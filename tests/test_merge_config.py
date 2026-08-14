import hashlib
import json
import os
import re
import subprocess
import tempfile
import tomllib
import unittest
import unittest.mock
from pathlib import Path

import scripts.merge_config as merge_config_module
from scripts.plugin_registry import resolve_codex_helper
from scripts.merge_config import (
    BASE_CLAUDEX5_HOOK_GROUPS,
    CLAUDEX5_HOOK_GROUPS,
    END_MARKER,
    START_MARKER,
    merge_claude_settings,
    merge_codex_config,
    remove_harness_config,
    replace_managed_block,
)


class ManagedBlockTests(unittest.TestCase):
    def test_repeated_merge_produces_one_managed_block(self):
        original = "user instructions\n"
        once = replace_managed_block(original, START_MARKER, END_MARKER, "managed\n")
        twice = replace_managed_block(once, START_MARKER, END_MARKER, "managed\n")

        self.assertEqual(once, twice)
        self.assertEqual(twice.count(START_MARKER), 1)
        self.assertTrue(twice.startswith(original))

    def test_unbalanced_marker_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unbalanced"):
            replace_managed_block(START_MARKER + "\nbroken", START_MARKER, END_MARKER, "managed")


class ClaudeSettingsTests(unittest.TestCase):
    def test_merge_preserves_existing_hooks_and_enables_official_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "model": "existing-model",
                        "hooks": {"Stop": [{"command": "keep-me"}]},
                        "statusLine": {"type": "command", "command": "keep-status"},
                        "enabledPlugins": {"existing@plugin": True},
                    }
                ),
                encoding="utf-8",
            )

            merge_claude_settings(path, enable_plugin=True)
            merged = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(merged["model"], "existing-model")
            self.assertEqual(merged["hooks"]["Stop"][0], {"command": "keep-me"})
            self.assertIn(CLAUDEX5_HOOK_GROUPS["Stop"][0], merged["hooks"]["Stop"])
            self.assertEqual(
                merged["statusLine"], {"type": "command", "command": "keep-status"}
            )
            self.assertEqual(
                merged["subagentStatusLine"],
                {
                    "type": "command",
                    "command": "~/.claude/statuslines/claudex5-subagent-models.py",
                },
            )
            self.assertTrue(merged["enabledPlugins"]["existing@plugin"])
            self.assertTrue(merged["enabledPlugins"]["codex@openai-codex"])
            self.assertEqual(
                merged["extraKnownMarketplaces"]["openai-codex"]["source"]["repo"],
                "openai/codex-plugin-cc",
            )

    def test_hook_merge_is_idempotent_and_preserves_foreign_shapes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            foreign_current = {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": "~/.orca/hook.sh"}],
            }
            path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "SessionStart": [foreign_current],
                            "Stop": [{"command": "legacy-hook"}],
                        },
                        "statusLine": {"type": "command", "command": "keep-status"},
                        "subagentStatusLine": {"type": "command", "command": "keep-subagent"},
                    }
                ),
                encoding="utf-8",
            )

            merge_claude_settings(path, enable_plugin=True)
            merge_claude_settings(path, enable_plugin=True)
            merged = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(merged["hooks"]["SessionStart"][0], foreign_current)
            self.assertEqual(merged["hooks"]["Stop"][0], {"command": "legacy-hook"})
            for event, owned_groups in BASE_CLAUDEX5_HOOK_GROUPS.items():
                for owned in owned_groups:
                    self.assertEqual(merged["hooks"][event].count(owned), 1)
            self.assertEqual(merged["statusLine"]["command"], "keep-status")
            self.assertEqual(merged["subagentStatusLine"]["command"], "keep-subagent")

    def test_invalid_json_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("{invalid", encoding="utf-8")
            before = path.read_bytes()

            with self.assertRaises(json.JSONDecodeError):
                merge_claude_settings(path, enable_plugin=True)

            self.assertEqual(path.read_bytes(), before)

    def test_foreign_subagent_status_line_is_preserved_with_warning(self):
        foreign_values = (
            {"type": "command", "command": "~/.claude/my-status.py"},
            None,
            "custom-renderer",
        )
        for foreign in foreign_values:
            with self.subTest(foreign=foreign), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "settings.json"
                path.write_text(
                    json.dumps({"subagentStatusLine": foreign}), encoding="utf-8"
                )

                warnings = merge_claude_settings(path, enable_plugin=True)
                merged = json.loads(path.read_text(encoding="utf-8"))

                self.assertEqual(merged["subagentStatusLine"], foreign)
                self.assertTrue(
                    any("foreign subagentStatusLine" in item for item in warnings)
                )

    def test_uninstall_removes_only_owned_subagent_status_line(self):
        owned = {
            "type": "command",
            "command": "~/.claude/statuslines/claudex5-subagent-models.py",
        }
        foreign = {"type": "command", "command": "~/.claude/my-status.py"}
        for initial, should_remain in ((owned, False), (foreign, True)):
            with self.subTest(initial=initial), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                (home / ".claude").mkdir()
                settings = home / ".claude/settings.json"
                settings.write_text(
                    json.dumps(
                        {
                            "statusLine": {"type": "command", "command": "keep-status"},
                            "subagentStatusLine": initial,
                        }
                    ),
                    encoding="utf-8",
                )

                remove_harness_config(home)
                result = json.loads(settings.read_text(encoding="utf-8"))

                self.assertEqual(
                    result["statusLine"], {"type": "command", "command": "keep-status"}
                )
                self.assertEqual("subagentStatusLine" in result, should_remain)
                if should_remain:
                    self.assertEqual(result["subagentStatusLine"], foreign)

    def test_uninstall_removes_only_exact_owned_hook_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".claude").mkdir()
            settings_path = home / ".claude/settings.json"
            foreign = {
                "hooks": [{"type": "command", "command": "~/.claude/hooks/other.py"}]
            }
            settings_path.write_text("{}", encoding="utf-8")
            merge_claude_settings(settings_path, enable_plugin=False)
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            settings["hooks"]["Stop"].insert(0, foreign)
            settings_path.write_text(json.dumps(settings), encoding="utf-8")

            remove_harness_config(home)
            result = json.loads(settings_path.read_text(encoding="utf-8"))

            self.assertEqual(result["hooks"]["Stop"], [foreign])
            for event in CLAUDEX5_HOOK_GROUPS:
                if event != "Stop":
                    self.assertNotIn(event, result.get("hooks", {}))

    def test_capability_gated_hooks_normalize_duplicates_and_remove_downgraded_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            foreign = {"matcher": "Bash", "hooks": [{"command": "~/.orca/hook.sh"}]}
            task_created = {"hooks": [{"type": "command", "command": "~/.claude/hooks/claudex5-live-graph.py", "timeout": 5}]}
            path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PostToolUse": [foreign],
                            "TaskCreated": [task_created, task_created],
                            "TaskCompleted": [task_created],
                        }
                    }
                ),
                encoding="utf-8",
            )

            merge_claude_settings(
                path, enable_plugin=False, enable_task_created=True, enable_task_completed=True
            )
            merge_claude_settings(
                path, enable_plugin=False, enable_task_created=True, enable_task_completed=True
            )
            latest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(latest["hooks"]["PostToolUse"][0], foreign)
            for event, owned_groups in CLAUDEX5_HOOK_GROUPS.items():
                for owned in owned_groups:
                    self.assertEqual(latest["hooks"][event].count(owned), 1)
            self.assertNotIn("matcher", latest["hooks"]["TaskCreated"][0])
            self.assertNotIn("matcher", latest["hooks"]["TaskCompleted"][0])

            merge_claude_settings(path, enable_plugin=False)
            downgraded = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("TaskCreated", downgraded["hooks"])
            self.assertNotIn("TaskCompleted", downgraded["hooks"])
            self.assertEqual(downgraded["hooks"]["PostToolUse"][0], foreign)

    def test_uninstall_rolls_back_every_owned_file_after_an_intermediate_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".claude").mkdir()
            (home / ".codex").mkdir()
            targets = (
                home / ".claude" / "CLAUDE.md",
                home / ".codex" / "AGENTS.md",
                home / ".claude" / "settings.json",
                home / ".codex" / "config.toml",
            )
            targets[0].write_text(
                f"before\n{START_MARKER}\nmanaged\n{END_MARKER}\n", encoding="utf-8"
            )
            targets[1].write_text(
                f"before codex\n{START_MARKER}\nmanaged\n{END_MARKER}\n", encoding="utf-8"
            )
            targets[2].write_text("{}\n", encoding="utf-8")
            targets[3].write_text("personality = \"keep\"\n", encoding="utf-8")
            originals = {path: path.read_bytes() for path in targets}
            real_atomic_write = merge_config_module.atomic_write
            calls = 0

            def fail_second_write(path, text, mode=None):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected intermediate unmerge failure")
                return real_atomic_write(path, text, mode)

            with unittest.mock.patch.object(
                merge_config_module, "atomic_write", side_effect=fail_second_write
            ):
                with self.assertRaisesRegex(OSError, "intermediate unmerge"):
                    remove_harness_config(home)

            self.assertGreaterEqual(calls, 3)
            self.assertEqual({path: path.read_bytes() for path in targets}, originals)

    def test_uninstall_rolls_back_if_post_removal_state_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".claude").mkdir()
            (home / ".codex").mkdir()
            claude_md = home / ".claude" / "CLAUDE.md"
            claude_md.write_text(f"before\n{START_MARKER}\nmanaged\n{END_MARKER}\n")
            (home / ".claude" / "settings.json").write_text("{}\n")
            state_file = home / "state.tsv"
            original = claude_md.read_bytes()
            real_atomic_write = merge_config_module.atomic_write

            def fail_state_publish(path, text, mode=None):
                if path == state_file:
                    raise OSError("injected state publication failure")
                return real_atomic_write(path, text, mode)

            with unittest.mock.patch.object(
                merge_config_module, "atomic_write", side_effect=fail_state_publish
            ):
                with self.assertRaisesRegex(OSError, "state publication"):
                    remove_harness_config(home, state_file)
            self.assertEqual(claude_md.read_bytes(), original)

    def test_install_aborts_without_overwriting_concurrent_foreign_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".claude").mkdir()
            (home / ".codex").mkdir()
            settings_path = home / ".claude" / "settings.json"
            settings_path.write_text('{"foreign":"before"}\n', encoding="utf-8")
            (home / ".codex" / "config.toml").write_text("", encoding="utf-8")
            real_atomic_write = merge_config_module.atomic_write
            changed = False

            def inject_concurrent_edit(path, text, mode=None):
                nonlocal changed
                if path == settings_path and not changed:
                    settings_path.write_text('{"foreign":"concurrent"}\n', encoding="utf-8")
                    changed = True
                return real_atomic_write(path, text, mode)

            with unittest.mock.patch.object(
                merge_config_module, "atomic_write", side_effect=inject_concurrent_edit
            ):
                with self.assertRaisesRegex(RuntimeError, "configuration changed concurrently"):
                    merge_config_module.install_from_repository(
                        home,
                        Path(__file__).resolve().parents[1],
                        harden=False,
                    )

            self.assertTrue(changed)
            self.assertEqual(
                json.loads(settings_path.read_text(encoding="utf-8")),
                {"foreign": "concurrent"},
            )
            self.assertFalse((home / ".claude" / "CLAUDE.md").exists())
            self.assertFalse((home / ".codex" / "AGENTS.md").exists())

    def test_uninstall_state_uses_committed_payload_not_concurrent_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".claude").mkdir()
            (home / ".codex").mkdir()
            claude_md = home / ".claude" / "CLAUDE.md"
            claude_md.write_text(f"before\n{START_MARKER}\nmanaged\n{END_MARKER}\n")
            (home / ".claude" / "settings.json").write_text("{}\n")
            state_file = home / "state.tsv"
            real_atomic_write = merge_config_module.atomic_write

            def concurrent_edit_after_write(path, text, mode=None):
                result = real_atomic_write(path, text, mode)
                if path == claude_md:
                    claude_md.write_text("concurrent user change\n")
                return result

            with unittest.mock.patch.object(
                merge_config_module, "atomic_write", side_effect=concurrent_edit_after_write
            ):
                remove_harness_config(home, state_file)

            expected = hashlib.sha256(b"before\n").hexdigest()
            published = dict(
                (line.split("\t", 1)[0], line.split("\t", 1)[1])
                for line in state_file.read_text().splitlines()
            )
            self.assertEqual(published[".claude/CLAUDE.md"], f"present\t{expected}")
            self.assertEqual(claude_md.read_text(), "concurrent user change\n")


