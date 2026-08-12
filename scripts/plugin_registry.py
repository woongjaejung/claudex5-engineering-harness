#!/usr/bin/env python3
"""Resolve the official Codex plugin helper without following foreign links."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def resolve_codex_helper(registry: Path, home: Path) -> Path | None:
    data = json.loads(registry.read_text(encoding="utf-8"))
    entries = data.get("plugins", {}).get("codex@openai-codex", [])
    if isinstance(entries, dict):
        entries = [entries]
    resolved_home = home.resolve()
    allowed = resolved_home
    for component in (".claude", "plugins", "cache", "openai-codex", "codex"):
        allowed /= component
        if allowed.is_symlink():
            return None
    allowed = allowed.resolve()
    for entry in reversed(entries):
        install_path = entry.get("installPath")
        if not install_path:
            continue
        raw_candidate = Path(install_path)
        if raw_candidate.is_symlink():
            continue
        candidate = raw_candidate.resolve()
        try:
            candidate.relative_to(allowed)
        except ValueError:
            continue
        scripts = candidate / "scripts"
        helper = scripts / "codex-companion.mjs"
        if scripts.is_symlink() or helper.is_symlink() or not helper.is_file():
            continue
        resolved_helper = helper.resolve(strict=True)
        try:
            resolved_helper.relative_to(allowed)
        except ValueError:
            continue
        return resolved_helper
    return None


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    helper = resolve_codex_helper(Path(sys.argv[1]), Path(sys.argv[2]))
    if helper is not None:
        print(helper)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
