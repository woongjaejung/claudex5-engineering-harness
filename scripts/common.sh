#!/usr/bin/env bash

claudex5_die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

claudex5_info() {
  printf 'INFO: %s\n' "$*"
}

claudex5_warn() {
  printf 'WARNING: %s\n' "$*" >&2
}

claudex5_validate_home() {
  local candidate="$1"
  [[ -n "$candidate" ]] || claudex5_die "target home is empty"
  mkdir -p "$candidate"
  local canonical
  canonical="$(CDPATH= cd -- "$candidate" && pwd -P)"
  [[ "$canonical" != "/" ]] || claudex5_die "target home must not resolve to /"
  printf '%s\n' "$canonical"
}

claudex5_find_python() {
  local candidate
  for candidate in \
    "${CLAUDEX5_PYTHON:-}" \
    "$(command -v python3 2>/dev/null || true)" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "${HOME:-}/miniforge3/bin/python3"; do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

claudex5_node_version_ok() {
  command -v node >/dev/null 2>&1 || return 1
  node -p '
    const [major, minor] = process.versions.node.split(".").map(Number);
    process.exit(major > 18 || (major === 18 && minor >= 18) ? 0 : 1)
  ' >/dev/null 2>&1
}

claudex5_codex_plugin_enabled() {
  local plugin_list="$1"
  printf '%s\n' "$plugin_list" | awk '
    /codex@openai-codex/ { in_plugin = 1; next }
    in_plugin && /Status:/ { enabled = ($0 ~ /enabled/); exit }
    in_plugin && /❯/ { exit }
    END { exit !(in_plugin && enabled) }
  '
}

claudex5_backup_configs() {
  local target_home="$1"
  local state_base="${XDG_STATE_HOME:-$target_home/.local/state}/claudex5-engineering-harness/backups"
  local backup_dir="$state_base/$(date -u +%Y%m%dT%H%M%SZ)-$$"
  local relative source
  umask 077
  [[ ! -L "$state_base" ]] || claudex5_die "backup state directory must not be a symbolic link: $state_base"
  mkdir -p "$backup_dir"
  chmod 700 "$state_base" "$backup_dir" || claudex5_die "cannot secure backup directory permissions"
  : > "$backup_dir/manifest.tsv"
  chmod 600 "$backup_dir/manifest.tsv"
  for relative in .claude/settings.json .claude/CLAUDE.md .codex/config.toml .codex/AGENTS.md; do
    source="$target_home/$relative"
    if [[ -f "$source" ]]; then
      mkdir -p "$backup_dir/$(dirname "$relative")"
      cp -p "$source" "$backup_dir/$relative"
      chmod 600 "$backup_dir/$relative" || claudex5_die "cannot secure backup file permissions"
      printf 'present\t%s\n' "$relative" >> "$backup_dir/manifest.tsv"
    else
      printf 'absent\t%s\n' "$relative" >> "$backup_dir/manifest.tsv"
    fi
  done
  printf '%s\n' "$backup_dir"
}

claudex5_restore_backup() {
  local target_home="$1"
  local backup_dir="$2"
  local expected_state="${3:-}"
  local state relative
  [[ -f "$backup_dir/manifest.tsv" ]] || return 0
  while IFS=$'\t' read -r state relative; do
    [[ -n "$relative" ]] || continue
    if [[ -n "$expected_state" && -s "$expected_state" ]]; then
      expected="$(awk -F '\t' -v wanted="$relative" '$1 == wanted {print $2 "\t" $3}' "$expected_state")"
      current="$(claudex5_file_state "$target_home/$relative")"
      if [[ "$current" != "$expected" ]]; then
        claudex5_warn "configuration changed during installation; automatic rollback skipped: $target_home/$relative"
        continue
      fi
    fi
    if [[ "$state" == "present" ]]; then
      mkdir -p "$target_home/$(dirname "$relative")"
      cp -p "$backup_dir/$relative" "$target_home/$relative"
    else
      rm -f "$target_home/$relative"
    fi
  done < "$backup_dir/manifest.tsv"
}

claudex5_file_state() {
  local path="$1"
  if [[ -f "$path" ]]; then
    local digest
    digest="$(shasum -a 256 "$path" | awk '{print $1}')"
    printf 'present\t%s' "$digest"
  else
    printf 'absent\t-'
  fi
}

claudex5_capture_config_state() {
  local target_home="$1"
  local output="$2"
  local relative state
  : > "$output"
  chmod 600 "$output"
  for relative in .claude/settings.json .claude/CLAUDE.md .codex/config.toml .codex/AGENTS.md; do
    state="$(claudex5_file_state "$target_home/$relative")"
    printf '%s\t%s\n' "$relative" "$state" >> "$output"
  done
}
