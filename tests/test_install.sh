#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
python_bin="${CLAUDEX5_TEST_PYTHON:-$(command -v python3)}"

test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
test_home="$test_root/home"
mkdir -p "$test_home/.claude" "$test_home/.codex"
test_fake_bin="$test_root/initial-fake-bin"
mkdir -p "$test_fake_bin"
cat > "$test_fake_bin/claude" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
  --version) printf '%s\n' '2.1.32' ;;
  *) exit 0 ;;
esac
EOF
cat > "$test_fake_bin/codex" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
  --version) printf '%s\n' 'codex-cli test' ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$test_fake_bin/claude" "$test_fake_bin/codex"

printf '%s\n' "existing Claude instructions" > "$test_home/.claude/CLAUDE.md"
printf '%s\n' "existing Codex instructions" > "$test_home/.codex/AGENTS.md"
printf '%s\n' '{"model":"keep-model","hooks":{"Stop":[{"command":"keep-hook"}]},"statusLine":{"type":"command","command":"keep-status"},"skipDangerousModePermissionPrompt":true}' > "$test_home/.claude/settings.json"
cat > "$test_home/.codex/config.toml" <<'EOF'
personality = "keep-personality"

[features]
js_repl = false

[projects."/"]
trust_level = "trusted"

[mcp_servers.keep]
command = "keep-command"
EOF

run_install() {
  PATH="$test_fake_bin:$PATH" CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 \
    "$repo_root/install.sh" --home "$test_home" --skip-runtime-check
}

run_install

[[ -L "$test_home/.claude/agents/harness-orchestrator.md" ]]
[[ -L "$test_home/.claude/skills/claudex5-subagent-routing/SKILL.md" ]]
[[ -L "$test_home/.claude/statuslines/claudex5-subagent-models.py" ]]
[[ -L "$test_home/.claude/hooks/claudex5-live-graph.py" ]]
[[ -L "$test_home/.local/bin/claudex5" ]]
[[ -L "$test_home/.codex/agents/harness-sol-research.toml" ]]
[[ -L "$test_home/.codex/agents/harness-sol-plan-review.toml" ]]
[[ ! -e "$test_home/.codex/agents/harness-spark-ui-iteration.toml" ]]
[[ "$(readlink "$test_home/.claude/agents/harness-orchestrator.md")" == "$repo_root/claude/agents/harness-orchestrator.md" ]]
[[ "$(readlink "$test_home/.claude/skills/claudex5-subagent-routing/SKILL.md")" == "$repo_root/claude/skills/claudex5-subagent-routing/SKILL.md" ]]
[[ "$(readlink "$test_home/.claude/statuslines/claudex5-subagent-models.py")" == "$repo_root/claude/statuslines/claudex5-subagent-models.py" ]]
[[ "$(readlink "$test_home/.claude/hooks/claudex5-live-graph.py")" == "$repo_root/claude/hooks/claudex5-live-graph.py" ]]
[[ "$(readlink "$test_home/.local/bin/claudex5")" == "$repo_root/bin/claudex5" ]]
grep -q "existing Claude instructions" "$test_home/.claude/CLAUDE.md"
grep -q "existing Codex instructions" "$test_home/.codex/AGENTS.md"
[[ "$(grep -c 'BEGIN CLAUDEX5' "$test_home/.claude/CLAUDE.md")" -eq 1 ]]
[[ "$(grep -c '\[agents.harness_sol_review\]' "$test_home/.codex/config.toml")" -eq 1 ]]
[[ "$(grep -c '\[agents.harness_sol_plan_review\]' "$test_home/.codex/config.toml")" -eq 1 ]]

"$python_bin" - "$test_home" <<'PY'
import json
import sys
from pathlib import Path

