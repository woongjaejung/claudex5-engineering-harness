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
for path in \
  "$target_home/.claude/agents"/harness-*.md \
  "$target_home/.claude/skills/claudex5-subagent-routing/SKILL.md" \
  "$target_home/.claude/statuslines/claudex5-subagent-models.py" \
  "$target_home/.codex/agents"/harness-*.toml; do
  [[ -L "$path" ]] || continue
  target="$(readlink "$path")"
  case "$target" in
    "$repo_root"/claude/agents/*|"$repo_root"/claude/skills/*|"$repo_root"/claude/statuslines/*|"$repo_root"/codex/agents/*) rm -f "$path" ;;
    *) claudex5_warn "foreign harness-named link preserved: $path" ;;
  esac
done
"$python_bin" "$repo_root/scripts/merge_config.py" uninstall --home "$target_home" --repo "$repo_root"
claudex5_info "harness-managed files and instruction blocks removed"
claudex5_info "backup: $backup_dir"