class CodexConfigTests(unittest.TestCase):
    def test_merge_preserves_existing_sections_and_warns_without_hardening(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.toml"
            path.write_text(
                'model = "gpt-existing"\n\n'
                '[features]\njs_repl = false\n\n'
                '[projects."/"]\ntrust_level = "trusted"\n\n'
                '[mcp_servers.keep]\ncommand = "keep"\n',
                encoding="utf-8",
            )

            warnings = merge_codex_config(path, root / "agents", harden=False, enable_spark=False)
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(parsed["model"], "gpt-existing")
            self.assertFalse(parsed["features"]["js_repl"])
            self.assertTrue(parsed["features"]["multi_agent"])
            self.assertEqual(parsed["projects"]["/"]["trust_level"], "trusted")
            self.assertEqual(parsed["mcp_servers"]["keep"]["command"], "keep")
            self.assertTrue(any("root project trust" in item for item in warnings))
            self.assertEqual(
                parsed["agents"]["harness_sol_research"]["config_file"],
                str(root / "agents" / "harness-sol-research.toml"),
            )

    def test_repeated_merge_does_not_duplicate_features_or_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.toml"
            path.write_text('personality = "pragmatic"\n', encoding="utf-8")

            merge_codex_config(path, root / "agents", harden=False)
            once = path.read_text(encoding="utf-8")
            merge_codex_config(path, root / "agents", harden=False)
            twice = path.read_text(encoding="utf-8")

            self.assertEqual(once, twice)
            self.assertEqual(twice.count("[features]"), 1)
            self.assertEqual(twice.count("[agents.harness_sol_review]"), 1)

    def test_spark_agent_is_registered_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.toml"
            path.write_text('personality = "pragmatic"\n', encoding="utf-8")

            merge_codex_config(path, root / "agents", harden=False, enable_spark=True)
            enabled = tomllib.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(
                enabled["agents"]["harness_spark_ui_iteration"]["config_file"],
                str(root / "agents" / "harness-spark-ui-iteration.toml"),
            )

            merge_codex_config(path, root / "agents", harden=False, enable_spark=False)
            disabled = tomllib.loads(path.read_text(encoding="utf-8"))

            self.assertNotIn("harness_spark_ui_iteration", disabled["agents"])

    def test_hardening_removes_only_exact_root_trust_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.toml"
            path.write_text(
                '[projects."/"]\ntrust_level = "trusted"\n\n'
                '[projects."/srv/app"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )

            merge_codex_config(path, root / "agents", harden=True)
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))

            self.assertNotIn("/", parsed.get("projects", {}))
            self.assertEqual(parsed["projects"]["/srv/app"]["trust_level"], "trusted")

    def test_invalid_toml_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[broken\n", encoding="utf-8")
            before = path.read_bytes()

            with self.assertRaises(tomllib.TOMLDecodeError):
                merge_codex_config(path, Path(directory) / "agents", harden=False)

            self.assertEqual(path.read_bytes(), before)

    def test_reinstall_preserves_following_array_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.toml"
            path.write_text(
                '[agents.harness_sol_review]\nconfig_file = "old"\n\n'
                '[[notifications]]\ncommand = "keep"\n',
                encoding="utf-8",
            )

            merge_codex_config(path, root / "agents", harden=False)
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(parsed["notifications"], [{"command": "keep"}])

    def test_reinstall_preserves_quoted_array_header_containing_bracket(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.toml"
            path.write_text(
                '[agents.harness_sol_review]\nconfig_file = "old"\n\n'
                '[["user]array"]]\ncommand = "keep"\n',
                encoding="utf-8",
            )

            merge_codex_config(path, root / "agents", harden=False)
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(parsed["user]array"], [{"command": "keep"}])

    def test_reinstall_ignores_header_like_text_inside_multiline_string(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.toml"
            path.write_text(
                'message = """\n[not.a.header]\nkeep this text\n"""\n\n'
                '[agents.harness_sol_review]\nconfig_file = "old"\n\n'
                '[after]\nvalue = "keep"\n',
                encoding="utf-8",
            )

            merge_codex_config(path, root / "agents", harden=False)
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))

            self.assertIn("[not.a.header]", parsed["message"])
            self.assertEqual(parsed["after"]["value"], "keep")

    def test_failed_install_rollback_does_not_overwrite_concurrent_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            repository = root / "repository"
            (home / ".claude").mkdir(parents=True)
            (home / ".codex").mkdir(parents=True)
            (repository / "claude").mkdir(parents=True)
            (repository / "codex").mkdir(parents=True)
            (repository / "claude/managed-CLAUDE.md").write_text("managed", encoding="utf-8")
            (repository / "codex/managed-AGENTS.md").write_text("managed", encoding="utf-8")
            claude_md = home / ".claude/CLAUDE.md"
            claude_md.write_text("original\n", encoding="utf-8")
            (home / ".codex/AGENTS.md").write_text("original\n", encoding="utf-8")
            (home / ".claude/settings.json").write_text("{}", encoding="utf-8")
            (home / ".codex/config.toml").write_text("[broken\n", encoding="utf-8")

            original_merge = merge_config_module.merge_instruction_file
            calls = 0

            def concurrent_change(path, body):
                nonlocal calls
                original_merge(path, body)
                calls += 1
                if calls == 1:
                    path.write_text("concurrent user change\n", encoding="utf-8")

            with unittest.mock.patch.object(
                merge_config_module, "merge_instruction_file", side_effect=concurrent_change
            ):
                with self.assertRaises(tomllib.TOMLDecodeError):
                    merge_config_module.install_from_repository(home, repository, harden=False)

            self.assertEqual(claude_md.read_text(encoding="utf-8"), "concurrent user change\n")

    def test_hardening_rejects_inline_root_trust_without_modifying_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.toml"
            path.write_text(
                'projects = { "/" = { trust_level = "trusted" } }\n',
                encoding="utf-8",
            )
            before = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "inline root project trust"):
                merge_codex_config(path, root / "agents", harden=True)

            self.assertEqual(path.read_bytes(), before)

    def test_symlinked_configuration_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real.json"
            link = root / "settings.json"
            real.write_text("{}", encoding="utf-8")
            link.symlink_to(real)

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                merge_claude_settings(link, enable_plugin=True)

            self.assertEqual(real.read_text(encoding="utf-8"), "{}")


