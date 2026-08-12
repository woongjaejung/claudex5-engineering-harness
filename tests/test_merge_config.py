import json
import os
import subprocess
import tempfile
import tomllib
import unittest
import unittest.mock
from pathlib import Path

import scripts.merge_config as merge_config_module
from scripts.plugin_registry import resolve_codex_helper
from scripts.merge_config import (
    END_MARKER,
    START_MARKER,
    merge_claude_settings,
    merge_codex_config,
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
                        "enabledPlugins": {"existing@plugin": True},
                    }
                ),
                encoding="utf-8",
            )

            merge_claude_settings(path, enable_plugin=True)
            merged = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(merged["model"], "existing-model")
            self.assertEqual(merged["hooks"]["Stop"], [{"command": "keep-me"}])
            self.assertTrue(merged["enabledPlugins"]["existing@plugin"])
            self.assertTrue(merged["enabledPlugins"]["codex@openai-codex"])
            self.assertEqual(
                merged["extraKnownMarketplaces"]["openai-codex"]["source"]["repo"],
                "openai/codex-plugin-cc",
            )

    def test_invalid_json_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("{invalid", encoding="utf-8")
            before = path.read_bytes()

            with self.assertRaises(json.JSONDecodeError):
                merge_claude_settings(path, enable_plugin=True)

            self.assertEqual(path.read_bytes(), before)


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

            warnings = merge_codex_config(path, root / "agents", harden=False)
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
            "harness-judge.md": "claude-fable-5",
            "harness-judge-opus.md": "claude-opus-5",
        }
        directory = self.repository / "claude" / "agents"
        actual = {path.name: self._frontmatter(path) for path in directory.glob("*.md")}

        self.assertEqual(set(actual), set(expected))
        self.assertEqual(len({item["name"] for item in actual.values()}), 8)
        for filename, model in expected.items():
            self.assertEqual(actual[filename]["model"], model)
            self.assertEqual(actual[filename]["effort"], "high")

    def test_codex_roles_match_model_and_effort_matrix(self):
        expected = {
            "harness-sol-research.toml": ("gpt-5.6-sol", "high"),
            "harness-luna-implementation.toml": ("gpt-5.6-luna", "max"),
            "harness-sol-review.toml": ("gpt-5.6-sol", "high"),
            "harness-sol-adversarial-review.toml": ("gpt-5.6-sol", "high"),
        }
        directory = self.repository / "codex" / "agents"
        actual = {
            path.name: tomllib.loads(path.read_text(encoding="utf-8"))
            for path in directory.glob("*.toml")
        }

        self.assertEqual(set(actual), set(expected))
        for filename, (model, effort) in expected.items():
            self.assertEqual(actual[filename]["model"], model)
            self.assertEqual(actual[filename]["model_reasoning_effort"], effort)
            self.assertTrue(actual[filename]["developer_instructions"].strip())

    def test_quality_gate_runs_available_package_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "calls.log"
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
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(log.read_text(encoding="utf-8"), "lint\ntest\n")


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
