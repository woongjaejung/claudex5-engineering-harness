"""Private append-only storage for Claudex5 live graph events."""

from __future__ import annotations

import copy
import errno
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import time
from typing import Any
from uuid import uuid4

from .model import (
    EDGE_KINDS,
    NODE_KINDS,
    NODE_STATES,
    SCHEMA_VERSION,
    new_snapshot,
    reduce_event,
    sanitize_label,
    validate_identifier,
)


_TEXT_FIELDS = frozenset({"label", "title", "session_title", "description"})
_NODE_METADATA_FIELDS = frozenset(
    {"label", "title", "description", "superseded_by", "role", "model", "effort"}
)
_NODE_STRUCTURE_FIELDS = frozenset(
    {"kind", "state", "parent_id", "parent_edge_kind", "dependencies"}
)
_PAYLOAD_FIELDS: dict[str, frozenset[str]] = {
    "session.started": frozenset({"cwd", "title", "session_title"}),
    "session.ended": frozenset({"state"}),
    "node.created": _NODE_METADATA_FIELDS | _NODE_STRUCTURE_FIELDS,
    "task.created": _NODE_METADATA_FIELDS | _NODE_STRUCTURE_FIELDS | frozenset({"supersedes"}),
    "node.started": _NODE_METADATA_FIELDS | _NODE_STRUCTURE_FIELDS,
    "node.finished": _NODE_METADATA_FIELDS | _NODE_STRUCTURE_FIELDS,
    "task.updated": _NODE_METADATA_FIELDS | _NODE_STRUCTURE_FIELDS | frozenset({"supersedes"}),
    "node.updated": _NODE_METADATA_FIELDS,
    "edge.created": frozenset({"target", "kind"}),
    "checkpoint": frozenset({"label"}),
}
_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version", "session_id", "cwd", "title", "created_at", "updated_at",
        "sequence", "status", "degraded", "root_node_id", "nodes", "edges", "checkpoints",
    }
)
_NODE_FIELDS = frozenset(
    {
        "id", "kind", "label", "description", "state", "sequence", "created_at",
        "started_at", "finished_at", "degraded", "role", "model", "effort", "superseded_by",
    }
)
_EDGE_FIELDS = frozenset({"id", "source", "target", "kind"})
_CHECKPOINT_FIELDS = frozenset({"sequence", "timestamp", "label"})


def _is_int(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _valid_snapshot(snapshot: object, session_id: str) -> bool:
    """Validate the persisted presentation schema before returning cached data."""
    if not isinstance(snapshot, dict) or not set(snapshot).issubset(_SNAPSHOT_FIELDS):
        return False
    if snapshot.get("schema_version") != SCHEMA_VERSION or snapshot.get("session_id") != session_id:
        return False
    if not all(isinstance(snapshot.get(key), str) for key in ("cwd", "created_at", "updated_at")):
        return False
    if "title" in snapshot and not isinstance(snapshot["title"], str):
        return False
    if not _is_int(snapshot.get("sequence")) or snapshot.get("status") not in NODE_STATES:
        return False
    if not isinstance(snapshot.get("degraded"), bool):
        return False
    try:
        root_node_id = validate_identifier(snapshot.get("root_node_id"), name="root node identifier")
    except ValueError:
        return False
    nodes = snapshot.get("nodes")
    edges = snapshot.get("edges")
    checkpoints = snapshot.get("checkpoints")
    if not isinstance(nodes, dict) or root_node_id not in nodes or not isinstance(edges, dict) or not isinstance(checkpoints, list):
        return False
    for node_id, node in nodes.items():
        try:
            safe_node_id = validate_identifier(node_id, name="node identifier")
        except ValueError:
            return False
        if not isinstance(node, dict) or not set(node).issubset(_NODE_FIELDS):
            return False
        if node.get("id") != safe_node_id or node.get("kind") not in NODE_KINDS or node.get("state") not in NODE_STATES:
            return False
        if not isinstance(node.get("label"), str) or not _is_int(node.get("sequence")) or not isinstance(node.get("created_at"), str):
            return False
        for key in ("description", "started_at", "finished_at", "role", "model", "effort"):
            if key in node and not isinstance(node[key], str):
                return False
        if "degraded" in node and not isinstance(node["degraded"], bool):
            return False
        if "superseded_by" in node:
            try:
                validate_identifier(node["superseded_by"], name="superseding node identifier")
            except ValueError:
                return False
    for edge_id, edge in edges.items():
        if not isinstance(edge_id, str) or not isinstance(edge, dict) or set(edge) != _EDGE_FIELDS:
            return False
        if edge.get("id") != edge_id or edge.get("kind") not in EDGE_KINDS:
            return False
        try:
            validate_identifier(edge.get("source"), name="edge source")
            validate_identifier(edge.get("target"), name="edge target")
        except ValueError:
            return False
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, dict) or set(checkpoint) != _CHECKPOINT_FIELDS:
            return False
        if not _is_int(checkpoint.get("sequence"), minimum=1):
            return False
        if not isinstance(checkpoint.get("timestamp"), str) or not isinstance(checkpoint.get("label"), str):
            return False
    return True


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_cwd(value: object) -> str:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        return ""
    return str(Path(value).expanduser().resolve(strict=False))


