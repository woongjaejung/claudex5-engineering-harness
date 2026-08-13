"""Deterministic terminal rendering for Claudex5 live snapshots."""

from __future__ import annotations

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


def _incoming(snapshot: Mapping[str, object]) -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    edges = snapshot.get("edges", {})
    if not isinstance(edges, Mapping):
        return result
    ordered = sorted(
        (edge for edge in edges.values() if isinstance(edge, dict)),
        key=lambda edge: (str(edge.get("target", "")), str(edge.get("kind", "")), str(edge.get("source", ""))),
    )
    for edge in ordered:
        target = str(edge.get("target", ""))
        result.setdefault(target, []).append((str(edge.get("source", "")), str(edge.get("kind", ""))))
    return result


def _display_name(node: Mapping[str, object]) -> str:
    return str(node.get("label") or node.get("id") or "unknown")


def render_snapshot(
    snapshot: Mapping[str, object] | None,
    columns: int = 120,
    color: bool = False,
    unicode: bool = True,
) -> str:
    """Render a snapshot without terminal side effects.

    ``color`` is reserved for the follow-mode caller; the pure renderer currently
    emits stable uncoloured text so snapshots are suitable for tests and logs.
    """

    del color
    if not snapshot:
        return "No Claudex5 run is available.\n"

    columns = max(32, int(columns))
    nodes = _ordered_nodes(snapshot)
    incoming = _incoming(snapshot)
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
                for source, _kind in incoming.get(node_id, [])
            ]
            suffix = f"; depends on {', '.join(dependency_names)}" if dependency_names else "; depends on none"
            prefix = f"{symbol} {_display_name(node)}"
            lines.append(_clip(prefix + suffix, columns, unicode))
        return "\n".join(lines) + "\n"

    connector = "└─" if unicode else "+-"
    root_ids = {str(node.get("id", "")) for node in nodes if not incoming.get(str(node.get("id", "")))}
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
    return "\n".join(lines) + "\n"
