#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/common.sh
source "$repo_root/scripts/common.sh"

target_home="${HOME:-}"
journal=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --home)
      [[ $# -ge 2 ]] || claudex5_die "--home requires a path"
      target_home="$2"
      shift 2
      ;;
    --journal)
      [[ $# -ge 2 ]] || claudex5_die "--journal requires a path"
      journal="$2"
      shift 2
      ;;
    *) claudex5_die "unknown argument: $1" ;;
  esac
done
target_home="$(claudex5_validate_home "$target_home")"

sources=(
  "$repo_root/claude/agents/harness-orchestrator.md"
  "$repo_root/claude/agents/harness-orchestrator-opus.md"
  "$repo_root/claude/agents/harness-researcher.md"
  "$repo_root/claude/agents/harness-implementer.md"
  "$repo_root/claude/agents/harness-implementer-opus.md"
  "$repo_root/claude/agents/harness-architecture-reviewer.md"
  "$repo_root/claude/agents/harness-judge.md"
  "$repo_root/claude/agents/harness-judge-opus.md"
  "$repo_root/codex/agents/harness-sol-research.toml"
  "$repo_root/codex/agents/harness-luna-implementation.toml"
  "$repo_root/codex/agents/harness-sol-review.toml"
  "$repo_root/codex/agents/harness-sol-adversarial-review.toml"
)
destinations=(
  "$target_home/.claude/agents/harness-orchestrator.md"
  "$target_home/.claude/agents/harness-orchestrator-opus.md"
  "$target_home/.claude/agents/harness-researcher.md"
  "$target_home/.claude/agents/harness-implementer.md"
  "$target_home/.claude/agents/harness-implementer-opus.md"
  "$target_home/.claude/agents/harness-architecture-reviewer.md"
  "$target_home/.claude/agents/harness-judge.md"
  "$target_home/.claude/agents/harness-judge-opus.md"
  "$target_home/.codex/agents/harness-sol-research.toml"
  "$target_home/.codex/agents/harness-luna-implementation.toml"
  "$target_home/.codex/agents/harness-sol-review.toml"
  "$target_home/.codex/agents/harness-sol-adversarial-review.toml"
)

for index in "${!sources[@]}"; do
  source_path="${sources[$index]}"
  destination="${destinations[$index]}"
  [[ -f "$source_path" ]] || claudex5_die "missing repository file: $source_path"
  if [[ -L "$destination" ]]; then
    [[ "$(readlink "$destination")" == "$source_path" ]] || \
      claudex5_die "foreign symlink collision: $destination"
  elif [[ -e "$destination" ]]; then
    claudex5_die "file collision: $destination"
  fi
done

mkdir -p "$target_home/.claude/agents" "$target_home/.codex/agents"
for index in "${!sources[@]}"; do
  source_path="${sources[$index]}"
  destination="${destinations[$index]}"
  if [[ ! -L "$destination" ]]; then
    ln -s "$source_path" "$destination"
    [[ -n "$journal" ]] && printf '%s\n' "$destination" >> "$journal"
    printf 'CREATED\t%s\n' "$destination"
  fi
done
