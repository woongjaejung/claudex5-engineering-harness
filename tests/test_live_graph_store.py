from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from scripts.live_graph.store import StateStore


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "state" / "runs"
        self.store = StateStore(self.root)
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()

    def start(self, session_id: str = "session-1", cwd: Path | None = None) -> dict[str, object]:
        return self.store.append(
            session_id,
            "session.started",
            f"session:{session_id}",
            {"cwd": str(cwd or self.project)},
            source="test",
        )

    def test_creates_private_paths_and_monotonic_events(self) -> None:
        first = self.start()
        second = self.store.append(
            "session-1",
            "node.started",
            "agent:one",
            {"kind": "claude_agent", "label": "Research"},
            source="test",
        )

        run_dir = self.root / "session-1"
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(run_dir.stat().st_mode & 0o777, 0o700)
        for filename in ("events.jsonl", "snapshot.json", ".lock"):
            self.assertEqual((run_dir / filename).stat().st_mode & 0o777, 0o600)
        events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
        self.assertEqual([event["sequence"] for event in events], [1, 2])

    def test_recovers_from_event_log_and_tolerates_only_malformed_final_line(self) -> None:
        self.start()
        self.store.append(
            "session-1",
            "node.started",
            "agent:one",
            {"kind": "claude_agent", "label": "Research"},
        )
        run_dir = self.root / "session-1"
        (run_dir / "snapshot.json").unlink()
        with (run_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write('{"unfinished":')

        recovered = self.store.load("session-1")
        self.assertEqual(recovered["sequence"], 2)
        self.assertFalse(recovered["degraded"])
        self.assertIn("agent:one", recovered["nodes"])

    def test_earlier_corruption_marks_recovered_snapshot_degraded(self) -> None:
        self.start()
        run_dir = self.root / "session-1"
        with (run_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("not-json\n")
            stream.write(
                json.dumps(
                    {
                        "schema_version": 1,
                        "event_id": "later-event",
                        "session_id": "session-1",
                        "sequence": 2,
                        "timestamp": "2026-08-13T00:00:02Z",
                        "event_type": "checkpoint",
                        "source": "test",
                        "node_id": "session:session-1",
                        "payload": {"label": "later"},
                    }
                )
                + "\n"
            )
        (run_dir / "snapshot.json").unlink()

        recovered = self.store.load("session-1")
        self.assertTrue(recovered["degraded"])
        self.assertEqual(recovered["sequence"], 2)

    def test_recovery_waits_for_run_lock_before_rebuilding_snapshot(self) -> None:
        self.start()
        run_dir = self.root / "session-1"
        (run_dir / "snapshot.json").unlink()
        with (run_dir / ".lock").open("r+") as lock_stream:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            blocked_store = StateStore(self.root, lock_timeout=0.02)
            with self.assertRaises(TimeoutError):
                blocked_store.load("session-1")
        self.assertFalse((run_dir / "snapshot.json").exists())

    def test_latest_selects_newest_matching_canonical_project(self) -> None:
        other = Path(self.temporary.name) / "other"
        other.mkdir()
        self.start("older", self.project)
        time.sleep(0.01)
        self.start("other", other)
        time.sleep(0.01)
        self.start("newer", self.project / ".." / "project")

        self.assertEqual(self.store.latest()["session_id"], "newer")
        self.assertEqual(self.store.latest(self.project)["session_id"], "newer")
        self.assertIsNone(self.store.latest(Path(self.temporary.name) / "missing"))

    def test_snapshots_are_deterministic_and_path_filtered(self) -> None:
        other = Path(self.temporary.name) / "other"
        other.mkdir()
        self.start("terminal-old", self.project)
        self.store.append("terminal-old", "session.ended", "session:terminal-old", {"state": "passed"})
        self.start("running-old", self.project)
        self.start("terminal-new", other)
        self.store.append("terminal-new", "session.ended", "session:terminal-new", {"state": "passed"})
        self.start("running-new", self.project / ".")

        timestamps = {
            "terminal-old": "2026-08-10T00:00:00Z",
            "running-old": "2026-08-11T00:00:00Z",
            "terminal-new": "2026-08-13T00:00:00Z",
            "running-new": "2026-08-12T00:00:00Z",
        }
        for session_id, timestamp in timestamps.items():
            snapshot_path = self.root / session_id / "snapshot.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["updated_at"] = timestamp
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        (self.root / "not a session").mkdir()

        self.assertEqual(
            [snapshot["session_id"] for snapshot in self.store.snapshots()],
            ["running-new", "running-old", "terminal-new", "terminal-old"],
        )
        self.assertEqual(
            [snapshot["session_id"] for snapshot in self.store.snapshots(self.project / ".." / "project")],
            ["running-new", "running-old", "terminal-old"],
        )
        self.assertEqual(self.store.latest()["session_id"], "running-new")

    def test_snapshots_preserve_latest_tie_breaker_by_session_id(self) -> None:
        self.start("running-a")
        self.start("running-z")
        for session_id in ("running-a", "running-z"):
            snapshot_path = self.root / session_id / "snapshot.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["updated_at"] = "2026-08-14T00:00:00Z"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

        self.assertEqual(
            [snapshot["session_id"] for snapshot in self.store.snapshots()],
            ["running-z", "running-a"],
        )
        self.assertEqual(self.store.latest()["session_id"], "running-z")

    def test_cleanup_removes_only_runs_older_than_boundary(self) -> None:
        self.start("old")
        self.start("fresh")
        self.store.append(
            "old",
            "session.ended",
            "session:old",
            {"state": "passed"},
        )
        old_dir = self.root / "old"
        nine_days_ago = time.time() - 9 * 86400
        for path in old_dir.iterdir():
            os.utime(path, (nine_days_ago, nine_days_ago))
        os.utime(old_dir, (nine_days_ago, nine_days_ago))

        removed = self.store.cleanup(max_age_days=7)
        self.assertEqual(removed, ["old"])
        self.assertFalse(old_dir.exists())
        self.assertTrue((self.root / "fresh").exists())

    def test_cleanup_preserves_active_run_even_when_its_files_are_old(self) -> None:
        self.start("active")
        active_dir = self.root / "active"
        nine_days_ago = time.time() - 9 * 86400
        for path in active_dir.iterdir():
            os.utime(path, (nine_days_ago, nine_days_ago))
        os.utime(active_dir, (nine_days_ago, nine_days_ago))

        self.assertEqual(self.store.cleanup(max_age_days=7), [])
        self.assertTrue(active_dir.exists())

    def test_cleanup_does_not_delete_a_locked_terminal_run(self) -> None:
        self.start("locked")
        self.store.append(
            "locked",
            "session.ended",
            "session:locked",
            {"state": "passed"},
        )
        run_dir = self.root / "locked"
        nine_days_ago = time.time() - 9 * 86400
        for path in run_dir.iterdir():
            os.utime(path, (nine_days_ago, nine_days_ago))
        os.utime(run_dir, (nine_days_ago, nine_days_ago))

        with (run_dir / ".lock").open("r+") as lock_stream:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            blocked_store = StateStore(self.root, lock_timeout=0.02)
            with self.assertRaises(TimeoutError):
                blocked_store.cleanup(max_age_days=7)
        self.assertTrue(run_dir.exists())

    def test_rejects_untrusted_session_and_node_identifiers_before_path_construction(self) -> None:
        bad_values = ("", "..", "../escape", "/absolute", "slash/value", "back\\value", "encoded%2Fvalue", "bad\nvalue", "x" * 129)
        for value in bad_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.store.append(value, "checkpoint", "node:safe", {})
                with self.assertRaises(ValueError):
                    self.store.append("safe", "checkpoint", value, {})
        self.assertFalse((Path(self.temporary.name) / "escape").exists())

    def test_rejects_symlink_in_managed_state_path(self) -> None:
        real = Path(self.temporary.name) / "real"
        (real / "inner").mkdir(parents=True)
        linked_parent = Path(self.temporary.name) / "linked"
        linked_parent.symlink_to(real, target_is_directory=True)
        store = StateStore(linked_parent / "inner" / "runs")

        with self.assertRaises(ValueError):
            store.append(
                "session-1",
                "session.started",
                "session:session-1",
                {"cwd": str(self.project)},
            )

    def test_lock_timeout_drops_without_modifying_event_log(self) -> None:
        self.start()
        run_dir = self.root / "session-1"
        before = (run_dir / "events.jsonl").read_bytes()
        with (run_dir / ".lock").open("r+") as lock_stream:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            blocked_store = StateStore(self.root, lock_timeout=0.02)
            with self.assertRaises(TimeoutError):
                blocked_store.append("session-1", "checkpoint", "session:session-1", {})
        self.assertEqual((run_dir / "events.jsonl").read_bytes(), before)

    def test_descriptions_are_bounded_and_secrets_are_redacted(self) -> None:
        long_description = "x" * 200
        event = self.store.append(
            "session-1", "task.created", "task:description",
            {"label": "Description", "description": long_description},
        )
        redacted = self.store.append(
            "session-1", "node.updated", "task:description",
            {"description": "Bearer " + "abcdefghijklmnopqrstuvwxyz012345"},
        )

        self.assertEqual(event["payload"]["description"], "x" * 160)
        self.assertEqual(redacted["payload"]["description"], "[REDACTED]")
        persisted = (self.root / "session-1" / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"description":"[REDACTED]"', persisted)

    def test_non_string_text_fields_are_rejected_before_persistence(self) -> None:
        self.start()
        events_path = self.root / "session-1" / "events.jsonl"
        before = events_path.read_bytes()

        for key in ("label", "title", "session_title", "description"):
            for value in ({"nested": "value"}, ["nested", "value"]):
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(ValueError, "^invalid event text field$"):
                        self.store.append("session-1", "node.updated", "task:one", {key: value})

        self.assertEqual(events_path.read_bytes(), before)
        private_state = "".join(
            path.read_text(encoding="utf-8")
            for path in (self.root / "session-1").iterdir()
            if path.is_file() and path.name != ".lock"
        )
        self.assertNotIn("nested", private_state)

    def test_drops_unknown_and_nested_fields_while_preserving_task_structure(self) -> None:
        forbidden_values = (
            "prompt-secret",
            "code-secret",
            "command-secret",
            "tool-output-secret",
            "response-secret",
            "/private/transcript-secret.jsonl",
            "/private/output-secret.txt",
            "environment-secret",
            "nested-secret",
        )
        event = self.store.append(
            "session-1",
            "task.created",
            "task:build",
            {
                "kind": "task",
                "label": "Build image",
                "description": "Safe description",
                "parent_id": "session:session-1",
                "parent_edge_kind": "contains",
                "dependencies": ["task:plan"],
                "prompt": forbidden_values[0],
                "code": forbidden_values[1],
                "command": forbidden_values[2],
                "tool_output": {"value": forbidden_values[3]},
                "response": forbidden_values[4],
                "transcript_path": forbidden_values[5],
                "output_path": forbidden_values[6],
                "environment": {"TOKEN": forbidden_values[7]},
                "arbitrary": {"nested": forbidden_values[8]},
            },
        )

        self.assertEqual(
            event["payload"],
            {
                "kind": "task",
                "label": "Build image",
                "description": "Safe description",
                "parent_id": "session:session-1",
                "parent_edge_kind": "contains",
                "dependencies": ["task:plan"],
            },
        )
        snapshot = self.store.load("session-1")
        self.assertEqual(snapshot["nodes"]["task:build"]["description"], "Safe description")
        self.assertIn("task:build|depends_on|task:plan", snapshot["edges"])
        persisted = b"\n".join(path.read_bytes() for path in self.root.rglob("*") if path.is_file())
        for value in forbidden_values:
            with self.subTest(value=value):
                self.assertNotIn(value.encode(), persisted)

    def test_non_string_node_metadata_is_rejected_before_persistence(self) -> None:
        self.start()
        events_path = self.root / "session-1" / "events.jsonl"
        before = events_path.read_bytes()

        for key in ("role", "model", "effort"):
            for value in ({"private": "nested-secret"}, ["nested-secret"]):
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(ValueError, "^invalid event metadata field$"):
                        self.store.append("session-1", "node.updated", "task:one", {key: value})

        self.assertEqual(events_path.read_bytes(), before)

    def test_clear_all_removes_runs_but_keeps_private_root(self) -> None:
        self.start("one")
        self.start("two")

        self.assertEqual(self.store.clear_all(), ["one", "two"])
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
