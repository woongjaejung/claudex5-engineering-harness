"""Normalize allowlisted Claude Code hook payloads into private graph events."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, TextIO

from .model import ROLE_METADATA, sanitize_label, validate_identifier
from .store import StateStore


_TASK_STATES = {
    "pending": "waiting",
    "waiting": "waiting",
    "in_progress": "running",
    "running": "running",
    "completed": "passed",
    "passed": "passed",
    "failed": "failed",
    "blocked": "blocked",
    "deleted": "skipped",
    "skipped": "skipped",
    "interrupted": "interrupted",
}


def _safe_identifier(value: object, prefix: str = "") -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = value if not prefix or value.startswith(prefix) else f"{prefix}{value}"
    try:
        return validate_identifier(candidate)
    except ValueError:
        return None


def _session(payload: dict[str, Any]) -> str | None:
    return _safe_identifier(payload.get("session_id"))


def _event(event_type: str, node_id: str, payload: dict[str, object]) -> dict[str, object]:
    return {"event_type": event_type, "node_id": node_id, "payload": payload, "source": "claude-hook"}


def _task_input(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("tool_input")
    return value if isinstance(value, dict) else {}


def _task_response(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("tool_response")
    if not isinstance(value, dict):
        return {}
    task = value.get("task")
    return task if isinstance(task, dict) else value


def _task_metadata(subject: object, description: object) -> dict[str, object]:
    result: dict[str, object] = {"kind": "task"}
    if isinstance(subject, str) and subject:
        result["label"] = sanitize_label(subject)
    if isinstance(description, str) and description:
        result["description"] = sanitize_label(description, limit=160)
    return result


def _first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _dependencies(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    dependencies: list[str] = []
    for item in value:
        if isinstance(item, (str, int)):
            dependency = _safe_identifier(str(item), "task:")
            if dependency is not None and dependency not in dependencies:
                dependencies.append(dependency)
    return dependencies


def _agent_kind(role: str) -> str:
    if role in {"harness-architecture-reviewer", "harness-code-reviewer"}:
        return "review"
    if role in {"harness-judge", "harness-judge-opus"}:
        return "judge"
    return "claude_agent"


def _agent_payload(role_value: object) -> dict[str, object]:
    role = sanitize_label(role_value) if isinstance(role_value, str) else ""
    result: dict[str, object] = {
        "kind": _agent_kind(role),
        "label": role or "Claude subagent",
    }
    if role:
        result["role"] = role
        result.update(ROLE_METADATA.get(role, {}))
    return result


def normalize_hook(payload: object) -> list[dict[str, object]]:
    """Return zero or one allowlisted lifecycle events from a Claude hook object."""
    if not isinstance(payload, dict):
        return []
    session_id = _session(payload)
    if session_id is None:
        return []
    hook_name = payload.get("hook_event_name")
    session_node = f"session:{session_id}"

    if hook_name == "SessionStart":
        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            return []
        result: dict[str, object] = {"cwd": str(Path(cwd).expanduser().resolve(strict=False))}
        session_title = payload.get("session_title")
        if isinstance(session_title, str) and session_title:
            result["title"] = sanitize_label(session_title)
        return [_event("session.started", session_node, result)]

    if hook_name in {"TaskCreated", "TaskCompleted"}:
        identifier = _safe_identifier(payload.get("task_id"), "task:")
        if identifier is None:
            return []
        return [
            _event(
                "task.created",
                identifier,
                _task_metadata(payload.get("task_subject"), payload.get("task_description")),
            )
        ]

    if hook_name == "PreToolUse" and payload.get("tool_name") == "TaskCreate":
        tool_input = _task_input(payload)
        identifier = _safe_identifier(tool_input.get("taskId"), "task:")
        if identifier is None:
            identifier = _safe_identifier(tool_input.get("id"), "task:")
        if identifier is None:
            identifier = _safe_identifier(payload.get("tool_use_id"), "task:compat-")
        if identifier is None:
            return []
        raw_label = tool_input.get("subject", tool_input.get("title"))
        result: dict[str, object] = {
            "kind": "task",
            "label": sanitize_label(raw_label) if isinstance(raw_label, str) else "Task",
            "dependencies": _dependencies(
                tool_input.get("blockedBy", tool_input.get("dependsOn", tool_input.get("dependencies", [])))
            ),
        }
        return [_event("task.created", identifier, result)]

    if hook_name == "PostToolUse" and payload.get("tool_name") == "TaskCreate":
        tool_input = _task_input(payload)
        response = _task_response(payload)
        identifier = _safe_identifier(response.get("taskId"), "task:")
        if identifier is None:
            identifier = _safe_identifier(response.get("id"), "task:")
        if identifier is None:
            return []
        result = _task_metadata(
            _first_string(tool_input.get("subject"), tool_input.get("title"), response.get("subject"), response.get("title")),
            _first_string(tool_input.get("description"), response.get("description")),
        )
        compatibility_id = _safe_identifier(payload.get("tool_use_id"), "task:compat-")
        if compatibility_id is not None:
            result["supersedes"] = compatibility_id
        return [_event("task.created", identifier, result)]

    if hook_name == "PostToolUse" and payload.get("tool_name") == "Agent":
        tool_input = _task_input(payload)
        tool_response = payload.get("tool_response")
        response = tool_response if isinstance(tool_response, dict) else {}
        identifier = _safe_identifier(response.get("agentId"), "agent:")
        if identifier is None:
            identifier = _safe_identifier(response.get("agent_id"), "agent:")
        description = tool_input.get("description")
        if identifier is None or not isinstance(description, str) or not description:
            return []
        return [_event("node.updated", identifier, {"description": sanitize_label(description, limit=160)})]

    if hook_name == "PostToolUse" and payload.get("tool_name") == "TaskUpdate":
        tool_input = _task_input(payload)
        response = _task_response(payload)
        raw_identifier = tool_input.get("taskId", tool_input.get("id"))
        if raw_identifier is None:
            raw_identifier = response.get("taskId", response.get("id"))
        identifier = _safe_identifier(raw_identifier, "task:")
        if identifier is None:
            return []
        raw_state = tool_input.get("status", response.get("status"))
        state = _TASK_STATES.get(raw_state) if isinstance(raw_state, str) else None
        if state is None:
            return []
        result = {"kind": "task", "state": state}
        title = tool_input.get("subject", response.get("subject"))
        if isinstance(title, str) and title:
            result["label"] = sanitize_label(title)
        return [_event("task.updated", identifier, result)]

    if hook_name == "SubagentStart":
        identifier = _safe_identifier(payload.get("agent_id"), "agent:")
        if identifier is None:
            return []
        return [_event("node.started", identifier, _agent_payload(payload.get("agent_type")))]

    if hook_name == "SubagentStop":
        identifier = _safe_identifier(payload.get("agent_id"), "agent:")
        if identifier is None:
            return []
        result = _agent_payload(payload.get("agent_type"))
        raw_state = payload.get("status")
        result["state"] = _TASK_STATES.get(raw_state, "passed") if isinstance(raw_state, str) else "passed"
        return [_event("node.finished", identifier, result)]

    if hook_name == "Stop":
        return [_event("checkpoint", session_node, {"label": "Claude checkpoint"})]

    if hook_name == "SessionEnd":
        return [_event("session.ended", session_node, {"state": "passed"})]

    return []


def record_hook(payload: object, store: StateStore) -> list[dict[str, object]]:
    """Persist normalized events, dropping lock contention as observability-only loss."""
    if not isinstance(payload, dict):
        return []
    session_id = _session(payload)
    if session_id is None:
        return []
    recorded: list[dict[str, object]] = []
    try:
        normalized = normalize_hook(payload)
        for item in normalized:
            recorded.append(
                store.append(
                    session_id,
                    str(item["event_type"]),
                    str(item["node_id"]),
                    item["payload"],  # type: ignore[arg-type]
                    source="claude-hook",
                )
            )
        if normalized and payload.get("hook_event_name") == "SessionStart":
            store.cleanup(max_age_days=7)
    except TimeoutError:
        return []
    return recorded


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None, stderr: TextIO | None = None) -> int:
    """Run the non-blocking Claude hook recorder."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-test", action="store_true")
    try:
        arguments = parser.parse_args(argv)
    except SystemExit:
        return 1
    input_stream = stdin or sys.stdin
    error_stream = stderr or sys.stderr
    try:
        payload = json.load(input_stream)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be an object")
        record_hook(payload, StateStore())
        return 0
    except (json.JSONDecodeError, UnicodeError, ValueError, TypeError):
        print("claudex5-live-graph: invalid-input", file=error_stream)
        return 1 if arguments.self_test else 0
    except (OSError, TimeoutError):
        print("claudex5-live-graph: store-unavailable", file=error_stream)
        return 1 if arguments.self_test else 0
    except Exception:
        print("claudex5-live-graph: collector-error", file=error_stream)
        return 1 if arguments.self_test else 0


if __name__ == "__main__":
    raise SystemExit(main())
