"""Pure session selection and snapshot bundle queries."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
from typing import Protocol

from .model import SCHEMA_VERSION, validate_identifier


class SnapshotStore(Protocol):
    def snapshots(self) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class SessionSelection:
    mode: str
    session_id: str | None = None

    @classmethod
    def one(cls, session_id: str) -> "SessionSelection":
        return cls("session", validate_identifier(session_id, name="session identifier"))

    @classmethod
    def all(cls) -> "SessionSelection":
        return cls("all", None)


def _ordered(snapshots: list[dict[str, object]]) -> list[dict[str, object]]:
    ordered = list(snapshots)
    ordered.sort(key=lambda snapshot: str(snapshot.get("session_id", "")), reverse=True)
    ordered.sort(key=lambda snapshot: str(snapshot.get("updated_at", "")), reverse=True)
    ordered.sort(key=lambda snapshot: snapshot.get("status") != "running")
    return ordered


def catalog(snapshots: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return safe, stable selector metadata without graph contents."""
    rows: list[dict[str, object]] = []
    for snapshot in _ordered(snapshots):
        session_id = validate_identifier(snapshot.get("session_id"), name="session identifier")
        title = snapshot.get("title", session_id)
        rows.append(
            {
                "session_id": session_id,
                "cwd": str(snapshot.get("cwd", "")),
                "title": str(title) if isinstance(title, str) and title else session_id,
                "status": str(snapshot.get("status", "")),
                "created_at": str(snapshot.get("created_at", "")),
                "updated_at": str(snapshot.get("updated_at", "")),
                "sequence": int(snapshot.get("sequence", 0)),
            }
        )
    return rows


def group_snapshots(
    snapshots: list[dict[str, object]], completed_limit: int | None
) -> list[dict[str, object]]:
    """Group running and bounded terminal sessions by their canonical project path."""
    if completed_limit is not None and (not isinstance(completed_limit, int) or completed_limit < 0):
        raise ValueError("completed limit must be a non-negative integer or None")

    projects: dict[str, dict[str, list[dict[str, object]]]] = {}
    for snapshot in _ordered(snapshots):
        cwd = str(snapshot.get("cwd", ""))
        group = projects.setdefault(cwd, {"running": [], "completed": []})
        key = "running" if snapshot.get("status") == "running" else "completed"
        group[key].append(snapshot)

    result: list[dict[str, object]] = []
    for cwd in sorted(projects):
        group = projects[cwd]
        completed = group["completed"]
        if completed_limit is not None:
            completed = completed[:completed_limit]
        result.append({"cwd": cwd, "running": group["running"], "completed": completed})
    return result


def _project_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    """Copy a snapshot for presentation and omit legacy compatibility nodes."""
    projected = copy.deepcopy(snapshot)
    for key in ("_event_log_size", "_event_log_mtime_ns", "_event_log_sequence"):
        projected.pop(key, None)
    nodes = projected.get("nodes")
    edges = projected.get("edges")
    if not isinstance(nodes, dict):
        return projected
    superseded = {
        node_id
        for node_id, node in nodes.items()
        if isinstance(node, dict) and node.get("superseded_by")
    }
    for node_id in superseded:
        nodes.pop(node_id, None)
    if isinstance(edges, dict):
        for edge_id, edge in list(edges.items()):
            if (
                not isinstance(edge, dict)
                or edge.get("source") in superseded
                or edge.get("target") in superseded
            ):
                edges.pop(edge_id, None)
    return projected


def bundle_revision(
    snapshots: list[dict[str, object]], selection: SessionSelection | None = None
) -> str:
    """Hash lifecycle state and logical selection without presentation text."""
    selected = selection or SessionSelection.all()
    rows = [
        {
            "session_id": validate_identifier(snapshot.get("session_id"), name="session identifier"),
            "schema_version": snapshot.get("schema_version"),
            "sequence": snapshot.get("sequence"),
            "updated_at": snapshot.get("updated_at"),
        }
        for snapshot in snapshots
    ]
    rows.sort(key=lambda row: row["session_id"])
    payload = {
        "selection": {"mode": selected.mode, "session_id": selected.session_id},
        "sessions": rows,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_bundle(
    store: SnapshotStore,
    selection: SessionSelection,
    completed_limit: int | None = None,
) -> dict[str, object]:
    """Build a selection-scoped graph projection with a machine-wide catalog."""
    snapshots = store.snapshots()
    if selection.mode == "session":
        selected = [
            snapshot
            for snapshot in snapshots
            if snapshot.get("session_id") == selection.session_id
        ]
        if len(selected) != 1:
            raise LookupError("selected session is unavailable")
        projected = selected
    elif selection.mode == "all" and selection.session_id is None:
        projected = snapshots
    else:
        raise ValueError("invalid session selection")

    groups = group_snapshots(
        projected, None if selection.mode == "session" else completed_limit
    )
    for group in groups:
        for key in ("running", "completed"):
            group[key] = [_project_snapshot(snapshot) for snapshot in group[key]]
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": bundle_revision(snapshots, selection),
        "selection": {"mode": selection.mode, "session_id": selection.session_id},
        "catalog": catalog(snapshots),
        "projects": groups,
    }
