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

python_bin="${CLAUDEX5_TEST_PYTHON:-$(command -v python3)}"
PYTHONPATH="$repo_root" "$python_bin" - "$test_root" <<'PY'
import json
import os
from pathlib import Path
import stat
import sys

from scripts.live_graph.store import StateStore
from scripts.live_graph.sessions import SessionSelection
from scripts.live_graph.web import create_server

root = Path(sys.argv[1]) / "private-state" / "runs"
store = StateStore(root)
store.append(
    "security-session",
    "session.started",
    "session:security-session",
    {"cwd": str(Path(sys.argv[1]) / "project")},
)
store.append(
    "security-session",
    "node.started",
    "task:security",
    {"kind": "task", "label": "Bearer " + "z" * 40},
)
assert stat.S_IMODE(root.stat().st_mode) == 0o700
for path in root.rglob("*"):
    if path.is_dir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    elif path.name != ".lock":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
persisted = b"\n".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
assert b"z" * 40 not in persisted
assert b"[REDACTED]" in persisted
try:
    create_server(store, SessionSelection.all(), host="0.0.0.0", port=0)
except ValueError:
    pass
else:
    raise AssertionError("public dashboard bind must be rejected")
PY

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

version_home="$test_root/versioned-hooks-home"
fake_bin="$test_root/fake-bin"
mkdir -p "$version_home/.claude" "$version_home/.codex" "$fake_bin"
printf '%s\n' '{}' > "$version_home/.claude/settings.json"
printf '%s\n' '' > "$version_home/.codex/config.toml"
"$repo_root/link.sh" --home "$version_home" >/dev/null
"$python_bin" "$repo_root/scripts/merge_config.py" install --home "$version_home" --repo "$repo_root" \
  --enable-task-completed --enable-task-created
cat > "$fake_bin/claude" <<'EOF'
#!/usr/bin/env bash
[[ "${1:-}" == "--version" ]] && printf '%s\n' "${FAKE_CLAUDE_VERSION:-2.1.84}" || exit 1
EOF
chmod +x "$fake_bin/claude"
PATH="$fake_bin:$PATH" "$repo_root/verify.sh" --home "$version_home" --repo "$repo_root" --structural-only >/dev/null
"$python_bin" - "$version_home/.claude/settings.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
settings = json.loads(path.read_text())
settings["hooks"].pop("TaskCreated")
path.write_text(json.dumps(settings))
PY
if PATH="$fake_bin:$PATH" "$repo_root/verify.sh" --home "$version_home" --repo "$repo_root" --structural-only >/dev/null 2>&1; then
  printf '%s\n' "supported Claude version must fail when TaskCreated hook is missing" >&2
  exit 1
fi
"$python_bin" "$repo_root/scripts/merge_config.py" install --home "$version_home" --repo "$repo_root" \
  --enable-task-completed --enable-task-created
if PATH="$fake_bin:$PATH" FAKE_CLAUDE_VERSION=2.1.32 \
  "$repo_root/verify.sh" --home "$version_home" --repo "$repo_root" --structural-only >/dev/null 2>&1; then
  printf '%s\n' "old Claude version must reject orphan official task hooks" >&2
  exit 1
fi

printf '%s\n' "verification security tests: PASS"
