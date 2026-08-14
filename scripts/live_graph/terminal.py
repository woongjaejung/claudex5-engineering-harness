"""Deterministic terminal rendering for Claudex5 live snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


UNICODE_STATUS = {
    "passed": "✓",
    "running": "●",
    "waiting": "○",
    "failed": "!",
    "blocked": "◆",
    "skipped": "–",
    "interrupted": "×",
}

ASCII_STATUS = {
    "passed": "[OK]",
    "running": "[RUN]",
    "waiting": "[WAIT]",
    "failed": "[FAIL]",
    "blocked": "[BLOCK]",
    "skipped": "[SKIP]",
    "interrupted": "[STOP]",
}


def _clip(value: object, width: int, unicode: bool) -> str:
    text = " ".join(str(value or "").split())
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    marker = "…" if unicode else "..."
    return text[: max(0, width - len(marker))] + marker


def _ordered_nodes(snapshot: Mapping[str, object]) -> list[dict]:
    nodes = snapshot.get("nodes", {})
    if not isinstance(nodes, Mapping):
        return []
    values = [value for value in nodes.values() if isinstance(value, dict)]
    return sorted(values, key=lambda node: (int(node.get("sequence", 0)), str(node.get("id", ""))))


def _dependencies(snapshot: Mapping[str, object]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    edges = snapshot.get("edges", {})
    if not isinstance(edges, Mapping):
        return result
    ordered = sorted(
        (edge for edge in edges.values() if isinstance(edge, dict)),
        key=lambda edge: (str(edge.get("target", "")), str(edge.get("kind", "")), str(edge.get("source", ""))),
    )
    for edge in ordered:
        if edge.get("kind") == "depends_on":
            result.setdefault(str(edge.get("source", "")), []).append(str(edge.get("target", "")))
    return result


def _display_name(node: Mapping[str, object]) -> str:
    return str(node.get("label") or node.get("id") or "unknown")


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _duration_text(seconds: float) -> str | None:
    if seconds < 0:
        return None
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m" + (f" {seconds}s" if seconds else "")
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h" + (f" {minutes}m" if minutes else "")
    days, hours = divmod(hours, 24)
    return f"{days}d" + (f" {hours}h" if hours else "")


def format_duration(node: Mapping[str, object], now: datetime) -> str:
    """Describe elapsed lifecycle time without fabricating missing evidence."""
    if now.tzinfo is None:
        return "duration unknown"
    now = now.astimezone(timezone.utc)
    state = str(node.get("state") or "")
    started = _timestamp(node.get("started_at"))
    created = _timestamp(node.get("created_at"))
    finished = _timestamp(node.get("finished_at"))
    if state == "running":
        duration = _duration_text((now - started).total_seconds()) if started else None
        return f"running {duration}" if duration is not None else "duration unknown"
    if state == "waiting":
        duration = _duration_text((now - created).total_seconds()) if created else None
        return f"waiting {duration}" if duration is not None else "duration unknown"
    if state in {"passed", "failed", "blocked", "skipped", "interrupted"}:
        start = started
        if start is None and node.get("kind") == "task" and not node.get("degraded"):
            start = created
        duration = _duration_text((finished - start).total_seconds()) if finished and start else None
        return f"{state} in {duration}" if duration is not None else "duration unknown"
    return "duration unknown"


def _age(value: object, now: datetime) -> str:
    timestamp = _timestamp(value)
    if timestamp is None:
        return "updated unknown"
    duration = _duration_text((now.astimezone(timezone.utc) - timestamp).total_seconds())
    return f"{duration} ago" if duration is not None else "updated unknown"


def render_session_catalog(rows: list[Mapping[str, object]], now: datetime, unicode: bool = True) -> str:
    """Render the safe session catalog for a human choosing a dashboard target."""
    status_map = UNICODE_STATUS if unicode else ASCII_STATUS
    lines = ["Claudex5 sessions"]
    if not rows:
        lines.append("No retained Claudex5 sessions.")
    for row in rows:
        status = str(row.get("status") or "unknown")
        symbol = status_map.get(status, "?")
        title = str(row.get("title") or row.get("session_id") or "unknown")
        lines.append(f"{symbol} {title} · {status} · {_age(row.get('updated_at'), now)}")
        lines.append(f"  {row.get('cwd') or 'unknown'} · {row.get('session_id') or 'unknown'}")
    return "\n".join(lines) + "\n"


def _session_progress(snapshot: Mapping[str, object]) -> tuple[int, int]:
    nodes = _ordered_nodes(snapshot)
    return sum(1 for node in nodes if node.get("state") in {"passed", "skipped"}), len(nodes)


def render_all_sessions(bundle: Mapping[str, object], columns: int, now: datetime, unicode: bool = True) -> str:
    """Render compact project-grouped status without expanding completed graphs."""
    columns = max(32, int(columns))
    status_map = UNICODE_STATUS if unicode else ASCII_STATUS
    projects = bundle.get("projects", [])
    if not isinstance(projects, list) or not projects:
        return "No Claudex5 run is available.\n"
    lines = ["Claudex5 live sessions"]
    for project in projects:
        if not isinstance(project, Mapping):
            continue
        lines.append(_clip(str(project.get("cwd") or "unknown"), columns, unicode))
        for key in ("running", "completed"):
            snapshots = project.get(key, [])
            if not isinstance(snapshots, list):
                continue
            for snapshot in snapshots:
                if not isinstance(snapshot, Mapping):
                    continue
                complete, total = _session_progress(snapshot)
                state = str(snapshot.get("status") or "unknown")
                symbol = status_map.get(state, "?")
                title = str(snapshot.get("title") or snapshot.get("session_id") or "unknown")
                lines.append(_clip(f"  {symbol} {title} · {state} · {complete}/{total} complete · {_age(snapshot.get('updated_at'), now)}", columns, unicode))
                if key == "running":
                    for node in _ordered_nodes(snapshot):
                        if node.get("state") == "running" and not node.get("superseded_by"):
                            lines.append(_clip(f"    {node.get('label') or node.get('id') or 'unknown'} · {format_duration(node, now)}", columns, unicode))
    return "\n".join(lines) + "\n"


def render_snapshot(
    snapshot: Mapping[str, object] | None,
    columns: int = 120,
    color: bool = False,
    unicode: bool = True,
    now: datetime | None = None,
) -> str:
    """Render a snapshot without terminal side effects.

    ``color`` is reserved for the follow-mode caller; the pure renderer currently
    emits stable uncoloured text so snapshots are suitable for tests and logs.
    """

    del color
    now = now or datetime.now(timezone.utc)
    if not snapshot:
        return "No Claudex5 run is available.\n"

    columns = max(32, int(columns))
    nodes = [node for node in _ordered_nodes(snapshot) if not node.get("superseded_by")]
    dependencies = _dependencies(snapshot)
    by_id = {str(node.get("id", "")): node for node in nodes}
    complete = sum(1 for node in nodes if node.get("state") in {"passed", "skipped"})
    project = Path(str(snapshot.get("cwd") or "unknown")).name or "/"
    status_map = UNICODE_STATUS if unicode else ASCII_STATUS

    lines = [
        _clip("Claudex5 live graph", columns, unicode),
        _clip(
            f"Run {snapshot.get('session_id', 'unknown')} · {project} · "
            f"{complete}/{len(nodes)} complete",
            columns,
            unicode,
        ),
    ]

    if columns < 88:
        lines.append(_clip("Dependency view", columns, unicode))
        for node in nodes:
            node_id = str(node.get("id", ""))
            symbol = status_map.get(str(node.get("state", "waiting")), "?")
            dependency_names = [
                _display_name(by_id[source]) if source in by_id else source
                for source in dependencies.get(node_id, [])
            ]
            suffix = f"; depends on {', '.join(dependency_names)}" if dependency_names else "; depends on none"
            prefix = f"{symbol} {_display_name(node)}"
            if dependency_names:
                line = prefix + suffix + f"; {format_duration(node, now)}"
            else:
                line = prefix + f"; {format_duration(node, now)}" + suffix
            lines.append(_clip(line, columns, unicode))
        return "\n".join(lines) + "\n"

    connector = "└─" if unicode else "+-"
    child_targets = {
        str(edge.get("target", ""))
        for edge in snapshot.get("edges", {}).values()
        if isinstance(edge, dict) and edge.get("kind") != "depends_on"
    } if isinstance(snapshot.get("edges"), Mapping) else set()
    root_ids = {str(node.get("id", "")) for node in nodes if str(node.get("id", "")) not in child_targets}
    for node in nodes:
        node_id = str(node.get("id", ""))
        symbol = status_map.get(str(node.get("state", "waiting")), "?")
        branch = "  " if node_id in root_ids else f"{connector} "
        detail = ""
        model = str(node.get("model") or "")
        effort = str(node.get("effort") or "")
        if model:
            detail = f" [{model}{' · ' + effort if effort else ''}]"
        line = f"{branch}{symbol} {_display_name(node)}{detail}"
        lines.append(_clip(line, columns, unicode))
        description = str(node.get("description") or "")
        duration = format_duration(node, now)
        if description:
            lines.append(_clip(f"    {description} · {duration}", columns, unicode))
        else:
            lines.append(_clip(f"    {duration}", columns, unicode))
    return "\n".join(lines) + "\n"