home = Path(sys.argv[1])
settings = json.loads((home / ".claude/settings.json").read_text())
assert settings["model"] == "keep-model"
assert settings["hooks"]["Stop"][0]["command"] == "keep-hook"
expected_matchers = {
    "SessionStart": [None],
    "PreToolUse": ["TaskCreate"],
    "PostToolUse": ["TaskCreate", "TaskUpdate", "Agent"],
    "SubagentStart": [None],
    "SubagentStop": [None],
    "Stop": [None],
    "SessionEnd": [None],
}
for event, matchers in expected_matchers.items():
    owned = [
        group for group in settings["hooks"][event]
        if group.get("hooks") == [{
            "type": "command",
            "command": "~/.claude/hooks/claudex5-live-graph.py",
            "timeout": 5,
        }]
    ]
    assert [group.get("matcher") for group in owned] == matchers
assert settings["statusLine"] == {"type": "command", "command": "keep-status"}
assert settings["subagentStatusLine"] == {
    "type": "command",
    "command": "~/.claude/statuslines/claudex5-subagent-models.py",
}
assert settings["skipDangerousModePermissionPrompt"] is True
assert settings["enabledPlugins"]["codex@openai-codex"] is True

config = (home / ".codex/config.toml").read_text()
assert 'personality = "keep-personality"' in config
assert '[projects."/"]' in config
assert '[mcp_servers.keep]' in config
assert config.count("multi_agent = true") == 1
assert config.count("[agents.harness_sol_plan_review]") == 1
PY

run_install
[[ -L "$test_home/.claude/skills/claudex5-subagent-routing/SKILL.md" ]]
[[ "$(grep -c 'BEGIN CLAUDEX5' "$test_home/.claude/CLAUDE.md")" -eq 1 ]]
[[ "$(grep -c '\[agents.harness_sol_review\]' "$test_home/.codex/config.toml")" -eq 1 ]]
[[ "$(grep -c '\[agents.harness_sol_plan_review\]' "$test_home/.codex/config.toml")" -eq 1 ]]
[[ "$(find "$test_home/.local/state/claudex5-engineering-harness/backups" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" -ge 1 ]]

cp "$test_home/.claude/settings.json" "$test_root/settings-before-invalid.json"
printf '%s\n' '{invalid' > "$test_home/.claude/settings.json"
if CLAUDEX5_PYTHON="$python_bin" \
  "$repo_root/uninstall.sh" --home "$test_home" >/dev/null 2>&1; then
  printf '%s\n' "intermediate unmerge parse failure must fail uninstall" >&2
  exit 1
fi
[[ -L "$test_home/.local/bin/claudex5" ]]
[[ -L "$test_home/.claude/hooks/claudex5-live-graph.py" ]]
grep -q 'BEGIN CLAUDEX5' "$test_home/.claude/CLAUDE.md"
grep -q 'BEGIN CLAUDEX5' "$test_home/.codex/AGENTS.md"
grep -q '^{invalid$' "$test_home/.claude/settings.json"
cp "$test_root/settings-before-invalid.json" "$test_home/.claude/settings.json"

atomic_uninstall_home="$test_root/atomic-uninstall-home"
mkdir -p "$atomic_uninstall_home/.claude/hooks" "$atomic_uninstall_home/.claude" \
  "$atomic_uninstall_home/.codex" "$atomic_uninstall_home/.local/bin" \
  "$atomic_uninstall_home/.local/state/claudex5-engineering-harness/runs"
printf '%s\n' '{}' > "$atomic_uninstall_home/.claude/settings.json"
printf '%s\n' '' > "$atomic_uninstall_home/.codex/config.toml"
"$python_bin" "$repo_root/scripts/merge_config.py" install --home "$atomic_uninstall_home" --repo "$repo_root"
ln -s "$repo_root/bin/claudex5" "$atomic_uninstall_home/.local/bin/claudex5"
ln -s "$repo_root/claude/hooks/claudex5-live-graph.py" "$atomic_uninstall_home/.claude/hooks/claudex5-live-graph.py"
printf '%s\n' 'private history remains untouched' > "$atomic_uninstall_home/.local/state/claudex5-engineering-harness/runs/history.jsonl"
before_atomic_uninstall="$(shasum -a 256 "$atomic_uninstall_home/.claude/settings.json" "$atomic_uninstall_home/.claude/CLAUDE.md" "$atomic_uninstall_home/.codex/config.toml" "$atomic_uninstall_home/.codex/AGENTS.md")"
if CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_UNINSTALL_FAIL_AFTER_REMOVAL=1 \
  "$repo_root/uninstall.sh" --home "$atomic_uninstall_home" >/dev/null 2>&1; then
  printf '%s\n' "injected link-removal failure must fail whole uninstall" >&2
  exit 1
