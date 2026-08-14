#!/usr/bin/env python3
"""Render model labels for exact Claudex5 Claude subagent names."""

from __future__ import annotations

import json
import sys
from typing import Any


ROLE_LABELS = {
    "harness-orchestrator": "Claude Fable 5 · high",
    "harness-orchestrator-opus": "Claude Opus 5 · high",
    "harness-researcher": "Claude Sonnet 5 · high",
    "harness-implementer": "Claude Sonnet 5 · high",
    "harness-implementer-opus": "Claude Opus 5 · high",
    "harness-architecture-reviewer": "Claude Opus 5 · high",
    "harness-code-reviewer": "Claude Opus 5 · high",
    "harness-judge": "Claude Fable 5 · high",
    "harness-judge-opus": "Claude Opus 5 · high",
}


def display_text(value: Any) -> str:
    """Collapse text to one terminal-safe line without ANSI controls."""
    if not isinstance(value, str):
        return ""
    without_controls = "".join(
        " " if ord(character) < 32 or ord(character) == 127 else character
        for character in value
    )
    return " ".join(without_controls.split())


def render(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
        raise ValueError("invalid status payload")

    rows: list[dict[str, str]] = []
    for task in payload["tasks"]:
        if not isinstance(task, dict):
            continue
        task_id = task.get("id")
        name = task.get("name")
        if not isinstance(task_id, str) or not isinstance(name, str):
            continue
        label = ROLE_LABELS.get(name)
        if label is None:
            continue
        description = display_text(task.get("description"))
        content = f"{name} [{label}]"
        if description:
            content = f"{content} · {description}"
        rows.append({"id": task_id, "content": content})
    return rows


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        rows = render(payload)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        print("invalid subagent status input", file=sys.stderr)
        return 2

    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
