#!/usr/bin/env python3
"""Command-line interface for Claudex5 live graph observability."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Sequence
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.live_graph.model import ROLE_METADATA, sanitize_label
from scripts.live_graph.store import StateStore
from scripts.live_graph.terminal import render_snapshot


CODEX_ROLES = {
    "harness_sol_research": ("gpt-5.6-sol", "high", "codex_agent"),
    "harness_sol_plan_review": ("gpt-5.6-sol", "high", "review"),
    "harness_luna_implementation": ("gpt-5.6-luna", "max", "codex_agent"),
    "harness_sol_review": ("gpt-5.6-sol", "high", "review"),
    "harness_sol_adversarial_review": ("gpt-5.6-sol", "high", "review"),
    "harness_spark_ui_iteration": ("gpt-5.3-codex-spark", "high", "codex_agent"),
}
SANDBOXES = ("read-only", "workspace-write", "danger-full-access")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claudex5", description="Inspect a Claudex5 run graph")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dashboard = subparsers.add_parser("dashboard", help="show the active graph")
    dashboard.add_argument("--session-id")
    dashboard.add_argument("--once", action="store_true")
    dashboard.add_argument("--web", action="store_true")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--no-open", action="store_true")
    dashboard.add_argument("--ascii", action="store_true")

    status = subparsers.add_parser("status", help="print snapshot status")
    status.add_argument("--session-id")
    status.add_argument("--json", action="store_true")

    event = subparsers.add_parser("event", help="record an allowlisted lifecycle event")
    event.add_argument("--session-id", required=True)
    event.add_argument("--type", required=True, choices=(
        "session.started", "session.ended", "node.created", "node.started",
        "node.finished", "task.created", "task.updated", "edge.created", "checkpoint",
    ))
    event.add_argument("--node-id", required=True)
    event.add_argument("--kind")
    event.add_argument("--label")
    event.add_argument("--state")
    event.add_argument("--role")
    event.add_argument("--parent-id")
    event.add_argument("--parent-edge-kind")
    event.add_argument("--dependency", action="append", default=[])
    event.add_argument("--target")
    event.add_argument("--edge-kind")
    event.add_argument("--cwd")

    codex_run = subparsers.add_parser("codex-run", help="run a fixed Codex role with lifecycle events")
    codex_run.add_argument("--session-id")
    codex_run.add_argument("--role", required=True, choices=tuple(CODEX_ROLES))
    codex_run.add_argument("--label", required=True)
    codex_run.add_argument("--sandbox", choices=SANDBOXES, default="workspace-write")
    codex_run.add_argument("--prompt-file", type=Path)
    codex_run.add_argument("--parent-id")
    codex_run.add_argument("--dependency", action="append", default=[])

    gate_run = subparsers.add_parser("gate-run", help="run one deterministic quality gate")
    gate_run.add_argument("--session-id")
    gate_run.add_argument("--group-id")
    gate_run.add_argument("--name", required=True)
    gate_run.add_argument("--dependency", action="append", default=[])
    gate_run.add_argument("child", nargs=argparse.REMAINDER)

    clean = subparsers.add_parser("clean", help="remove old private run state")
    clean.add_argument("--all", action="store_true")
    clean.add_argument("--days", type=float, default=7)
    return parser


def _snapshot(store: StateStore, session_id: str | None) -> dict | None:
    return store.load(session_id) if session_id else store.latest()


def _session_id(store: StateStore, requested: str | None) -> str:
    if requested:
        return requested
    snapshot = store.latest(Path.cwd()) or store.latest()
    if snapshot:
        return str(snapshot["session_id"])
    session_id = f"manual-{uuid4().hex}"
    store.append(
        session_id,
        "session.started",
        f"session:{session_id}",
        {"cwd": str(Path.cwd())},
        source="explicit",
    )
    return session_id


def _payload(arguments: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in ("kind", "label", "state", "role", "parent_id", "parent_edge_kind", "target", "cwd"):
        value = getattr(arguments, key, None)
        if value is not None:
            payload[key] = value
    if arguments.dependency:
        payload["dependencies"] = arguments.dependency
    if arguments.edge_kind:
        payload["kind"] = arguments.edge_kind
    role = payload.get("role")
    if isinstance(role, str) and role in ROLE_METADATA:
        payload.update(ROLE_METADATA[role])
    return payload


def _run_child(command: list[str], *, prompt: str | None = None) -> tuple[int, bool]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if prompt is not None else None,
        text=True,
        start_new_session=True,
    )
    interrupted = False
    forwarded_signal: int | None = None
    previous: dict[int, object] = {}

    def forward(signum: int, _frame: object) -> None:
        nonlocal interrupted, forwarded_signal
        interrupted = True
        forwarded_signal = signum
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, forward)
    try:
        process.communicate(prompt)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    returncode = process.returncode if process.returncode is not None else 1
    if returncode < 0:
        returncode = 128 + abs(returncode)
        interrupted = True
    elif forwarded_signal is not None:
        returncode = 128 + forwarded_signal
    return returncode, interrupted


def _finish_state(returncode: int, interrupted: bool) -> str:
    if interrupted:
        return "interrupted"
    return "passed" if returncode == 0 else "failed"


def _codex_run(arguments: argparse.Namespace, store: StateStore) -> int:
    session_id = _session_id(store, arguments.session_id)
    model, effort, kind = CODEX_ROLES[arguments.role]
    if arguments.prompt_file is not None:
        if not sys.stdin.isatty():
            piped = sys.stdin.read()
            if piped:
                raise ValueError("use either --prompt-file or standard input, not both")
        prompt = arguments.prompt_file.read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            raise ValueError("codex-run requires --prompt-file or prompt data on standard input")
        prompt = sys.stdin.read()
    if not prompt:
        raise ValueError("Codex prompt must not be empty")
    node_id = f"codex:{uuid4().hex}"
    payload = {
        "kind": kind,
        "label": sanitize_label(arguments.label),
        "role": arguments.role,
        "model": model,
        "effort": effort,
        "parent_id": arguments.parent_id or f"session:{session_id}",
        "dependencies": arguments.dependency,
    }
    store.append(session_id, "node.started", node_id, payload, source="codex-wrapper")
    codex = shutil.which("codex")
    if not codex:
        store.append(session_id, "node.finished", node_id, {**payload, "state": "failed"}, source="codex-wrapper")
        raise RuntimeError("Codex CLI is not available")
    command = [
        codex, "exec", "--ephemeral", "--model", model,
        "-c", f'model_reasoning_effort="{effort}"',
        "--sandbox", arguments.sandbox, "-",
    ]
    returncode = 1
    interrupted = False
    try:
        returncode, interrupted = _run_child(command, prompt=prompt)
        return returncode
    finally:
        store.append(
            session_id,
            "node.finished",
            node_id,
            {**payload, "state": _finish_state(returncode, interrupted)},
            source="codex-wrapper",
        )


def _gate_run(arguments: argparse.Namespace, store: StateStore) -> int:
    child = list(arguments.child)
    if child and child[0] == "--":
        child.pop(0)
    if not child:
        raise ValueError("gate-run requires a child command after --")
    session_id = _session_id(store, arguments.session_id)
    node_id = f"gate:{uuid4().hex}"
    group_id = arguments.group_id or f"quality:{uuid4().hex}"
    payload = {
        "kind": "quality_gate",
        "label": sanitize_label(arguments.name),
        "parent_id": group_id,
        "parent_edge_kind": "gates",
        "dependencies": arguments.dependency,
    }
    store.append(session_id, "node.started", node_id, payload, source="gate-wrapper")
    returncode = 1
    interrupted = False
    try:
        returncode, interrupted = _run_child(child)
        return returncode
    finally:
        store.append(
            session_id,
            "node.finished",
            node_id,
            {**payload, "state": _finish_state(returncode, interrupted)},
            source="gate-wrapper",
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    store = StateStore()
    try:
        if arguments.command == "event":
            store.append(
                arguments.session_id,
                arguments.type,
                arguments.node_id,
                _payload(arguments),
                source="explicit",
            )
            return 0
        if arguments.command == "status":
            snapshot = _snapshot(store, arguments.session_id)
            if arguments.json:
                print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
            else:
                print("no run" if snapshot is None else f"{snapshot['session_id']}: {snapshot['status']}")
            return 0
        if arguments.command == "dashboard":
            if arguments.web:
                from scripts.live_graph.web import serve_dashboard

                return serve_dashboard(store, arguments.session_id, arguments.host, arguments.port, not arguments.no_open)
            previous = None
            while True:
                rendered = render_snapshot(
                    _snapshot(store, arguments.session_id),
                    columns=shutil.get_terminal_size((120, 24)).columns,
                    color=sys.stdout.isatty(),
                    unicode=not arguments.ascii,
                )
                if arguments.once:
                    sys.stdout.write(rendered)
                    return 0
                if rendered != previous:
                    sys.stdout.write("\033[2J\033[H" + rendered)
                    sys.stdout.flush()
                    previous = rendered
                time.sleep(1)
        if arguments.command == "codex-run":
            return _codex_run(arguments, store)
        if arguments.command == "gate-run":
            return _gate_run(arguments, store)
        if arguments.command == "clean":
            removed = store.clear_all() if arguments.all else store.cleanup(arguments.days)
            print(f"Removed {len(removed)} run{'s' if len(removed) != 1 else ''}.")
            return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