fi
[[ "$(shasum -a 256 "$atomic_uninstall_home/.claude/settings.json" "$atomic_uninstall_home/.claude/CLAUDE.md" "$atomic_uninstall_home/.codex/config.toml" "$atomic_uninstall_home/.codex/AGENTS.md")" == "$before_atomic_uninstall" ]]
[[ -L "$atomic_uninstall_home/.local/bin/claudex5" ]]
[[ -L "$atomic_uninstall_home/.claude/hooks/claudex5-live-graph.py" ]]
grep -q 'private history remains untouched' "$atomic_uninstall_home/.local/state/claudex5-engineering-harness/runs/history.jsonl"

exact_link_home="$test_root/exact-link-home"
mkdir -p "$exact_link_home/.claude/agents" "$exact_link_home/.claude/hooks" "$exact_link_home/.claude" \
  "$exact_link_home/.codex" "$exact_link_home/.local/bin"
printf '%s\n' '{}' > "$exact_link_home/.claude/settings.json"
printf '%s\n' '' > "$exact_link_home/.codex/config.toml"
"$python_bin" "$repo_root/scripts/merge_config.py" install --home "$exact_link_home" --repo "$repo_root"
ln -s "$repo_root/claude/agents/harness-orchestrator.md" "$exact_link_home/.claude/agents/harness-custom.md"
ln -s "$repo_root/claude/agents/harness-researcher.md" "$exact_link_home/.claude/agents/harness-orchestrator.md"
CLAUDEX5_PYTHON="$python_bin" "$repo_root/uninstall.sh" --home "$exact_link_home" >/dev/null
[[ -L "$exact_link_home/.claude/agents/harness-custom.md" ]]
[[ -L "$exact_link_home/.claude/agents/harness-orchestrator.md" ]]

CLAUDEX5_PYTHON="$python_bin" "$repo_root/uninstall.sh" --home "$test_home"
[[ ! -e "$test_home/.claude/agents/harness-orchestrator.md" ]]
[[ ! -e "$test_home/.claude/skills/claudex5-subagent-routing/SKILL.md" ]]
[[ ! -e "$test_home/.claude/statuslines/claudex5-subagent-models.py" ]]
[[ ! -e "$test_home/.claude/hooks/claudex5-live-graph.py" ]]
[[ ! -e "$test_home/.local/bin/claudex5" ]]
[[ ! -e "$test_home/.codex/agents/harness-sol-research.toml" ]]
[[ ! -e "$test_home/.codex/agents/harness-sol-plan-review.toml" ]]
! grep -q 'BEGIN CLAUDEX5' "$test_home/.claude/CLAUDE.md"
! grep -q '\[agents.harness_sol_review\]' "$test_home/.codex/config.toml"
! grep -q '\[agents.harness_sol_plan_review\]' "$test_home/.codex/config.toml"
grep -q "existing Claude instructions" "$test_home/.claude/CLAUDE.md"
grep -q 'personality = "keep-personality"' "$test_home/.codex/config.toml"
"$python_bin" - "$test_home" <<'PY'
import json
import sys
from pathlib import Path

settings = json.loads((Path(sys.argv[1]) / ".claude/settings.json").read_text())
assert settings["statusLine"] == {"type": "command", "command": "keep-status"}
assert "subagentStatusLine" not in settings
for groups in settings.get("hooks", {}).values():
    assert not any(
        group.get("hooks") == [{
            "type": "command",
            "command": "~/.claude/hooks/claudex5-live-graph.py",
            "timeout": 5,
        }]
        for group in groups if isinstance(group, dict)
    )
PY

