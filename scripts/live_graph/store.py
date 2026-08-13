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

from .model import SCHEMA_VERSION, new_snapshot, reduce_event, validate_identifier


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_cwd(value: object) -> str:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        return ""
    return str(Path(value).expanduser().resolve(strict=False))


class StateStore:
    """Store lifecycle events with private permissions and bounded locking."""

    def __init__(self, root: Path | None = None, lock_timeout: float = 0.2):
        if lock_timeout < 0:
            raise ValueError("lock timeout must not be negative")
        if root is None:
            state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            root = state_home / "claudex5-engineering-harness" / "runs"
        self.root = Path(root).expanduser().absolute()
        self.lock_timeout = lock_timeout

    @staticmethod
    def _reject_symlink(path: Path) -> None:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return
        if stat.S_ISLNK(mode):
            raise ValueError("managed state path must not contain a symbolic link")

    def _ensure_root(self) -> None:
        if not self.root.exists():
            nearest = self.root.parent
            while not nearest.exists() and nearest != nearest.parent:
                nearest = nearest.parent
            self._reject_symlink(nearest)
        self._reject_symlink(self.root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._reject_symlink(self.root)
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

    def _recover(self, run_dir: Path, session_id: str) -> dict[str, object] | None:
        events_path = run_dir / "events.jsonl"
        self._reject_symlink(events_path)
        try:
            lines = events_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
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
        if (
            snapshot is not None
            and snapshot.get("schema_version") == SCHEMA_VERSION
            and snapshot.get("session_id") == session_id
        ):
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
        safe_payload = copy.deepcopy(payload)
        if event_type == "session.started":
            safe_payload["cwd"] = _canonical_cwd(safe_payload.get("cwd"))
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
        snapshot = self._load_unlocked(run_dir, session_id)
        if snapshot is not None and not (run_dir / "snapshot.json").exists():
            self._write_snapshot(run_dir, snapshot)
        return snapshot

    def latest(self, cwd: Path | str | None = None) -> dict[str, object] | None:
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
        if not snapshots:
            return None
        active = [snapshot for snapshot in snapshots if snapshot.get("status") == "running"]
        candidates = active or snapshots
        return max(candidates, key=lambda snapshot: (str(snapshot.get("updated_at", "")), str(snapshot.get("session_id", ""))))

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
            if candidate.is_dir() and candidate.stat().st_mtime < cutoff:
                removed.append(self._remove_run(candidate))
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
