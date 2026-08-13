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
    while IFS=$'\t' read -r link_path link_target; do
      [[ -n "$link_path" ]] || continue
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
"$python_bin" "$repo_root/scripts/merge_config.py" uninstall --home "$target_home" --repo "$repo_root"
claudex5_capture_config_state "$target_home" "$expected_state_file"
config_removed=1
removed_count=0
for path in \
  "$target_home/.local/bin/claudex5" \
  "$target_home/.claude/agents"/harness-*.md \
  "$target_home/.claude/hooks/claudex5-live-graph.py" \
  "$target_home/.claude/skills/claudex5-subagent-routing/SKILL.md" \
  "$target_home/.claude/statuslines/claudex5-subagent-models.py" \
  "$target_home/.codex/agents"/harness-*.toml; do
  [[ -L "$path" ]] || continue
  target="$(readlink "$path")"
  case "$target" in
    "$repo_root"/bin/*|"$repo_root"/claude/agents/*|"$repo_root"/claude/hooks/*|"$repo_root"/claude/skills/*|"$repo_root"/claude/statuslines/*|"$repo_root"/codex/agents/*)
      rm -f "$path"
      printf '%s\t%s\n' "$path" "$target" >> "$removed_links_file"
      removed_count=$((removed_count + 1))
      if [[ "${CLAUDEX5_UNINSTALL_FAIL_AFTER_REMOVAL:-}" == "$removed_count" ]]; then
        claudex5_die "injected uninstall link-removal failure"
      fi
      ;;
    *) claudex5_warn "foreign harness-named link preserved: $path" ;;
  esac
done
committed=1
trap - EXIT INT TERM
rm -f "$removed_links_file" "$expected_state_file"
claudex5_info "harness-managed files and instruction blocks removed"
claudex5_info "backup: $backup_dir"