class TemplateTests(unittest.TestCase):
    repository = Path(__file__).resolve().parents[1]

    @staticmethod
    def _frontmatter(path: Path) -> dict[str, str]:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0] != "---":
            raise AssertionError(f"missing frontmatter: {path}")
        result: dict[str, str] = {}
        for line in lines[1:]:
            if line == "---":
                return result
            key, separator, value = line.partition(":")
            if separator:
                result[key.strip()] = value.strip()
        raise AssertionError(f"unterminated frontmatter: {path}")

    def test_claude_roles_have_unique_names_and_expected_models(self):
        expected = {
            "harness-orchestrator.md": "claude-fable-5",
            "harness-orchestrator-opus.md": "claude-opus-5",
            "harness-researcher.md": "claude-sonnet-5",
            "harness-implementer.md": "claude-sonnet-5",
            "harness-implementer-opus.md": "claude-opus-5",
            "harness-architecture-reviewer.md": "claude-opus-5",
            "harness-code-reviewer.md": "claude-opus-5",
            "harness-judge.md": "claude-fable-5",
            "harness-judge-opus.md": "claude-opus-5",
        }
        directory = self.repository / "claude" / "agents"
        actual = {path.name: self._frontmatter(path) for path in directory.glob("*.md")}

        self.assertEqual(set(actual), set(expected))
        self.assertEqual(len({item["name"] for item in actual.values()}), 9)
        for filename, model in expected.items():
            self.assertEqual(actual[filename]["model"], model)
            self.assertEqual(actual[filename]["effort"], "high")

    def test_codex_roles_match_model_and_effort_matrix(self):
        expected = {
            "harness-sol-research.toml": ("gpt-5.6-sol", "high"),
            "harness-sol-plan-review.toml": ("gpt-5.6-sol", "high"),
            "harness-luna-implementation.toml": ("gpt-5.6-luna", "max"),
            "harness-sol-review.toml": ("gpt-5.6-sol", "high"),
            "harness-sol-adversarial-review.toml": ("gpt-5.6-sol", "high"),
            "harness-spark-ui-iteration.toml": ("gpt-5.3-codex-spark", None),
        }
        directory = self.repository / "codex" / "agents"
        actual = {
            path.name: tomllib.loads(path.read_text(encoding="utf-8"))
            for path in directory.glob("*.toml")
        }

        self.assertEqual(set(actual), set(expected))
        for filename, (model, effort) in expected.items():
            self.assertEqual(actual[filename]["model"], model)
            if effort is None:
                self.assertNotIn("model_reasoning_effort", actual[filename])
            else:
                self.assertEqual(actual[filename]["model_reasoning_effort"], effort)
            self.assertTrue(actual[filename]["developer_instructions"].strip())

        plan_review = actual["harness-sol-plan-review.toml"]["developer_instructions"]
        for required in (
            "fresh context",
            "without editing files",
            "APPROVE",
            "NEEDS CHANGES",
            "requirements",
            "assumptions",
            "dependency",
            "test-first",
            "security",
            "migration",
            "rollback",
            "recovery",
            "simpler",
        ):
            self.assertIn(required, plan_review)

    def test_root_readme_is_english_only(self):
        readme = (self.repository / "README.md").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"[가-힣]", readme))

    def test_superpowers_adapter_skill_contract(self):
        skill_path = (
            self.repository
            / "claude"
            / "skills"
            / "claudex5-subagent-routing"
            / "SKILL.md"
        )
        self.assertTrue(skill_path.is_file(), f"missing adapter skill: {skill_path}")

        frontmatter = self._frontmatter(skill_path)
        self.assertEqual(set(frontmatter), {"name", "description"})
        self.assertEqual(frontmatter["name"], "claudex5-subagent-routing")
        self.assertTrue(frontmatter["description"].startswith("Use when "))
        self.assertIn("Superpowers", frontmatter["description"])
        self.assertIn("subagent-driven-development", frontmatter["description"])
        self.assertIn("executing-plans", frontmatter["description"])

        content = skill_path.read_text(encoding="utf-8")
        for required in (
            "harness-researcher",
            "harness-implementer",
            "harness-implementer-opus",
            "harness-architecture-reviewer",
            "harness-code-reviewer",
            "harness-judge",
            "gpt-5.6-sol",
            "fable-advisor",
            "Grok",
            "build",
            "lint",
            "typecheck",
            "test",
        ):
            self.assertIn(required, content)
        self.assertIn("only when the user explicitly names", content)
        self.assertLess(len(re.findall(r"\b[\w.-]+\b", content)), 500)

        managed = (self.repository / "claude" / "managed-CLAUDE.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("claudex5-subagent-routing", managed)
        self.assertIn("subagent-driven-development", managed)
        self.assertIn("executing-plans", managed)

    def test_complex_plans_require_bounded_sol_review_before_implementation(self):
        paths = (
            self.repository / "claude/managed-CLAUDE.md",
            self.repository / "claude/agents/harness-orchestrator.md",
            self.repository / "claude/skills/claudex5-subagent-routing/SKILL.md",
            self.repository / "codex/managed-AGENTS.md",
        )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for required in (
            "harness_sol_plan_review",
            "[Codex Sol · high] Plan review",
            "multiple modules or services",
            "authentication",
            "authorization",
            "security",
            "data migration",
            "destructive state",
            "rollback",
            "architecture",
            "operational risk",
            "ambiguous",
            "multiple viable approaches",
            "five or more executable tasks",
            "simple plans",
            "fresh",
            "read-only",
            "gpt-5.6-sol",
            "APPROVE",
            "NEEDS CHANGES",
            "Fable remains the plan owner",
            "one fresh recheck",
            "stop before implementation",
            "ask the user",
        ):
            self.assertIn(required, combined)

        skill = paths[2].read_text(encoding="utf-8")
        self.assertLess(len(re.findall(r"\b[\w.-]+\b", skill)), 500)

    def test_quality_gate_runs_available_package_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "calls.log"
            harness_log = root / "harness.log"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake = fake_bin / "claudex5"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%q ' \"$@\" >> \"$HARNESS_LOG\"; printf '\\\\n' >> \"$HARNESS_LOG\"\n"
                "if [[ \"${1:-}\" == event ]]; then exit 0; fi\n"
                "while [[ $# -gt 0 && \"$1\" != -- ]]; do shift; done\n"
                "[[ $# -gt 0 ]] && shift\n"
                "exec \"$@\"\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            package = {
                "scripts": {
                    "lint": f"printf 'lint\\n' >> {log}",
                    "test": f"printf 'test\\n' >> {log}",
                }
            }
            (root / "package.json").write_text(json.dumps(package), encoding="utf-8")
            gate = self.repository / "project-template" / "scripts" / "quality-gate.sh"
            result = subprocess.run(
                ["/bin/bash", str(gate)],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
                    "HARNESS_LOG": str(harness_log),
                    "CLAUDEX5_SESSION_ID": "quality-session",
                },
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(log.read_text(encoding="utf-8"), "lint\ntest\n")
            observed = harness_log.read_text(encoding="utf-8")
            self.assertIn("event --session-id quality-session --type node.started", observed)
            self.assertIn("gate-run --session-id quality-session", observed)
            self.assertIn("--name lint", observed)
            self.assertIn("--name test", observed)
            self.assertIn("--type node.finished", observed)
            self.assertIn("--state passed", observed)

    def test_quality_gate_falls_back_when_graph_telemetry_cannot_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "calls.log"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake = fake_bin / "claudex5"
            fake.write_text("#!/usr/bin/env bash\nexit 70\n", encoding="utf-8")
            fake.chmod(0o755)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"lint": f"printf 'lint\\n' >> {log}"}}),
                encoding="utf-8",
            )
            gate = self.repository / "project-template" / "scripts" / "quality-gate.sh"

            result = subprocess.run(
                ["/bin/bash", str(gate)],
                cwd=root,
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(log.read_text(encoding="utf-8"), "lint\n")
            self.assertIn("graph telemetry could not start", result.stderr)


class PluginRegistryTests(unittest.TestCase):
    def test_symlinked_official_cache_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            external = home / "external-cache"
            helper = external / "1.0.0/scripts/codex-companion.mjs"
            helper.parent.mkdir(parents=True)
            helper.write_text("external", encoding="utf-8")
            cache_parent = home / ".claude/plugins/cache/openai-codex"
            cache_parent.mkdir(parents=True)
            (cache_parent / "codex").symlink_to(external, target_is_directory=True)
            registry = home / ".claude/plugins/installed_plugins.json"
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(
                json.dumps(
                    {"plugins": {"codex@openai-codex": [{"installPath": str(external / "1.0.0")}]}},
                ),
                encoding="utf-8",
            )

            self.assertIsNone(resolve_codex_helper(registry, home))

    def test_external_symlink_helper_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            install = home / ".claude/plugins/cache/openai-codex/codex/1.0.0"
            scripts = install / "scripts"
            scripts.mkdir(parents=True)
            external = home / "external.mjs"
            external.write_text("malicious", encoding="utf-8")
            (scripts / "codex-companion.mjs").symlink_to(external)
            registry = home / ".claude/plugins/installed_plugins.json"
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(
                json.dumps({"plugins": {"codex@openai-codex": [{"installPath": str(install)}]}}),
                encoding="utf-8",
            )

            self.assertIsNone(resolve_codex_helper(registry, home))

    def test_regular_helper_inside_official_cache_is_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            install = home / ".claude/plugins/cache/openai-codex/codex/1.0.0"
            helper = install / "scripts/codex-companion.mjs"
            helper.parent.mkdir(parents=True)
            helper.write_text("safe", encoding="utf-8")
            registry = home / ".claude/plugins/installed_plugins.json"
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(
                json.dumps({"plugins": {"codex@openai-codex": [{"installPath": str(install)}]}}),
                encoding="utf-8",
            )

            self.assertEqual(resolve_codex_helper(registry, home), helper.resolve())


if __name__ == "__main__":
    unittest.main()
