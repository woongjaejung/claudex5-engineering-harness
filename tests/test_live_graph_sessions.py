from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import unittest

from scripts.live_graph.sessions import (
    SessionSelection,
    build_bundle,
    bundle_revision,
    catalog,
    group_snapshots,
)


def snapshot(
    session_id: str,
    cwd: str,
    status: str,
    updated_at: str,
    *,
    sequence: int = 1,
    title: str | None = None,
    nodes: dict[str, dict[str, object]] | None = None,
    edges: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": session_id,
        "cwd": cwd,
        "title": title or session_id,
        "created_at": "2026-08-14T00:00:00Z",
        "updated_at": updated_at,
        "sequence": sequence,
        "status": status,
        "nodes": nodes or {f"session:{session_id}": {"id": f"session:{session_id}"}},
        "edges": edges or {},
    }


class MemoryStore:
    def __init__(self, snapshots: list[dict[str, object]]):
        self._snapshots = snapshots
        self.calls = 0

    def snapshots(self) -> list[dict[str, object]]:
        self.calls += 1
        return list(self._snapshots)


class SessionSelectionTests(unittest.TestCase):
    def test_selection_is_immutable_and_rejects_path_like_ids(self) -> None:
        selection = SessionSelection.one("session-1")

        self.assertEqual(selection.mode, "session")
        self.assertEqual(selection.session_id, "session-1")
        self.assertEqual(SessionSelection.all(), SessionSelection("all", None))
        with self.assertRaises(ValueError):
            SessionSelection.one("../escape")
        with self.assertRaises(FrozenInstanceError):
            selection.mode = "all"  # type: ignore[misc]


class SessionQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_one = "/workspace/alpha"
        self.project_two = "/other/alpha"
        self.session_a = snapshot("session-a", self.project_one, "running", "2026-08-14T03:00:00Z", title="Build")
        self.session_b = snapshot("session-b", self.project_one, "passed", "2026-08-14T02:00:00Z", title="Earlier")
        self.session_c = snapshot("session-c", self.project_one, "failed", "2026-08-14T04:00:00Z", title="Newest")
        self.session_d = snapshot("session-d", self.project_two, "running", "2026-08-14T01:00:00Z")

    def test_catalog_retains_complete_ids_raw_timestamps_and_safe_display_fields(self) -> None:
        rows = catalog([self.session_b, self.session_a])

        self.assertEqual([row["session_id"] for row in rows], ["session-a", "session-b"])
        self.assertEqual(rows[0]["title"], "Build")
        self.assertEqual(rows[0]["cwd"], self.project_one)
        self.assertEqual(rows[0]["created_at"], "2026-08-14T00:00:00Z")
        self.assertEqual(rows[0]["updated_at"], "2026-08-14T03:00:00Z")
        self.assertEqual(rows[0]["status"], "running")
        self.assertEqual(rows[0]["sequence"], 1)
        self.assertNotIn("age", rows[0])

    def test_grouping_uses_full_canonical_paths_and_limits_completed_per_project(self) -> None:
        groups = group_snapshots(
            [self.session_b, self.session_d, self.session_c, self.session_a], completed_limit=1
        )

        self.assertEqual([group["cwd"] for group in groups], [self.project_two, self.project_one])
        first, second = groups
        self.assertEqual([item["session_id"] for item in first["running"]], ["session-d"])
        self.assertEqual(first["completed"], [])
        self.assertEqual([item["session_id"] for item in second["running"]], ["session-a"])
        self.assertEqual([item["session_id"] for item in second["completed"]], ["session-c"])

    def test_grouping_keeps_all_completed_when_no_limit_is_requested(self) -> None:
        groups = group_snapshots([self.session_b, self.session_c, self.session_a], completed_limit=None)

        self.assertEqual(
            [item["session_id"] for item in groups[0]["completed"]], ["session-c", "session-b"]
        )

    def test_focused_bundle_catalogs_every_session_but_projects_only_selected_session(self) -> None:
        store = MemoryStore([self.session_b, self.session_a])

        bundle = build_bundle(store, SessionSelection.one("session-a"))

        self.assertEqual(store.calls, 1)
        self.assertEqual(bundle["selection"], {"mode": "session", "session_id": "session-a"})
        self.assertEqual([row["session_id"] for row in bundle["catalog"]], ["session-a", "session-b"])
        self.assertEqual(
            [item["session_id"] for group in bundle["projects"] for item in group["running"]],
            ["session-a"],
        )
        self.assertEqual(
            [item["session_id"] for group in bundle["projects"] for item in group["completed"]], [],
        )

    def test_focused_completed_session_is_not_hidden_by_completed_limit(self) -> None:
        bundle = build_bundle(
            MemoryStore([self.session_b]), SessionSelection.one("session-b"), completed_limit=0
        )

        self.assertEqual(
            [item["session_id"] for group in bundle["projects"] for item in group["completed"]],
            ["session-b"],
        )

    def test_bundle_projection_removes_superseded_nodes_and_their_edges_without_mutating_source(self) -> None:
        nodes = {
            "session:session-a": {"id": "session:session-a"},
            "task:compat": {"id": "task:compat", "superseded_by": "task:stable"},
            "task:stable": {"id": "task:stable"},
        }
        edges = {
            "old": {"id": "old", "source": "session:session-a", "target": "task:compat"},
            "new": {"id": "new", "source": "session:session-a", "target": "task:stable"},
        }
        source = snapshot(
            "session-a", self.project_one, "running", "2026-08-14T03:00:00Z", nodes=nodes, edges=edges
        )
        source.update(
            {"_event_log_size": 123, "_event_log_mtime_ns": 456, "_event_log_sequence": 7}
        )
        before = copy.deepcopy(source)

        bundle = build_bundle(MemoryStore([source]), SessionSelection.all())
        projected = bundle["projects"][0]["running"][0]

        self.assertNotIn("task:compat", projected["nodes"])
        self.assertNotIn("old", projected["edges"])
        self.assertIn("task:stable", projected["nodes"])
        self.assertIn("new", projected["edges"])
        self.assertNotIn("_event_log_size", projected)
        self.assertNotIn("_event_log_mtime_ns", projected)
        self.assertNotIn("_event_log_sequence", projected)
        self.assertEqual(source, before)

    def test_missing_selected_session_has_fixed_lookup_error(self) -> None:
        with self.assertRaisesRegex(LookupError, "^selected session is unavailable$"):
            build_bundle(MemoryStore([self.session_a]), SessionSelection.one("session-b"))

    def test_revision_changes_for_catalog_lifecycle_or_logical_selection_not_display_or_wall_clock(self) -> None:
        baseline = [self.session_a]
        display_changed = copy.deepcopy(baseline)
        display_changed[0]["title"] = "Changed display text"
        display_changed[0]["cwd"] = "/elsewhere"
        updated = copy.deepcopy(baseline)
        updated[0]["updated_at"] = "2026-08-14T03:00:01Z"

        self.assertEqual(bundle_revision(baseline), bundle_revision(display_changed))
        self.assertNotEqual(bundle_revision(baseline), bundle_revision(updated))
        all_bundle = build_bundle(MemoryStore(baseline), SessionSelection.all())
        focused_bundle = build_bundle(MemoryStore(baseline), SessionSelection.one("session-a"))
        self.assertNotEqual(all_bundle["revision"], focused_bundle["revision"])
        self.assertNotIn("age", repr(all_bundle))


if __name__ == "__main__":
    unittest.main()
