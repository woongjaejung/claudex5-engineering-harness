#!/usr/bin/env python3
"""Render "name [model · effort]" rows for Claude subagents.

Claude Code 2.1.233 gives the renderer the resolved ``model``/``effort`` but
not the subagent name, and a custom row replaces the whole body including the
default name. The name is recovered from the task's own transcript file
(``<session>/subagents/agent-<id>.jsonl``), whose assistant entries carry it
as ``attributionAgent``. When the payload omits the model, known Claudex5
roles fall back to the fixed mapping so their rows stay labeled.
"""

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

MODEL_FAMILY_NAMES = (
    ("claude-fable-5", "Claude Fable 5"),
    ("claude-mythos-5", "Claude Mythos 5"),
    ("claude-opus-5", "Claude Opus 5"),
    ("claude-sonnet-5", "Claude Sonnet 5"),
    ("claude-haiku-4-5", "Claude Haiku 4.5"),
)

TRANSCRIPT_SCAN_LINES = 50


def display_text(value: Any) -> str:
    """Collapse text to one terminal-safe line without ANSI controls."""
    if not isinstance(value, str):
        return ""
    without_controls = "".join(
        " " if ord(character) < 32 or ord(character) == 127 else character
        for character in value
    )
    return " ".join(without_controls.split())


def friendly_model(model_id: str) -> str:
    for prefix, name in MODEL_FAMILY_NAMES:
        if model_id.startswith(prefix):
            return name
    return model_id


def subagent_name(payload: dict[str, Any], task: dict[str, Any]) -> str:
    """Resolve the agent name from the payload or the task's transcript."""
    name = task.get("name")
    if isinstance(name, str) and name:
        return display_text(name)
    transcript = payload.get("transcript_path")
    task_id = task.get("id", "")
    if (
        not isinstance(transcript, str)
        or not transcript.endswith(".jsonl")
        or not task_id.replace("-", "").isalnum()
    ):
        return ""
    path = f"{transcript[:-len('.jsonl')]}/subagents/agent-{task_id}.jsonl"
    try:
        with open(path, encoding="utf-8") as handle:
            for _ in range(TRANSCRIPT_SCAN_LINES):
                line = handle.readline()
                if not line:
                    break
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    agent = entry.get("attributionAgent")
                    if isinstance(agent, str) and agent:
                        return display_text(agent)
    except OSError:
        pass
    return ""


def task_label(payload: dict[str, Any], task: dict[str, Any]) -> str | None:
    """Label from the payload's resolved model, else the fixed role mapping."""
    model = display_text(task.get("model"))
    if model:
        effort = task.get("effort")
        if isinstance(effort, (int, float)) and not isinstance(effort, bool):
            effort_text = str(effort)
        else:
            effort_text = display_text(effort)
        if effort_text:
            return f"{friendly_model(model)} · {effort_text}"
        return friendly_model(model)
    return ROLE_LABELS.get(subagent_name(payload, task))


def render(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
        raise ValueError("invalid status payload")

    rows: list[dict[str, str]] = []
    for task in payload["tasks"]:
        if not isinstance(task, dict):
            continue
        task_id = task.get("id")
        if not isinstance(task_id, str):
            continue
        label = task_label(payload, task)
        if label is None:
            continue
        name = subagent_name(payload, task)
        content = f"{name} [{label}]" if name else f"[{label}]"
        description = display_text(task.get("description"))
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
