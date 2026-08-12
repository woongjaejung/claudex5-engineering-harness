#!/usr/bin/env bash
set -euo pipefail

ran=0

if [[ -f package.json ]]; then
  for script_name in lint typecheck test build; do
    if node -e 'const p=require("./package.json"); process.exit(p.scripts?.[process.argv[1]] ? 0 : 1)' "$script_name"; then
      npm run "$script_name"
      ran=1
    fi
  done
fi

if [[ -f pyproject.toml || -d tests ]]; then
  if command -v pytest >/dev/null 2>&1; then
    pytest
  else
    python3 -m unittest discover -s tests -v
  fi
  ran=1
fi

if [[ -f go.mod ]]; then
  go test ./...
  ran=1
fi

if [[ -f Cargo.toml ]]; then
  cargo test
  ran=1
fi

if [[ "$ran" -eq 0 ]]; then
  printf '%s\n' "No supported project manifest was detected; run this repository's documented checks manually." >&2
  exit 2
fi
