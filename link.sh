#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=scripts/common.sh
source "$repo_root/scripts/common.sh"

target_home="${HOME:-}"
journal=""
enable_spark=0
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
    --enable-spark) enable_spark=1; shift ;;
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
  "$repo_root/claude/skills/claudex5-subagent-routing/SKILL.md"
  "$repo_root/claude/statuslines/claudex5-subagent-models.py"
  "$repo_root/claude/hooks/claudex5-live-graph.py"
  "$repo_root/bin/claudex5"
  "$repo_root/codex/agents/harness-sol-research.toml"
  "$repo_root/codex/agents/harness-sol-plan-review.toml"
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
  "$target_home/.claude/skills/claudex5-subagent-routing/SKILL.md"
  "$target_home/.claude/statuslines/claudex5-subagent-models.py"
  "$target_home/.claude/hooks/claudex5-live-graph.py"
  "$target_home/.local/bin/claudex5"
  "$target_home/.codex/agents/harness-sol-research.toml"
  "$target_home/.codex/agents/harness-sol-plan-review.toml"
  "$target_home/.codex/agents/harness-luna-implementation.toml"
  "$target_home/.codex/agents/harness-sol-review.toml"
  "$target_home/.codex/agents/harness-sol-adversarial-review.toml"
)

spark_source="$repo_root/codex/agents/harness-spark-ui-iteration.toml"
spark_destination="$target_home/.codex/agents/harness-spark-ui-iteration.toml"
remove_managed_spark=0
if [[ "$enable_spark" -eq 1 ]]; then
  sources+=("$spark_source")
  destinations+=("$spark_destination")
elif [[ -L "$spark_destination" && "$(readlink "$spark_destination")" == "$spark_source" ]]; then
  remove_managed_spark=1
fi

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

if [[ "$remove_managed_spark" -eq 1 ]]; then
  rm -f "$spark_destination"
  [[ -n "$journal" ]] && printf 'removed\t%s\t%s\n' "$spark_destination" "$spark_source" >> "$journal"
  printf 'REMOVED\t%s\n' "$spark_destination"
fi

mkdir -p \
  "$target_home/.local/bin" \
  "$target_home/.claude/agents" \
  "$target_home/.claude/hooks" \
  "$target_home/.claude/skills/claudex5-subagent-routing" \
  "$target_home/.claude/statuslines" \
  "$target_home/.codex/agents"
for index in "${!sources[@]}"; do
  source_path="${sources[$index]}"
  destination="${destinations[$index]}"
  if [[ ! -L "$destination" ]]; then
    ln -s "$source_path" "$destination"
    [[ -n "$journal" ]] && printf 'created\t%s\t%s\n' "$destination" "$source_path" >> "$journal"
    printf 'CREATED\t%s\n' "$destination"
  fi
done
