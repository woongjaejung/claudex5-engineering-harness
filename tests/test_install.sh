#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
python_bin="${CLAUDEX5_TEST_PYTHON:-$(command -v python3)}"

test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
test_home="$test_root/home"
mkdir -p "$test_home/.claude" "$test_home/.codex"

printf '%s\n' "existing Claude instructions" > "$test_home/.claude/CLAUDE.md"
printf '%s\n' "existing Codex instructions" > "$test_home/.codex/AGENTS.md"
printf '%s\n' '{"model":"keep-model","hooks":{"Stop":[{"command":"keep-hook"}]},"skipDangerousModePermissionPrompt":true}' > "$test_home/.claude/settings.json"
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
  CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 \
    "$repo_root/install.sh" --home "$test_home" --skip-runtime-check
}

run_install

[[ -L "$test_home/.claude/agents/harness-orchestrator.md" ]]
[[ -L "$test_home/.codex/agents/harness-sol-research.toml" ]]
[[ "$(readlink "$test_home/.claude/agents/harness-orchestrator.md")" == "$repo_root/claude/agents/harness-orchestrator.md" ]]
grep -q "existing Claude instructions" "$test_home/.claude/CLAUDE.md"
grep -q "existing Codex instructions" "$test_home/.codex/AGENTS.md"
[[ "$(grep -c 'BEGIN CLAUDEX5' "$test_home/.claude/CLAUDE.md")" -eq 1 ]]
[[ "$(grep -c '\[agents.harness_sol_review\]' "$test_home/.codex/config.toml")" -eq 1 ]]

"$python_bin" - "$test_home" <<'PY'
import json
import sys
from pathlib import Path

home = Path(sys.argv[1])
settings = json.loads((home / ".claude/settings.json").read_text())
assert settings["model"] == "keep-model"
assert settings["hooks"]["Stop"][0]["command"] == "keep-hook"
assert settings["skipDangerousModePermissionPrompt"] is True
assert settings["enabledPlugins"]["codex@openai-codex"] is True

config = (home / ".codex/config.toml").read_text()
assert 'personality = "keep-personality"' in config
assert '[projects."/"]' in config
assert '[mcp_servers.keep]' in config
assert config.count("multi_agent = true") == 1
PY

run_install
[[ "$(grep -c 'BEGIN CLAUDEX5' "$test_home/.claude/CLAUDE.md")" -eq 1 ]]
[[ "$(grep -c '\[agents.harness_sol_review\]' "$test_home/.codex/config.toml")" -eq 1 ]]
[[ "$(find "$test_home/.local/state/claudex5-engineering-harness/backups" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" -ge 1 ]]

CLAUDEX5_PYTHON="$python_bin" "$repo_root/uninstall.sh" --home "$test_home"
[[ ! -e "$test_home/.claude/agents/harness-orchestrator.md" ]]
[[ ! -e "$test_home/.codex/agents/harness-sol-research.toml" ]]
! grep -q 'BEGIN CLAUDEX5' "$test_home/.claude/CLAUDE.md"
! grep -q '\[agents.harness_sol_review\]' "$test_home/.codex/config.toml"
grep -q "existing Claude instructions" "$test_home/.claude/CLAUDE.md"
grep -q 'personality = "keep-personality"' "$test_home/.codex/config.toml"

collision_home="$test_root/collision-home"
mkdir -p "$collision_home/.claude/agents" "$collision_home/.codex"
printf '%s\n' "user-owned" > "$collision_home/.claude/agents/harness-orchestrator.md"
if CLAUDEX5_PYTHON="$python_bin" CLAUDEX5_SKIP_PLUGIN=1 \
  "$repo_root/install.sh" --home "$collision_home" --skip-runtime-check >/dev/null 2>&1; then
  printf '%s\n' "installer unexpectedly overwrote a collision" >&2
  exit 1
fi
grep -q "user-owned" "$collision_home/.claude/agents/harness-orchestrator.md"

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

printf '%s\n' "integration tests: PASS"