def _safe_payload(event_type: str, payload: dict[str, object]) -> dict[str, object]:
    """Copy only reducer-supported, scalar lifecycle fields into private state."""
    for key in _TEXT_FIELDS:
        if key in payload and not isinstance(payload[key], str):
            raise ValueError("invalid event text field")
    for key in ("role", "model", "effort"):
        if key in payload and not isinstance(payload[key], str):
            raise ValueError("invalid event metadata field")

    allowed = _PAYLOAD_FIELDS.get(event_type, frozenset())
    safe_payload = {key: payload[key] for key in allowed if key in payload}
    for key in ("kind", "state", "parent_id", "parent_edge_kind", "target", "superseded_by", "supersedes"):
        if key in safe_payload and not isinstance(safe_payload[key], str):
            raise ValueError("invalid event structural field")
    if "dependencies" in safe_payload:
        dependencies = safe_payload["dependencies"]
        if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
            raise ValueError("invalid event structural field")

    for key in ("label", "title", "session_title", "role", "model", "effort"):
        if key in safe_payload:
            safe_payload[key] = sanitize_label(safe_payload[key])
    if "description" in safe_payload:
        safe_payload["description"] = sanitize_label(safe_payload["description"], limit=160)
    if event_type == "session.started":
        safe_payload["cwd"] = _canonical_cwd(safe_payload.get("cwd"))
    return safe_payload