collision_home="$test_root/collision-home"
mkdir -p "$collision_home/.claude/agents" "$collision_home/.codex"
printf '%s\n' "user-owned" > "$collision_home/.claude/agents/harness-orchestrator.md"
if CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 \
  "$repo_root/install.sh" --home "$collision_home" --skip-runtime-check >/dev/null 2>&1; then
  printf '%s\n' "installer unexpectedly overwrote a collision" >&2
  exit 1
fi
grep -q "user-owned" "$collision_home/.claude/agents/harness-orchestrator.md"

skill_collision_home="$test_root/skill-collision-home"
mkdir -p "$skill_collision_home/.claude/skills/claudex5-subagent-routing"
printf '%s\n' "user-owned skill" > "$skill_collision_home/.claude/skills/claudex5-subagent-routing/SKILL.md"
if CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 \
  "$repo_root/install.sh" --home "$skill_collision_home" --skip-runtime-check >/dev/null 2>&1; then
  printf '%s\n' "installer unexpectedly overwrote a skill collision" >&2
  exit 1
fi
grep -q "user-owned skill" "$skill_collision_home/.claude/skills/claudex5-subagent-routing/SKILL.md"

statusline_collision_home="$test_root/statusline-collision-home"
mkdir -p "$statusline_collision_home/.claude/statuslines"
printf '%s\n' "user-owned status line" > "$statusline_collision_home/.claude/statuslines/claudex5-subagent-models.py"
if CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 \
  "$repo_root/install.sh" --home "$statusline_collision_home" --skip-runtime-check >/dev/null 2>&1; then
  printf '%s\n' "installer unexpectedly overwrote a status-line collision" >&2
  exit 1
fi
grep -q "user-owned status line" "$statusline_collision_home/.claude/statuslines/claudex5-subagent-models.py"

foreign_status_home="$test_root/foreign-status-home"
mkdir -p "$foreign_status_home/.claude" "$foreign_status_home/.codex"
printf '%s\n' '{"subagentStatusLine":{"type":"command","command":"~/.claude/my-status.py"}}' > "$foreign_status_home/.claude/settings.json"
printf '%s\n' '' > "$foreign_status_home/.codex/config.toml"
foreign_status_log="$test_root/foreign-status.log"
CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 \
  "$repo_root/install.sh" --home "$foreign_status_home" --skip-runtime-check \
  >"$foreign_status_log" 2>&1
grep -q 'foreign subagentStatusLine is preserved' "$foreign_status_log"
"$python_bin" - "$foreign_status_home" <<'PY'
import json
import sys
from pathlib import Path

settings = json.loads((Path(sys.argv[1]) / ".claude/settings.json").read_text())
assert settings["subagentStatusLine"] == {
    "type": "command",
    "command": "~/.claude/my-status.py",
}
PY
CLAUDEX5_PYTHON="$python_bin" \
  "$repo_root/verify.sh" --home "$foreign_status_home" --strict --structural-only \
  >"$foreign_status_log" 2>&1
grep -q 'WARNING: foreign subagentStatusLine is preserved' "$foreign_status_log"

root_alias="$test_root/root-alias"
ln -s / "$root_alias"
if CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 \
  "$repo_root/install.sh" --home "$root_alias" --skip-runtime-check >/dev/null 2>&1; then
  printf '%s\n' "canonical root home must be rejected" >&2
  exit 1
fi

symlink_home="$test_root/symlink-home"
mkdir -p "$symlink_home" "$test_root/external-claude"
ln -s "$test_root/external-claude" "$symlink_home/.claude"
if CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 \
  "$repo_root/install.sh" --home "$symlink_home" --skip-runtime-check >/dev/null 2>&1; then
  printf '%s\n' "symlinked configuration directory must be rejected" >&2
  exit 1
fi

nested_symlink_home="$test_root/nested-symlink-home"
nested_external="$test_root/nested-external"
mkdir -p "$nested_symlink_home/.claude" "$nested_symlink_home/.codex" "$nested_external"
ln -s "$nested_external" "$nested_symlink_home/.claude/hooks"
if "$repo_root/link.sh" --home "$nested_symlink_home" >/dev/null 2>&1; then
  printf '%s\n' "linker must reject a nested managed-directory symlink" >&2
  exit 1
