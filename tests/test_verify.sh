#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
fixture_repo="$test_root/repository"
mkdir -p "$fixture_repo"
git -C "$fixture_repo" init -q
git -C "$fixture_repo" config user.name "Verification Test"
git -C "$fixture_repo" config user.email "verification@example.invalid"
printf '%s\n' "safe content" > "$fixture_repo/README.md"
git -C "$fixture_repo" add README.md

"$repo_root/verify.sh" --repo "$fixture_repo" --secrets-only

printf '%s\n' '{}' > "$fixture_repo/auth.json"
git -C "$fixture_repo" add -f auth.json
if "$repo_root/verify.sh" --repo "$fixture_repo" --secrets-only >/dev/null 2>&1; then
  printf '%s\n' "tracked auth.json must fail verification" >&2
  exit 1
fi
git -C "$fixture_repo" rm -q --cached auth.json
rm "$fixture_repo/auth.json"

fake_key="sk-proj-$(printf 'a%.0s' {1..40})"
printf '%s\n' "$fake_key" > "$fixture_repo/example.txt"
git -C "$fixture_repo" add example.txt
if "$repo_root/verify.sh" --repo "$fixture_repo" --secrets-only >/dev/null 2>&1; then
  printf '%s\n' "likely OpenAI key content must fail verification" >&2
  exit 1
fi
git -C "$fixture_repo" rm -q --cached example.txt
rm "$fixture_repo/example.txt"

staged_key="sk-proj-$(printf 'b%.0s' {1..40})"
printf '%s\n' "$staged_key" > "$fixture_repo/staged.txt"
git -C "$fixture_repo" add staged.txt
printf '%s\n' "safe worktree content" > "$fixture_repo/staged.txt"
if "$repo_root/verify.sh" --repo "$fixture_repo" --secrets-only >/dev/null 2>&1; then
  printf '%s\n' "secret present only in the Git index must fail verification" >&2
  exit 1
fi
git -C "$fixture_repo" rm -q -f --cached staged.txt
rm "$fixture_repo/staged.txt"

bearer_value="$(printf 'c%.0s' {1..48})"
printf 'Authorization: Bearer %s\n' "$bearer_value" > "$fixture_repo/bearer.txt"
git -C "$fixture_repo" add bearer.txt
if "$repo_root/verify.sh" --repo "$fixture_repo" --secrets-only >/dev/null 2>&1; then
  printf '%s\n' "Bearer token must fail verification" >&2
  exit 1
fi
git -C "$fixture_repo" rm -q --cached bearer.txt
rm "$fixture_repo/bearer.txt"

printf '%s\n' "OPENAI_API_KEY=<set-on-your-machine>" > "$fixture_repo/.env.example"
git -C "$fixture_repo" add -f .env.example
"$repo_root/verify.sh" --repo "$fixture_repo" --secrets-only

printf '%s\n' "verification security tests: PASS"
