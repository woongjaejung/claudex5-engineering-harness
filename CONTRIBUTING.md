# Contributing

Thanks for helping improve Claudex5 Engineering Harness.

## Before changing code

1. Open an issue or discussion for behavior that changes global configuration semantics.
2. Keep all managed names under the `harness-` or `harness_` namespace.
3. Never use real credentials as fixtures, even if they are expired or revoked.
4. Preserve user-owned configuration by default; security hardening must remain explicit.

## Local checks

```bash
python3 -m unittest discover -s tests -v
bash tests/test_install.sh
bash tests/test_bootstrap.sh
bash tests/test_verify.sh
bash -n install.sh link.sh verify.sh uninstall.sh bootstrap-system.sh scripts/common.sh
./verify.sh --secrets-only
git diff --check
```

Integration tests must use an isolated temporary home. Do not point tests at your real `~/.claude` or `~/.codex` directories.

## Pull requests

- Explain the user-visible behavior and why global scope is necessary.
- Include a failing test first for executable behavior changes.
- Document install, update, fallback, and uninstall effects.
- Show the exact verification commands and results.
- Confirm `git status --short`, staged diff, and the secret scan before pushing.

Human-facing prose should be reviewed as instructions, not locked to brittle exact-text tests. Executable scripts and configuration merges require behavior tests.
