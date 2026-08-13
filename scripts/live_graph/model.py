"""Pure event validation and reduction for Claudex5 live graph snapshots."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


SCHEMA_VERSION = 1
NODE_KINDS = frozenset(
    {
        "session",
        "workflow_stage",
        "task",
        "claude_agent",
        "codex_agent",
        "review",
        "judge",
        "quality_gate",
    }
)
NODE_STATES = frozenset(
    {"waiting", "running", "passed", "failed", "blocked", "skipped", "interrupted"}
)
TERMINAL_STATES = frozenset({"passed", "failed", "blocked", "skipped", "interrupted"})
EDGE_KINDS = frozenset({"contains", "depends_on", "dispatches", "reviews", "gates"})

ROLE_METADATA: dict[str, dict[str, str]] = {
    "harness-orchestrator": {"model": "claude-fable-5", "effort": "high"},
    "harness-orchestrator-opus": {"model": "claude-opus-5", "effort": "high"},
    "harness-researcher": {"model": "claude-sonnet-5", "effort": "high"},
    "harness-implementer": {"model": "claude-sonnet-5", "effort": "high"},
    "harness-implementer-opus": {"model": "claude-opus-5", "effort": "high"},
    "harness-architecture-reviewer": {"model": "claude-opus-5", "effort": "high"},
    "harness-judge": {"model": "claude-fable-5", "effort": "high"},
    "harness-judge-opus": {"model": "claude-opus-5", "effort": "high"},
    "harness-sol-plan-review": {"model": "gpt-5.6-sol", "effort": "high"},
    "harness-sol-research": {"model": "gpt-5.6-sol", "effort": "high"},
    "harness-sol-review": {"model": "gpt-5.6-sol", "effort": "high"},
    "harness-sol-adversarial-review": {"model": "gpt-5.6-sol", "effort": "high"},
    "harness-luna-implementation": {"model": "gpt-5.6-luna", "effort": "max"},
    "harness-spark-ui-iteration": {"model": "gpt-5.3-codex-spark"},
    # CLI wrapper aliases use underscores because they are convenient shell values.
    "harness_sol_plan_review": {"model": "gpt-5.6-sol", "effort": "high"},
    "harness_sol_research": {"model": "gpt-5.6-sol", "effort": "high"},
    "harness_sol_review": {"model": "gpt-5.6-sol", "effort": "high"},
    "harness_sol_adversarial_review": {"model": "gpt-5.6-sol", "effort": "high"},
    "harness_luna_alternative": {"model": "gpt-5.6-luna", "effort": "max"},
    "harness_spark_ui_iteration": {"model": "gpt-5.3-codex-spark"},
}

_IDENTIFIER_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}\Z")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\bsk-(?:proj-|ant-api\d*-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
)


def validate_identifier(value: object, *, name: str = "identifier") -> str:
    """Return a safe logical identifier, rejecting all path-like forms."""
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"invalid {name}")
    lowered = value.lower()
    if ".." in value or "%2f" in lowered or "%5c" in lowered:
        raise ValueError(f"invalid {name}")
    return value


def sanitize_label(value: object, limit: int = 120) -> str:
    """Return a one-line, clipped label or a fixed redaction marker."""
    if limit < 0:
        raise ValueError("label limit must not be negative")
    text = "" if value is None else str(value)
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return "[REDACTED]"
    cleaned = "".join(
        " " if character.isspace() or unicodedata.category(character).startswith("C") else character
        for character in text
    )
    return " ".join(cleaned.split())[:limit]


def _edge_id(source: str, target: str, kind: str) -> str:
    return f"{source}|{kind}|{target}"


def _add_edge(snapshot: dict[str, Any], source: str, target: str, kind: str) -> None:
    validate_identifier(source, name="edge source")
    validate_identifier(target, name="edge target")
    if kind not in EDGE_KINDS:
        raise ValueError("invalid edge kind")
    identifier = _edge_id(source, target, kind)
    snapshot["edges"].setdefault(
        identifier,
        {"id": identifier, "source": source, "target": target, "kind": kind},
    )


def new_snapshot(session_id: str, cwd: str, timestamp: str) -> dict[str, object]:
    """Create an empty running snapshot with a root session node."""
    session_id = validate_identifier(session_id, name="session identifier")
    root_id = f"session:{session_id}"
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "cwd": str(cwd),
        "created_at": timestamp,
        "updated_at": timestamp,
        "sequence": 0,
        "status": "running",
        "degraded": False,
        "root_node_id": root_id,
        "nodes": {
            root_id: {
                "id": root_id,
                "kind": "session",
                "label": sanitize_label(session_id),
                "state": "running",
                "sequence": 0,
                "started_at": timestamp,
            }
        },
        "edges": {},
        "checkpoints": [],
    }


def _node_fields(node_id: str, payload: dict[str, Any], sequence: int, timestamp: str) -> dict[str, Any]:
    kind = payload.get("kind", "task")
    if kind not in NODE_KINDS:
        raise ValueError("invalid node kind")
    node: dict[str, Any] = {
        "id": node_id,
        "kind": kind,
        "label": sanitize_label(payload.get("label", payload.get("title", node_id))),
        "state": payload.get("state", "waiting"),
        "sequence": sequence,
    }
    if node["state"] not in NODE_STATES:
        raise ValueError("invalid node state")
    for key in ("role", "model", "effort"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            node[key] = sanitize_label(value)
    role = node.get("role")
    if isinstance(role, str) and role in ROLE_METADATA:
        node.update({key: value for key, value in ROLE_METADATA[role].items() if key not in node})
    if node["state"] == "running":
        node["started_at"] = timestamp
    return node


def _attach_parent(snapshot: dict[str, Any], node_id: str, payload: dict[str, Any]) -> None:
    parent_id = payload.get("parent_id", snapshot["root_node_id"])
    if parent_id:
        parent_id = validate_identifier(parent_id, name="parent identifier")
        _add_edge(snapshot, parent_id, node_id, payload.get("parent_edge_kind", "contains"))


def reduce_event(snapshot: dict[str, object], event: dict[str, object]) -> dict[str, object]:
    """Apply one validated lifecycle event to a snapshot in place."""
    if event.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported event schema")
    if event.get("session_id") != snapshot.get("session_id"):
        raise ValueError("event session does not match snapshot")
    sequence = event.get("sequence")
    if not isinstance(sequence, int) or sequence < 1:
        raise ValueError("invalid event sequence")
    timestamp = event.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        raise ValueError("invalid event timestamp")
    event_type = event.get("event_type")
    node_id = validate_identifier(event.get("node_id"), name="node identifier")
    payload_value = event.get("payload", {})
    if not isinstance(payload_value, dict):
        raise ValueError("invalid event payload")
    payload: dict[str, Any] = payload_value
    nodes: dict[str, dict[str, Any]] = snapshot["nodes"]  # type: ignore[assignment]

    if event_type in {"node.created", "task.created"}:
        effective = dict(payload)
        if event_type == "task.created":
            effective.setdefault("kind", "task")
            effective.setdefault("state", "waiting")
        nodes.setdefault(node_id, _node_fields(node_id, effective, sequence, timestamp))
        _attach_parent(snapshot, node_id, effective)  # type: ignore[arg-type]
        dependencies = effective.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise ValueError("invalid dependencies")
        for dependency in dependencies:
            _add_edge(snapshot, node_id, validate_identifier(dependency, name="dependency"), "depends_on")  # type: ignore[arg-type]
    elif event_type == "node.started":
        existing = nodes.get(node_id)
        if existing is None:
            effective = dict(payload)
            effective["state"] = "running"
            nodes[node_id] = _node_fields(node_id, effective, sequence, timestamp)
            _attach_parent(snapshot, node_id, effective)  # type: ignore[arg-type]
        elif existing["state"] not in TERMINAL_STATES:
            existing["state"] = "running"
            existing.setdefault("started_at", timestamp)
            for key in ("role", "model", "effort"):
                value = payload.get(key)
                if isinstance(value, str) and value and key not in existing:
                    existing[key] = sanitize_label(value)
            role = existing.get("role")
            if isinstance(role, str) and role in ROLE_METADATA:
                for key, value in ROLE_METADATA[role].items():
                    existing.setdefault(key, value)
    elif event_type in {"node.finished", "task.updated"}:
        state = payload.get("state")
        if state not in NODE_STATES:
            raise ValueError("invalid terminal or task state")
        existing = nodes.get(node_id)
        if existing is None:
            effective = dict(payload)
            effective.setdefault("kind", "task" if event_type == "task.updated" else "claude_agent")
            nodes[node_id] = _node_fields(node_id, effective, sequence, timestamp)
            nodes[node_id]["degraded"] = True
            snapshot["degraded"] = True
            _attach_parent(snapshot, node_id, effective)  # type: ignore[arg-type]
        elif existing["state"] not in TERMINAL_STATES or existing["state"] == state:
            existing["state"] = state
            if state in TERMINAL_STATES:
                existing["finished_at"] = timestamp
    elif event_type == "edge.created":
        target = validate_identifier(payload.get("target"), name="edge target")
        _add_edge(snapshot, node_id, target, str(payload.get("kind", "contains")))  # type: ignore[arg-type]
    elif event_type == "checkpoint":
        checkpoints: list[dict[str, Any]] = snapshot["checkpoints"]  # type: ignore[assignment]
        checkpoints.append({"sequence": sequence, "timestamp": timestamp, "label": sanitize_label(payload.get("label", "checkpoint"))})
    elif event_type == "session.started":
        nodes[snapshot["root_node_id"]]["state"] = "running"  # type: ignore[index]
        snapshot["status"] = "running"
    elif event_type == "session.ended":
        state = payload.get("state", "passed")
        if state not in TERMINAL_STATES:
            raise ValueError("invalid session state")
        for node in nodes.values():
            if node["state"] == "running":
                node["state"] = state if node["kind"] == "session" else "interrupted"
                node["finished_at"] = timestamp
        snapshot["status"] = state
    else:
        raise ValueError("unknown event type")

    snapshot["sequence"] = max(int(snapshot.get("sequence", 0)), sequence)
    snapshot["updated_at"] = timestamp
    return snapshot
