#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/common.sh
source "$repo_root/scripts/common.sh"

target_home="${HOME:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --home)
      [[ $# -ge 2 ]] || claudex5_die "--home requires a path"
      target_home="$2"
      shift 2
      ;;
    -h|--help)
      printf '%s\n' "Usage: ./uninstall.sh [--home PATH]"
      exit 0
      ;;
    *) claudex5_die "unknown argument: $1" ;;
  esac
done
target_home="$(claudex5_validate_home "$target_home")"
[[ ! -L "$target_home/.claude" ]] || claudex5_die "refusing symlinked configuration directory: $target_home/.claude"
[[ ! -L "$target_home/.codex" ]] || claudex5_die "refusing symlinked configuration directory: $target_home/.codex"
for managed_path in \
  "$target_home/.local/bin" \
  "$target_home/.local/state/claudex5-engineering-harness" \
  "$target_home/.claude/agents" \
  "$target_home/.claude/hooks" \
  "$target_home/.claude/skills/claudex5-subagent-routing" \
  "$target_home/.claude/statuslines" \
  "$target_home/.codex/agents"; do
  claudex5_assert_no_symlink_components "$target_home" "$managed_path"
done
python_bin="$(claudex5_find_python)" || claudex5_die "Python 3.11 or newer is required"

backup_dir="$(claudex5_backup_configs "$target_home")"
removed_links_file="$(mktemp)"
expected_state_file="$(mktemp)"
committed=0
config_removed=0
cleanup() {
  local status=$?
  if [[ "$committed" -ne 1 ]]; then
    claudex5_warn "uninstall failed; restoring managed configuration and links"
    if [[ "$config_removed" -eq 1 ]]; then
      claudex5_restore_backup "$target_home" "$backup_dir" "$expected_state_file"
    fi
    while IFS= read -r -d '' link_path && IFS= read -r -d '' link_target; do
      if ! (claudex5_assert_no_symlink_components "$target_home" "$(dirname "$link_path")"); then
        claudex5_warn "managed link path changed during rollback; skipped: $link_path"
        continue
      fi
      if [[ ! -e "$link_path" && ! -L "$link_path" ]]; then
        mkdir -p "$(dirname "$link_path")"
        ln -s "$link_target" "$link_path"
      fi
    done < "$removed_links_file"
  fi
  rm -f "$removed_links_file" "$expected_state_file"
  exit "$status"
}
trap cleanup EXIT INT TERM

# Remove settings and instruction ownership before links. The state capture
# lets rollback restore only files that no other process changed afterwards.
"$python_bin" "$repo_root/scripts/merge_config.py" uninstall --home "$target_home" --repo "$repo_root" \
  --state-file "$expected_state_file"
config_removed=1
removed_count=0
link_sources=(
  "$repo_root/claude/agents/harness-orchestrator.md"
  "$repo_root/claude/agents/harness-orchestrator-opus.md"
  "$repo_root/claude/agents/harness-researcher.md"
  "$repo_root/claude/agents/harness-implementer.md"
  "$repo_root/claude/agents/harness-implementer-opus.md"
  "$repo_root/claude/agents/harness-architecture-reviewer.md"
  "$repo_root/claude/agents/harness-code-reviewer.md"
  "$repo_root/claude/agents/harness-judge.md"
  "$repo_root/claude/agents/harness-judge-opus.md"
  "$repo_root/claude/skills/claudex5-subagent-routing/SKILL.md"
  "$repo_root/claude/statuslines/claudex5-subagent-models.py"
  "$repo_root/claude/hooks/claudex5-live-graph.py"
  "$repo_root/bin/claudex5"
  "$repo_root/codex/agents/harness-sol-research.toml"
  "$repo_root/codex/agents/harness-sol-plan-review.toml"
  "$repo_root/codex/agents/harness-luna-implementation.toml"
  "$repo_root/codex/agents/harness-sol-review.toml"
  "$repo_root/codex/agents/harness-sol-adversarial-review.toml"
  "$repo_root/codex/agents/harness-spark-ui-iteration.toml"
)
link_destinations=(
  "$target_home/.claude/agents/harness-orchestrator.md"
  "$target_home/.claude/agents/harness-orchestrator-opus.md"
  "$target_home/.claude/agents/harness-researcher.md"
  "$target_home/.claude/agents/harness-implementer.md"
  "$target_home/.claude/agents/harness-implementer-opus.md"
  "$target_home/.claude/agents/harness-architecture-reviewer.md"
  "$target_home/.claude/agents/harness-code-reviewer.md"
  "$target_home/.claude/agents/harness-judge.md"
  "$target_home/.claude/agents/harness-judge-opus.md"
  "$target_home/.claude/skills/claudex5-subagent-routing/SKILL.md"
  "$target_home/.claude/statuslines/claudex5-subagent-models.py"
  "$target_home/.claude/hooks/claudex5-live-graph.py"
  "$target_home/.local/bin/claudex5"
  "$target_home/.codex/agents/harness-sol-research.toml"
  "$target_home/.codex/agents/harness-sol-plan-review.toml"
  "$target_home/.codex/agents/harness-luna-implementation.toml"
  "$target_home/.codex/agents/harness-sol-review.toml"
  "$target_home/.codex/agents/harness-sol-adversarial-review.toml"
  "$target_home/.codex/agents/harness-spark-ui-iteration.toml"
)
for index in "${!link_sources[@]}"; do
  path="${link_destinations[$index]}"
  target="${link_sources[$index]}"
  claudex5_assert_no_symlink_components "$target_home" "$(dirname "$path")"
  [[ -L "$path" ]] || continue
  [[ "$(readlink "$path")" == "$target" ]] || continue
  if [[ "${CLAUDEX5_UNINSTALL_JOURNAL_FAIL:-0}" == "1" ]]; then
    claudex5_die "injected uninstall journal failure"
  fi
  printf '%s\0%s\0' "$path" "$target" >> "$removed_links_file"
  rm -f "$path"
  removed_count=$((removed_count + 1))
  if [[ "${CLAUDEX5_UNINSTALL_FAIL_AFTER_REMOVAL:-}" == "$removed_count" ]]; then
    claudex5_die "injected uninstall link-removal failure"
  fi
done
committed=1
trap - EXIT INT TERM
rm -f "$removed_links_file" "$expected_state_file"
claudex5_info "harness-managed files and instruction blocks removed"
claudex5_info "backup: $backup_dir"