fi
if CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 \
  "$repo_root/install.sh" --home "$nested_symlink_home" --skip-runtime-check >/dev/null 2>&1; then
  printf '%s\n' "installer must reject a nested managed-directory symlink" >&2
  exit 1
fi
[[ ! -e "$nested_external/claudex5-live-graph.py" ]]

uninstall_symlink_home="$test_root/uninstall-symlink-home"
uninstall_external="$test_root/uninstall-external"
mkdir -p "$uninstall_symlink_home/.claude" "$uninstall_symlink_home/.codex" "$uninstall_external"
printf '%s\n' '{}' > "$uninstall_symlink_home/.claude/settings.json"
printf '%s\n' '' > "$uninstall_symlink_home/.codex/config.toml"
CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 \
  "$repo_root/install.sh" --home "$uninstall_symlink_home" --skip-runtime-check >/dev/null
mv "$uninstall_symlink_home/.claude/hooks" "$uninstall_symlink_home/.claude/hooks-real"
ln -s "$repo_root/claude/hooks/claudex5-live-graph.py" "$uninstall_external/claudex5-live-graph.py"
ln -s "$uninstall_external" "$uninstall_symlink_home/.claude/hooks"
if CLAUDEX5_PYTHON="$python_bin" \
  "$repo_root/uninstall.sh" --home "$uninstall_symlink_home" >/dev/null 2>&1; then
  printf '%s\n' "uninstaller must reject a nested managed-directory symlink" >&2
  exit 1
fi
[[ -L "$uninstall_external/claudex5-live-graph.py" ]]
grep -q 'BEGIN CLAUDEX5' "$uninstall_symlink_home/.claude/CLAUDE.md"

rollback_home="$test_root/rollback-home"
mkdir -p "$rollback_home/.claude" "$rollback_home/.codex"
printf '%s\n' "before rollback" > "$rollback_home/.claude/CLAUDE.md"
printf '%s\n' '{}' > "$rollback_home/.claude/settings.json"
printf '%s\n' '' > "$rollback_home/.codex/config.toml"
printf '%s\n' "before Codex rollback" > "$rollback_home/.codex/AGENTS.md"
if CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 CLAUDEX5_VERIFY_FAIL=1 \
  "$repo_root/install.sh" --home "$rollback_home" --skip-runtime-check >/dev/null 2>&1; then
  printf '%s\n' "injected verification failure must fail installation" >&2
  exit 1
fi
[[ "$(cat "$rollback_home/.claude/CLAUDE.md")" == "before rollback" ]]
[[ "$(cat "$rollback_home/.codex/AGENTS.md")" == "before Codex rollback" ]]
[[ ! -e "$rollback_home/.claude/agents/harness-orchestrator.md" ]]
[[ ! -e "$rollback_home/.claude/skills/claudex5-subagent-routing/SKILL.md" ]]
[[ ! -e "$rollback_home/.claude/statuslines/claudex5-subagent-models.py" ]]
[[ ! -e "$rollback_home/.codex/agents/harness-sol-plan-review.toml" ]]

fake_bin="$test_root/fake-bin"
spark_home="$test_root/spark-home"
mkdir -p "$fake_bin" "$spark_home/.claude" "$spark_home/.codex"
printf '%s\n' '{}' > "$spark_home/.claude/settings.json"
printf '%s\n' '' > "$spark_home/.codex/config.toml"
cat > "$fake_bin/claude" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
  --version) printf '%s\n' "${FAKE_CLAUDE_VERSION:-2.1.226 (Claude Code)}" ;;
  auth) exit 0 ;;
  plugin)
    if [[ "${FAKE_FABLE_ADVISOR_ENABLED:-0}" == "1" ]]; then
      cat <<'PLUGINS'
  ❯ fable-advisor@fable-advisor
    Version: 4.0.0
    Scope: user
    Status: ✔ enabled
