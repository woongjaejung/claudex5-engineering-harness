#!/usr/bin/env python3
"""Stable Claude Code hook entry point for the Claudex5 live graph."""

from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    self_test = "--self-test" in sys.argv[1:]
    try:
        repository = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repository))
        from scripts.live_graph.record import main as record_main

        return record_main(sys.argv[1:])
    except Exception:
        print("claudex5-live-graph: collector-error", file=sys.stderr)
        return 1 if self_test else 0


if __name__ == "__main__":
    raise SystemExit(main())
