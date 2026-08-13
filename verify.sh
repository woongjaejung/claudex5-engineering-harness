#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/common.sh
source "$repo_root/scripts/common.sh"

target_home="${HOME:-}"
scan_repo="$repo_root"
strict=0
secrets_only=0
structural_only=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --home)
      [[ $# -ge 2 ]] || claudex5_die "--home requires a path"
      target_home="$2"
      shift 2
      ;;
    --repo)
      [[ $# -ge 2 ]] || claudex5_die "--repo requires a path"
      scan_repo="$2"
      shift 2
      ;;
    --strict) strict=1; shift ;;
    --secrets-only) secrets_only=1; shift ;;
    --structural-only) structural_only=1; shift ;;
    -h|--help)
      printf '%s\n' "Usage: ./verify.sh [--home PATH] [--repo PATH] [--strict] [--secrets-only] [--structural-only]"
      exit 0
      ;;
    *) claudex5_die "unknown argument: $1" ;;
  esac
done

target_home="$(claudex5_validate_home "$target_home")"
scan_repo="$(CDPATH= cd -- "$scan_repo" && pwd -P)"
failures=0
warnings=0

pass() { printf 'PASS: %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; failures=$((failures + 1)); }
warn() { printf 'WARNING: %s\n' "$*" >&2; warnings=$((warnings + 1)); }

scan_secret_candidates() {
  local list_file file relative basename content_file
  list_file="$(mktemp)"
  content_file="$(mktemp)"
  scan_one() {
    local source_file="$1"
    local display_path="$2"
    local normalized
    normalized="$(mktemp)"
    LC_ALL=C tr -d '\000' < "$source_file" > "$normalized"
    if LC_ALL=C grep -Eq 'sk-(proj-|ant-[A-Za-z0-9_-]*-)?[A-Za-z0-9_-]{20,}' "$normalized"; then
      fail "SECRET-KEY: likely OpenAI/Anthropic key content in $display_path"
    fi
    if LC_ALL=C grep -Eq '(ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16})' "$normalized"; then
      fail "SECRET-CLOUD: likely GitHub/AWS credential content in $display_path"
    fi
    if LC_ALL=C grep -Eq -- '-----BEGIN ([A-Z0-9 ]+ )?PRIVATE KEY-----' "$normalized"; then
      fail "SECRET-PRIVATE-KEY: private key material in $display_path"
    fi
    if LC_ALL=C grep -Eiq '(authorization:[[:space:]]*bearer|bearer)[[:space:]]+[A-Za-z0-9._~+/-]{24,}={0,2}' "$normalized"; then
      fail "SECRET-BEARER: likely Bearer token content in $display_path"
    fi
    rm -f "$normalized"
  }

  if git -C "$scan_repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$scan_repo" ls-files --cached -z > "$list_file"
  else
    find "$scan_repo" -type f -not -path '*/.git/*' -print0 > "$list_file"
  fi
  while IFS= read -r -d '' relative; do
    if [[ "$relative" == /* ]]; then
      file="$relative"
    else
      file="$scan_repo/$relative"
    fi
    basename="${relative##*/}"
    case "$basename" in
      auth.json|credentials.json|.claude.json|history.jsonl)
        fail "SECRET-FILENAME: repository candidate contains forbidden credential/session filename: $relative"
        continue
        ;;
    esac
    case "/$relative/" in
      */session-env/*|*/sessions/*|*/backups/*)
        fail "SECRET-PATH: repository candidate contains forbidden local-state path: $relative"
        continue
        ;;
    esac
    if git -C "$scan_repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      if git -C "$scan_repo" show ":$relative" > "$content_file" 2>/dev/null; then
        scan_one "$content_file" "Git index:$relative"
      fi
    elif [[ -f "$file" ]]; then
      scan_one "$file" "$relative"
    fi
  done < "$list_file"

  if git -C "$scan_repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$scan_repo" ls-files --modified --others --exclude-standard -z > "$list_file"
    while IFS= read -r -d '' relative; do
      file="$scan_repo/$relative"
      [[ -f "$file" ]] || continue
      scan_one "$file" "working tree:$relative"
    done < "$list_file"
  fi
  rm -f "$list_file" "$content_file"
}

scan_secret_candidates
if [[ "$failures" -eq 0 ]]; then
  pass "no forbidden credential files or likely secret values in Git push candidates"
fi

if [[ "$secrets_only" -eq 1 ]]; then
  [[ "$failures" -eq 0 ]] || exit 1
  exit 0
fi

python_bin="$(claudex5_find_python)" || { fail "Python 3.11 or newer is not available"; python_bin=""; }
if [[ -n "$python_bin" ]]; then
  if "$python_bin" - "$repo_root" "$target_home" <<'PY'
import json
import sys
from pathlib import Path

repository = Path(sys.argv[1])
home = Path(sys.argv[2])
sys.path.insert(0, str(repository))
from scripts.merge_config import parse_toml

json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
parse_toml((home / ".codex/config.toml").read_text(encoding="utf-8"))
PY
  then
    pass "Claude JSON and Codex TOML configuration parse successfully"
  else
    fail "Claude JSON or Codex TOML configuration is invalid"
  fi
fi

for instruction in "$target_home/.claude/CLAUDE.md" "$target_home/.codex/AGENTS.md"; do
  if [[ ! -f "$instruction" ]]; then
    fail "missing managed instruction file: $instruction"
  elif [[ "$(grep -c 'BEGIN CLAUDEX5 ENGINEERING HARNESS' "$instruction" || true)" -ne 1 || \
          "$(grep -c 'END CLAUDEX5 ENGINEERING HARNESS' "$instruction" || true)" -ne 1 ]]; then
    fail "managed instruction markers are missing or duplicated: $instruction"
  fi
done

expected_links=(
  "$target_home/.claude/statuslines/claudex5-subagent-models.py:$repo_root/claude/statuslines/claudex5-subagent-models.py"
  "$target_home/.claude/skills/claudex5-subagent-routing/SKILL.md:$repo_root/claude/skills/claudex5-subagent-routing/SKILL.md"
  "$target_home/.claude/agents/harness-orchestrator.md:$repo_root/claude/agents/harness-orchestrator.md"
  "$target_home/.claude/agents/harness-researcher.md:$repo_root/claude/agents/harness-researcher.md"
  "$target_home/.claude/agents/harness-implementer.md:$repo_root/claude/agents/harness-implementer.md"
  "$target_home/.claude/agents/harness-architecture-reviewer.md:$repo_root/claude/agents/harness-architecture-reviewer.md"
  "$target_home/.claude/agents/harness-judge.md:$repo_root/claude/agents/harness-judge.md"
  "$target_home/.codex/agents/harness-sol-research.toml:$repo_root/codex/agents/harness-sol-research.toml"
  "$target_home/.codex/agents/harness-sol-plan-review.toml:$repo_root/codex/agents/harness-sol-plan-review.toml"
  "$target_home/.codex/agents/harness-luna-implementation.toml:$repo_root/codex/agents/harness-luna-implementation.toml"
  "$target_home/.codex/agents/harness-sol-review.toml:$repo_root/codex/agents/harness-sol-review.toml"
  "$target_home/.codex/agents/harness-sol-adversarial-review.toml:$repo_root/codex/agents/harness-sol-adversarial-review.toml"
)
for mapping in "${expected_links[@]}"; do
  link_path="${mapping%%:*}"
  expected_target="${mapping#*:}"
  if [[ ! -L "$link_path" || "$(readlink "$link_path" 2>/dev/null || true)" != "$expected_target" ]]; then
    fail "missing or incorrect managed link: $link_path"
  fi
done

if [[ -n "$python_bin" && -f "$target_home/.claude/settings.json" ]]; then
  subagent_status_state="$($python_bin - "$target_home/.claude/settings.json" <<'PY'
import json
import sys
from pathlib import Path

settings = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = {
    "type": "command",
    "command": "~/.claude/statuslines/claudex5-subagent-models.py",
}
value = settings.get("subagentStatusLine")
if value == expected:
    print("active")
elif value is None:
    print("missing")
else:
    print("foreign")
PY
)"
  case "$subagent_status_state" in
    active) pass "Claudex5 subagent model labels are active" ;;
    missing)
      if [[ "$strict" -eq 1 ]]; then
        fail "Claudex5 subagent model labels are missing; rerun ./install.sh"
      else
        warn "Claudex5 subagent model labels are missing; rerun ./install.sh"
      fi
      ;;
    foreign)
      if [[ "$strict" -eq 1 ]]; then
        fail "foreign subagentStatusLine is preserved; Claudex5 model labels are not active"
      else
        warn "foreign subagentStatusLine is preserved; Claudex5 model labels are not active"
      fi
      ;;
  esac
fi

spark_link="$target_home/.codex/agents/harness-spark-ui-iteration.toml"
spark_target="$repo_root/codex/agents/harness-spark-ui-iteration.toml"
spark_link_installed=0
spark_table_installed=0
spark_installed=0
if [[ -L "$spark_link" && "$(readlink "$spark_link" 2>/dev/null || true)" == "$spark_target" ]]; then
  spark_link_installed=1
fi
if [[ -f "$target_home/.codex/config.toml" ]] && \
   grep -Eq '^\[agents\.harness_spark_ui_iteration\][[:space:]]*(#.*)?$' \
     "$target_home/.codex/config.toml"; then
  spark_table_installed=1
fi
if [[ "$spark_link_installed" -eq 1 && "$spark_table_installed" -eq 1 ]]; then
  spark_installed=1
  pass "conditional Codex-Spark role is installed consistently"
elif [[ "$spark_link_installed" -eq 0 && "$spark_table_installed" -eq 0 ]]; then
  pass "conditional Codex-Spark role is consistently disabled"
else
  fail "Codex-Spark role link and agent table are inconsistent; rerun ./install.sh"
fi

if [[ "$failures" -eq 0 ]]; then
  pass "managed blocks and role links are installed exactly once"
fi

if [[ "${CLAUDEX5_VERIFY_FAIL:-0}" == "1" ]]; then
  fail "injected structural verification failure"
fi

if [[ "$structural_only" -eq 1 ]]; then
  printf 'SUMMARY: failures=%d warnings=%d\n' "$failures" "$warnings"
  [[ "$failures" -eq 0 ]]
  exit
fi

if command -v claude >/dev/null 2>&1; then
  pass "Claude Code available: $(claude --version 2>/dev/null | head -n 1)"
  if HOME="$target_home" claude auth status >/dev/null 2>&1; then
    pass "Claude subscription authentication is available"
  elif [[ "$strict" -eq 1 ]]; then
    fail "Claude authentication unavailable; run: claude"
  else
    warn "Claude authentication unavailable; run: claude"
  fi
  plugin_list="$(HOME="$target_home" claude plugin list 2>/dev/null || true)"
  if claudex5_plugin_enabled "$plugin_list" "superpowers"; then
    pass "Superpowers is enabled; the Claudex5 adapter controls role routing"
  fi
  if claudex5_plugin_enabled "$plugin_list" "fable-advisor"; then
    conflict_message="fable-advisor is enabled and may replace Claudex5 routing; run: claude plugin disable fable-advisor@fable-advisor"
    if [[ "$strict" -eq 1 ]]; then
      fail "$conflict_message"
    else
      warn "$conflict_message"
    fi
  fi
  if claudex5_codex_plugin_enabled "$plugin_list"; then
    pass "official OpenAI Codex Claude Code plugin is installed"
    registry="$target_home/.claude/plugins/installed_plugins.json"
    helper_path=""
    if [[ -n "$python_bin" && -f "$registry" ]]; then
      helper_path="$($python_bin "$repo_root/scripts/plugin_registry.py" "$registry" "$target_home")"
    fi
    if [[ -n "$helper_path" && -x "$(command -v node 2>/dev/null || true)" ]]; then
      readiness_file="$(mktemp)"
      if HOME="$target_home" node "$helper_path" setup --json > "$readiness_file" 2>/dev/null && \
         "$python_bin" - "$readiness_file" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    raise SystemExit(0 if json.load(handle).get("ready") is True else 1)
PY
      then
        pass "official Codex plugin setup reports ready=true"
      elif [[ "$strict" -eq 1 ]]; then
        fail "official Codex plugin is installed but not ready; run /codex:setup in Claude Code"
      else
        warn "official Codex plugin is installed but not ready; run /codex:setup in Claude Code"
      fi
      rm -f "$readiness_file"
    elif [[ "$strict" -eq 1 ]]; then
      fail "could not resolve the official Codex plugin helper from Claude's registry"
    else
      warn "could not resolve the official Codex plugin helper; run /codex:setup in Claude Code"
    fi
  elif [[ "$strict" -eq 1 ]]; then
    fail "official Codex plugin is not installed"
  else
    warn "official Codex plugin is not installed"
  fi
elif [[ "$strict" -eq 1 ]]; then
  fail "Claude Code is not installed"
else
  warn "Claude Code is not installed"
fi

if command -v codex >/dev/null 2>&1; then
  pass "Codex available: $(codex --version 2>/dev/null | head -n 1)"
  if HOME="$target_home" codex login status >/dev/null 2>&1; then
    pass "ChatGPT subscription authentication is available"
  elif [[ "$strict" -eq 1 ]]; then
    fail "Codex authentication unavailable; run: codex login --device-auth"
  else
    warn "Codex authentication unavailable; run: codex login --device-auth"
  fi
  if [[ -n "$python_bin" ]]; then
    set +e
    spark_state="$(HOME="$target_home" "$python_bin" "$repo_root/scripts/spark_probe.py" \
      --codex-bin "$(command -v codex)" 2>/dev/null)"
    spark_probe_status=$?
    set -e
    if [[ "$spark_probe_status" -eq 0 && "$spark_state" == "available" ]]; then
      if [[ "$spark_installed" -eq 1 ]]; then
        pass "Codex-Spark access is available and its role is enabled"
      else
        warn "Codex-Spark is now available but its role is disabled; rerun ./install.sh"
      fi
    elif [[ "$spark_probe_status" -eq 1 && "$spark_state" == "unavailable" ]]; then
      if [[ "$spark_installed" -eq 1 ]]; then
        warn "Codex-Spark is no longer available but its role is enabled; rerun ./install.sh"
      else
        pass "Codex-Spark is unavailable and the Sonnet fallback is active"
      fi
    else
      warn "Codex-Spark availability could not be confirmed; installed state was left unchanged"
    fi
  fi
elif [[ "$strict" -eq 1 ]]; then
  fail "Codex CLI is not installed"
else
  warn "Codex CLI is not installed"
fi

if [[ -f "$target_home/.claude/settings.json" ]] && \
   grep -Eq '"skipDangerousModePermissionPrompt"[[:space:]]*:[[:space:]]*true' "$target_home/.claude/settings.json"; then
  warn "Claude dangerous-mode warning bypass is preserved; use ./install.sh --harden to disable it"
fi
if [[ -f "$target_home/.codex/config.toml" ]] && \
   grep -Eq '^\[projects\."/"\][[:space:]]*$' "$target_home/.codex/config.toml"; then
  warn "Codex root project trust is preserved; use ./install.sh --harden to remove it"
fi

env_names="$(env | cut -d= -f1 | grep -E '^(ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|OPENAI_API_KEY|CODEX_ACCESS_TOKEN)$' || true)"
if [[ -n "$env_names" ]]; then
  warn "API credential environment variable names are active: $(tr '\n' ' ' <<< "$env_names")"
else
  pass "no Claude/Codex API-key environment variables are active"
fi

printf 'SUMMARY: failures=%d warnings=%d\n' "$failures" "$warnings"
[[ "$failures" -eq 0 ]]