PLUGINS
    fi
    ;;
  *) exit 0 ;;
esac
EOF
cat > "$fake_bin/codex" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
  --version) printf '%s\n' 'codex-cli 0.147.0' ;;
  login) exit 0 ;;
  app-server)
    IFS= read -r initialize
    printf '%s\n' '{"id":0,"result":{}}'
    IFS= read -r initialized
    IFS= read -r request
    if [[ "${FAKE_SPARK_AVAILABLE:-0}" == "1" ]]; then
      printf '%s\n' '{"id":1,"result":{"data":[{"id":"gpt-5.3-codex-spark","model":"gpt-5.3-codex-spark"}],"nextCursor":null}}'
    else
      printf '%s\n' '{"id":1,"result":{"data":[{"id":"gpt-5.6-sol","model":"gpt-5.6-sol"}],"nextCursor":null}}'
    fi
    ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$fake_bin/claude" "$fake_bin/codex"

unknown_version_home="$test_root/unknown-version-home"
unknown_version_log="$test_root/unknown-version.log"
mkdir -p "$unknown_version_home/.claude" "$unknown_version_home/.codex"
printf '%s\n' '{}' > "$unknown_version_home/.claude/settings.json"
printf '%s\n' '' > "$unknown_version_home/.codex/config.toml"
PATH="$fake_bin:$PATH" FAKE_CLAUDE_VERSION='2.1.84-beta.1' CLAUDEX5_PYTHON="$python_bin" \
  CLAUDEX5_SKIP_PLUGIN=1 "$repo_root/install.sh" --home "$unknown_version_home" --skip-runtime-check \
  >"$unknown_version_log" 2>&1
[[ "$(grep -c 'Claude Code version is unavailable or unsupported' "$unknown_version_log")" -eq 1 ]]
"$python_bin" - "$unknown_version_home" <<'PY'
import json
import sys
from pathlib import Path

hooks = json.loads((Path(sys.argv[1]) / ".claude/settings.json").read_text())["hooks"]
assert "TaskCreated" not in hooks and "TaskCompleted" not in hooks
PY

for version in 2.1.32 2.1.33 2.1.84 2.1.226; do
  version_home="$test_root/version-$version"
  mkdir -p "$version_home/.claude" "$version_home/.codex"
  printf '%s\n' '{"hooks":{"PostToolUse":[{"matcher":"Bash","hooks":[{"command":"~/.orca/hook.sh"}]}]}}' > "$version_home/.claude/settings.json"
  printf '%s\n' '' > "$version_home/.codex/config.toml"
  PATH="$fake_bin:$PATH" FAKE_CLAUDE_VERSION="$version" CLAUDEX5_PYTHON="$python_bin" \
    CLAUDEX5_SKIP_PLUGIN=1 "$repo_root/install.sh" --home "$version_home" --skip-runtime-check >/dev/null
  PATH="$fake_bin:$PATH" FAKE_CLAUDE_VERSION="$version" CLAUDEX5_PYTHON="$python_bin" \
    CLAUDEX5_SKIP_PLUGIN=1 "$repo_root/install.sh" --home "$version_home" --skip-runtime-check >/dev/null
  "$python_bin" - "$version_home" "$version" <<'PY'
import json
import sys
from pathlib import Path

home, version = Path(sys.argv[1]), sys.argv[2]
settings = json.loads((home / ".claude/settings.json").read_text())
hooks = settings["hooks"]
assert hooks["PostToolUse"][0]["matcher"] == "Bash"
expected = {"2.1.32": set(), "2.1.33": {"TaskCompleted"}, "2.1.84": {"TaskCompleted", "TaskCreated"}, "2.1.226": {"TaskCompleted", "TaskCreated"}}[version]
for event in ("TaskCompleted", "TaskCreated"):
    if event in expected:
        assert len(hooks[event]) == 1 and "matcher" not in hooks[event][0]
    else:
        assert event not in hooks