class StateStore:
    """Store lifecycle events with private permissions and bounded locking."""

    def __init__(self, root: Path | None = None, lock_timeout: float = 0.2):
        if lock_timeout < 0:
            raise ValueError("lock timeout must not be negative")
        if root is None:
            state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            root = state_home / "claudex5-engineering-harness" / "runs"
        self.root = Path(root).expanduser().absolute()
        self._managed_path_boundary = (
            self.root.parents[1] if len(self.root.parents) > 1 else self.root.parent
        )
        self.lock_timeout = lock_timeout

    @staticmethod
    def _reject_symlink(path: Path) -> None:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return
        if stat.S_ISLNK(mode):
            raise ValueError("managed state path must not contain a symbolic link")

    def _reject_symlink_components(self, path: Path) -> None:
        """Reject every component inside the caller-managed state boundary."""
        absolute = path.absolute()
        try:
            relative = absolute.relative_to(self._managed_path_boundary)
        except ValueError as error:
            raise ValueError("managed state path escaped its boundary") from error
        current = self._managed_path_boundary
        self._reject_symlink(current)
        for part in relative.parts:
            current /= part
            self._reject_symlink(current)

    def _ensure_root(self) -> None:
        self._reject_symlink_components(self.root)
        if not self.root.exists():
            nearest = self.root.parent
            while not nearest.exists() and nearest != nearest.parent:
                nearest = nearest.parent
            self._reject_symlink(nearest)
        self._reject_symlink(self.root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._reject_symlink_components(self.root)
        os.chmod(self.root, 0o700)

    def _run_dir(self, session_id: object, *, create: bool) -> Path:
        safe_session = validate_identifier(session_id, name="session identifier")
        self._ensure_root()
        run_dir = self.root / safe_session
        self._reject_symlink(run_dir)
        if create:
            run_dir.mkdir(mode=0o700, exist_ok=True)
            self._reject_symlink(run_dir)
            os.chmod(run_dir, 0o700)
        return run_dir

    @staticmethod
    def _open_private(path: Path, flags: int) -> int:
        if path.is_symlink():
            raise ValueError("managed state file must not be a symbolic link")
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags | nofollow, 0o600)
        os.fchmod(descriptor, 0o600)
        return descriptor

    def _lock(self, run_dir: Path):
        lock_path = run_dir / ".lock"
        descriptor = self._open_private(lock_path, os.O_CREAT | os.O_RDWR)
        stream = os.fdopen(descriptor, "r+", encoding="utf-8")
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return stream
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    stream.close()
                    raise
                if time.monotonic() >= deadline:
                    stream.close()
                    raise TimeoutError("live graph state lock timed out") from None
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))

    def _write_snapshot(self, run_dir: Path, snapshot: dict[str, object]) -> None:
        destination = run_dir / "snapshot.json"
        self._reject_symlink(destination)
        temporary = run_dir / f".snapshot.{os.getpid()}.{uuid4().hex}.tmp"
        descriptor = self._open_private(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(snapshot, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(run_dir, directory_flags)
            try:
                os.fsync(directory_fd)
            except OSError as error:
                unsupported = {errno.EBADF, errno.EINVAL}
                if hasattr(errno, "ENOTSUP"):
                    unsupported.add(errno.ENOTSUP)
                if error.errno not in unsupported:
                    raise
            finally:
                os.close(directory_fd)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _read_json(path: Path) -> dict[str, object] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeError):
            return None
        return value if isinstance(value, dict) else None

    def _event_log_sequence(self, run_dir: Path, session_id: str) -> int | None:
        """Return the greatest structurally valid durable event sequence."""
        events_path = run_dir / "events.jsonl"
        self._reject_symlink(events_path)
        try:
            lines = events_path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError, UnicodeError):
            return None
        greatest: int | None = None
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            sequence = event.get("sequence")
            if (
                event.get("schema_version") == SCHEMA_VERSION
                and event.get("session_id") == session_id
                and _is_int(sequence, minimum=1)
            ):
                greatest = max(greatest or 0, sequence)
        return greatest

    def _cached_is_current(
        self, snapshot: dict[str, object] | None, run_dir: Path, session_id: str
    ) -> bool:
        if not _valid_snapshot(snapshot, session_id):
            return False
        log_sequence = self._event_log_sequence(run_dir, session_id)
        return log_sequence is None or int(snapshot["sequence"]) >= log_sequence

    def _recover(self, run_dir: Path, session_id: str) -> dict[str, object] | None:
        events_path = run_dir / "events.jsonl"
        self._reject_symlink(events_path)
        try:
            lines = events_path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError, UnicodeError):
            return None
        valid_events: list[dict[str, object]] = []
        degraded = False
        for index, line in enumerate(lines):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                if index != len(lines) - 1:
                    degraded = True
                continue
            valid_events.append(value)
        if not valid_events:
            return None
        cwd = ""
        for event in valid_events:
            payload = event.get("payload")
            if event.get("event_type") == "session.started" and isinstance(payload, dict):
                cwd = _canonical_cwd(payload.get("cwd"))
                break
        snapshot: dict[str, object] = new_snapshot(
            session_id,
            cwd,
            str(valid_events[0].get("timestamp", _utc_now())),
        )
        for event in valid_events:
            try:
                reduce_event(snapshot, event)
            except (TypeError, ValueError, KeyError):
                degraded = True
        if degraded:
            snapshot["degraded"] = True
        return snapshot

    def _load_unlocked(self, run_dir: Path, session_id: str) -> dict[str, object] | None:
        snapshot_path = run_dir / "snapshot.json"
        self._reject_symlink(snapshot_path)
        snapshot = self._read_json(snapshot_path)
        if self._cached_is_current(snapshot, run_dir, session_id):
            return snapshot
        return self._recover(run_dir, session_id)

    def append(
        self,
        session_id: str,
        event_type: str,
        node_id: str,
        payload: dict[str, object] | None,
        source: str = "explicit",
    ) -> dict[str, object]:
        """Validate, sequence, persist, and reduce a caller event."""
        session_id = validate_identifier(session_id, name="session identifier")
        node_id = validate_identifier(node_id, name="node identifier")
        source = validate_identifier(source, name="event source")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("event payload must be an object")
        safe_payload = _safe_payload(event_type, payload)
        run_dir = self._run_dir(session_id, create=True)
        lock_stream = self._lock(run_dir)
        try:
            snapshot = self._load_unlocked(run_dir, session_id)
            timestamp = _utc_now()
            if snapshot is None:
                snapshot = new_snapshot(session_id, str(safe_payload.get("cwd", "")), timestamp)
            sequence = int(snapshot.get("sequence", 0)) + 1
            event: dict[str, object] = {
                "schema_version": SCHEMA_VERSION,
                "event_id": str(uuid4()),
                "session_id": session_id,
                "sequence": sequence,
                "timestamp": timestamp,
                "event_type": event_type,
                "source": source,
                "node_id": node_id,
                "payload": safe_payload,
            }
            next_snapshot = reduce_event(copy.deepcopy(snapshot), event)
            events_path = run_dir / "events.jsonl"
            descriptor = self._open_private(events_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._write_snapshot(run_dir, next_snapshot)
            return event
        finally:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
            lock_stream.close()

    def load(self, session_id: str) -> dict[str, object] | None:
        session_id = validate_identifier(session_id, name="session identifier")
        run_dir = self._run_dir(session_id, create=False)
        if not run_dir.exists():
            return None
        self._reject_symlink(run_dir)
        snapshot_path = run_dir / "snapshot.json"
        self._reject_symlink(snapshot_path)
        cached = self._read_json(snapshot_path)
        if self._cached_is_current(cached, run_dir, session_id):
            return cached
        lock_stream = self._lock(run_dir)
        try:
            cached = self._read_json(snapshot_path)
            if self._cached_is_current(cached, run_dir, session_id):
                return cached
            snapshot = self._recover(run_dir, session_id)
            if snapshot is not None and _valid_snapshot(snapshot, session_id):
                self._write_snapshot(run_dir, snapshot)
                return snapshot
            return None
        finally:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
            lock_stream.close()

    def _snapshots_unordered(self, cwd: Path | str | None = None) -> list[dict[str, object]]:
        self._ensure_root()
        wanted_cwd = _canonical_cwd(cwd) if cwd is not None else None
        snapshots: list[dict[str, object]] = []
        for candidate in self.root.iterdir():
            self._reject_symlink(candidate)
            if not candidate.is_dir():
                continue
            try:
                session_id = validate_identifier(candidate.name, name="session identifier")
            except ValueError:
                continue
            snapshot = self.load(session_id)
            if snapshot is None:
                continue
            if wanted_cwd is not None and _canonical_cwd(snapshot.get("cwd")) != wanted_cwd:
                continue
            snapshots.append(snapshot)
        return snapshots

    def snapshots(self, cwd: Path | str | None = None) -> list[dict[str, object]]:
        """Return current session snapshots in stable running-first order."""
        snapshots = self._snapshots_unordered(cwd)
        snapshots.sort(key=lambda snapshot: str(snapshot.get("session_id", "")), reverse=True)
        snapshots.sort(key=lambda snapshot: str(snapshot.get("updated_at", "")), reverse=True)
        snapshots.sort(key=lambda snapshot: snapshot.get("status") != "running")
        return snapshots

    def latest(self, cwd: Path | str | None = None) -> dict[str, object] | None:
        snapshots = self.snapshots(cwd)
        return snapshots[0] if snapshots else None

    def _remove_run(self, candidate: Path) -> str:
        self._reject_symlink(candidate)
        if candidate.parent != self.root or not candidate.is_dir():
            raise ValueError("run path escaped state root")
        session_id = validate_identifier(candidate.name, name="session identifier")
        if candidate.resolve(strict=True).parent != self.root.resolve(strict=True):
            raise ValueError("run path escaped state root")
        shutil.rmtree(candidate)
        return session_id

    def cleanup(self, max_age_days: float = 7) -> list[str]:
        if max_age_days < 0:
            raise ValueError("maximum age must not be negative")
        self._ensure_root()
        cutoff = time.time() - max_age_days * 86400
        removed: list[str] = []
        for candidate in sorted(self.root.iterdir(), key=lambda path: path.name):
            self._reject_symlink(candidate)
            if not candidate.is_dir():
                continue
            validate_identifier(candidate.name, name="session identifier")
            event_log = candidate / "events.jsonl"
            snapshot_path = candidate / "snapshot.json"
            self._reject_symlink(event_log)
            self._reject_symlink(snapshot_path)
            timestamps = [
                path.stat().st_mtime
                for path in (event_log, snapshot_path)
                if path.exists()
            ]
            if max(timestamps, default=candidate.stat().st_mtime) >= cutoff:
                continue
            lock_stream = self._lock(candidate)
            try:
                timestamps = [
                    path.stat().st_mtime
                    for path in (event_log, snapshot_path)
                    if path.exists()
                ]
                if max(timestamps, default=candidate.stat().st_mtime) >= cutoff:
                    continue
                snapshot = self._load_unlocked(candidate, candidate.name)
                if snapshot is not None and snapshot.get("status") == "running":
                    continue
                removed.append(self._remove_run(candidate))
            finally:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
                lock_stream.close()
        return removed

    def clear_all(self) -> list[str]:
        self._ensure_root()
        removed: list[str] = []
        for candidate in sorted(self.root.iterdir(), key=lambda path: path.name):
            self._reject_symlink(candidate)
            if candidate.is_dir():
                removed.append(self._remove_run(candidate))
            elif candidate.name.startswith(".snapshot."):
                candidate.unlink()
        return removed
