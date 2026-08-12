#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
output="$(CLAUDEX5_OS_RELEASE="$repo_root/tests/fixtures/ubuntu-os-release" \
  "$repo_root/bootstrap-vps.sh" --dry-run)"

for required in "Python 3" "Node.js 22" "Claude Code" "OpenAI Codex" "machine-local login"; do
  case "$output" in
    *"$required"*) ;;
    *) printf 'missing bootstrap dry-run text: %s\n' "$required" >&2; exit 1 ;;
  esac
done

printf '%s\n' "bootstrap tests: PASS"
