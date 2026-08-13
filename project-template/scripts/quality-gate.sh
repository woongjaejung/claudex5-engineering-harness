#!/usr/bin/env bash
set -euo pipefail

ran=0
group_id="quality:all-$$"
parent_id="$group_id"
previous_node=""
gate_index=0
harness_available=0
session_args=()
if [[ -n "${CLAUDEX5_SESSION_ID:-}" ]]; then
  session_args=(--session-id "$CLAUDEX5_SESSION_ID")
fi
if command -v claudex5 >/dev/null 2>&1; then
  harness_available=1
  claudex5 event "${session_args[@]}" --type node.started --node-id "$parent_id" \
    --kind quality_gate --label "Deterministic quality gates"
else
  printf '%s\n' "WARNING: claudex5 is unavailable; quality commands will run without graph events." >&2
fi

finish_parent() {
  local status=$?
  if [[ "$harness_available" -eq 1 ]]; then
    local state="passed"
    if [[ "$status" -eq 130 || "$status" -eq 143 ]]; then
      state="interrupted"
    elif [[ "$status" -ne 0 ]]; then
      state="failed"
    fi
    claudex5 event "${session_args[@]}" --type node.finished --node-id "$parent_id" \
      --kind quality_gate --label "Deterministic quality gates" --state "$state" || true
  fi
  return "$status"
}
trap finish_parent EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

run_gate() {
  local name="$1"
  shift
  gate_index=$((gate_index + 1))
  local node_id="gate:${group_id#quality:}:$gate_index"
  if [[ "$harness_available" -eq 1 ]]; then
    local args=(gate-run "${session_args[@]}" --group-id "$group_id" --node-id "$node_id" --name "$name")
    if [[ -n "$previous_node" ]]; then
      args+=(--dependency "$previous_node")
    fi
    claudex5 "${args[@]}" -- "$@"
    previous_node="$node_id"
  else
    "$@"
  fi
}

if [[ -f package.json ]]; then
  for script_name in lint typecheck test build; do
    if node -e 'const p=require("./package.json"); process.exit(p.scripts?.[process.argv[1]] ? 0 : 1)' "$script_name"; then
      run_gate "$script_name" npm run "$script_name"
      ran=1
    fi
  done
fi

if [[ -f pyproject.toml || -d tests ]]; then
  if command -v pytest >/dev/null 2>&1; then
    run_gate pytest pytest
  else
    run_gate unittest python3 -m unittest discover -s tests -v
  fi
  ran=1
fi

if [[ -f go.mod ]]; then
  run_gate go-test go test ./...
  ran=1
fi

if [[ -f Cargo.toml ]]; then
  run_gate cargo-test cargo test
  ran=1
fi

if [[ "$ran" -eq 0 ]]; then
  printf '%s\n' "No supported project manifest was detected; run this repository's documented checks manually." >&2
  exit 2
fi
