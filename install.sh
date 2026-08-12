#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/common.sh
source "$repo_root/scripts/common.sh"

target_home="${HOME:-}"
harden=0
bootstrap=0
skip_runtime=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --home)
      [[ $# -ge 2 ]] || claudex5_die "--home requires a path"
      target_home="$2"
      shift 2
      ;;
    --harden) harden=1; shift ;;
    --bootstrap) bootstrap=1; shift ;;
    --skip-runtime-check) skip_runtime=1; shift ;;
    -h|--help)
      printf '%s\n' "Usage: ./install.sh [--bootstrap] [--harden] [--home PATH]"
      exit 0
      ;;
    *) claudex5_die "unknown argument: $1" ;;
  esac
done
target_home="$(claudex5_validate_home "$target_home")"
[[ ! -L "$target_home/.claude" ]] || claudex5_die "refusing symlinked configuration directory: $target_home/.claude"
[[ ! -L "$target_home/.codex" ]] || claudex5_die "refusing symlinked configuration directory: $target_home/.codex"

if [[ "$bootstrap" -eq 1 ]]; then
  "$repo_root/bootstrap-vps.sh"
  export PATH="$target_home/.local/bin:$PATH"
fi

python_bin="$(claudex5_find_python)" || claudex5_die "Python 3.11 or newer is required"
if [[ "$skip_runtime" -eq 0 ]]; then
  claudex5_node_version_ok || claudex5_die "Node.js 18.18 or newer is required; use --bootstrap on a new VPS"
  command -v claude >/dev/null 2>&1 || claudex5_die "Claude Code is required; use --bootstrap on a new VPS"
  command -v codex >/dev/null 2>&1 || claudex5_die "Codex CLI is required; use --bootstrap on a new VPS"
fi

backup_dir="$(claudex5_backup_configs "$target_home")"
created_links_file="$(mktemp)"
expected_state_file="$(mktemp)"
committed=0
cleanup() {
  local status=$?
  if [[ "$committed" -ne 1 ]]; then
    claudex5_warn "installation failed; restoring configuration backup"
    claudex5_restore_backup "$target_home" "$backup_dir" "$expected_state_file"
    if [[ -f "$created_links_file" ]]; then
      while IFS= read -r link_path; do
        [[ -L "$link_path" ]] && rm -f "$link_path"
      done < "$created_links_file"
    fi
  fi
  rm -f "$created_links_file"
  rm -f "$expected_state_file"
  exit "$status"
}
trap cleanup EXIT INT TERM

"$repo_root/link.sh" --home "$target_home" --journal "$created_links_file" >/dev/null

merge_args=(install --home "$target_home" --repo "$repo_root")
[[ "$harden" -eq 1 ]] && merge_args+=(--harden)
"$python_bin" "$repo_root/scripts/merge_config.py" "${merge_args[@]}"
claudex5_capture_config_state "$target_home" "$expected_state_file"

if [[ "${CLAUDEX5_SKIP_PLUGIN:-0}" != "1" && "$skip_runtime" -eq 0 ]]; then
  plugin_list="$(HOME="$target_home" claude plugin list 2>/dev/null || true)"
  if ! grep -q 'codex@openai-codex' <<< "$plugin_list"; then
    HOME="$target_home" claude plugin marketplace add openai/codex-plugin-cc
    HOME="$target_home" claude plugin install codex@openai-codex
    plugin_list="$(HOME="$target_home" claude plugin list 2>/dev/null || true)"
  fi
  if ! claudex5_codex_plugin_enabled "$plugin_list"; then
    HOME="$target_home" claude plugin enable codex@openai-codex >/dev/null
  fi
fi
claudex5_capture_config_state "$target_home" "$expected_state_file"

if [[ -x "$repo_root/verify.sh" ]]; then
  "$repo_root/verify.sh" --home "$target_home" --repo "$repo_root" --structural-only
fi
committed=1
trap - EXIT INT TERM
rm -f "$created_links_file"
rm -f "$expected_state_file"
claudex5_info "installation complete"
claudex5_info "backup: $backup_dir"
"$repo_root/verify.sh" --home "$target_home" --repo "$repo_root"