PY
  PATH="$fake_bin:$PATH" FAKE_CLAUDE_VERSION="$version" CLAUDEX5_PYTHON="$python_bin" \
    "$repo_root/verify.sh" --home "$version_home" --repo "$repo_root" --structural-only >/dev/null
  CLAUDEX5_PYTHON="$python_bin" "$repo_root/uninstall.sh" --home "$version_home" >/dev/null
  "$python_bin" - "$version_home" <<'PY'
import json
import sys
from pathlib import Path

hooks = json.loads((Path(sys.argv[1]) / ".claude/settings.json").read_text())["hooks"]
assert hooks["PostToolUse"] == [{"matcher": "Bash", "hooks": [{"command": "~/.orca/hook.sh"}]}]
assert "TaskCreated" not in hooks and "TaskCompleted" not in hooks
PY
done

PATH="$fake_bin:$PATH" FAKE_SPARK_AVAILABLE=1 CLAUDEX5_PYTHON="$python_bin" \
  CLAUDEX5_SKIP_PLUGIN=1 "$repo_root/install.sh" --home "$spark_home"
[[ -L "$spark_home/.codex/agents/harness-spark-ui-iteration.toml" ]]
grep -q '\[agents.harness_spark_ui_iteration\]' "$spark_home/.codex/config.toml"

if PATH="$fake_bin:$PATH" FAKE_SPARK_AVAILABLE=0 CLAUDEX5_PYTHON="$python_bin" \
  CLAUDEX5_SKIP_PLUGIN=1 CLAUDEX5_VERIFY_FAIL=1 \
  "$repo_root/install.sh" --home "$spark_home" >/dev/null 2>&1; then
  printf '%s\n' "injected verification failure must reject Spark disable reconciliation" >&2
  exit 1
fi
[[ -L "$spark_home/.codex/agents/harness-spark-ui-iteration.toml" ]]
grep -q '\[agents.harness_spark_ui_iteration\]' "$spark_home/.codex/config.toml"

PATH="$fake_bin:$PATH" FAKE_SPARK_AVAILABLE=0 CLAUDEX5_PYTHON="$python_bin" \
  CLAUDEX5_SKIP_PLUGIN=1 "$repo_root/install.sh" --home "$spark_home"
[[ ! -e "$spark_home/.codex/agents/harness-spark-ui-iteration.toml" ]]
! grep -q '\[agents.harness_spark_ui_iteration\]' "$spark_home/.codex/config.toml"

conflict_output="$test_root/fable-conflict.log"
PATH="$fake_bin:$PATH" FAKE_SPARK_AVAILABLE=0 FAKE_FABLE_ADVISOR_ENABLED=1 \
  CLAUDEX5_PYTHON="$python_bin" "$repo_root/verify.sh" --home "$spark_home" \
  >"$conflict_output" 2>&1
grep -q 'WARNING: fable-advisor is enabled' "$conflict_output"
grep -q 'claude plugin disable fable-advisor@fable-advisor' "$conflict_output"
if PATH="$fake_bin:$PATH" FAKE_SPARK_AVAILABLE=0 FAKE_FABLE_ADVISOR_ENABLED=1 \
  CLAUDEX5_PYTHON="$python_bin" "$repo_root/verify.sh" --home "$spark_home" --strict \
  >"$conflict_output" 2>&1; then
  printf '%s\n' "strict verification must reject enabled fable-advisor" >&2
  exit 1
fi
grep -q 'FAIL: fable-advisor is enabled' "$conflict_output"

spark_collision_home="$test_root/spark-collision-home"
mkdir -p "$spark_collision_home/.codex/agents"
printf '%s\n' "user-owned Spark role" > "$spark_collision_home/.codex/agents/harness-spark-ui-iteration.toml"
if "$repo_root/link.sh" --home "$spark_collision_home" --enable-spark >/dev/null 2>&1; then
  printf '%s\n' "Spark registration unexpectedly overwrote a collision" >&2
  exit 1
fi
grep -q "user-owned Spark role" "$spark_collision_home/.codex/agents/harness-spark-ui-iteration.toml"

printf '%s\n' "integration tests: PASS"
