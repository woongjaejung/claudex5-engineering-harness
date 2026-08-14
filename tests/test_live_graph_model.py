from __future__ import annotations

import copy
import unittest

from scripts.live_graph.model import (
    ROLE_METADATA,
    new_snapshot,
    reduce_event,
    sanitize_label,
)


class SanitizeLabelTests(unittest.TestCase):
    def test_redacts_supported_secret_shapes(self) -> None:
        labels = (
            "Bearer " + "abcdefghijklmnopqrstuvwxyz012345",
            "sk-" + "proj-abcdefghijklmnopqrstuvwxyz0123456789",
            "sk-" + "ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
            "ghp" + "_abcdefghijklmnopqrstuvwxyz0123456789",
            "AKIA" + "IOSFODNN7EXAMPLE",
            "-----BEGIN " + "PRIVATE KEY-----",
            "https://alice:secret-password@example.test/path",
        )

        for label in labels:
            with self.subTest(label=label):
                self.assertEqual(sanitize_label(label), "[REDACTED]")

    def test_removes_controls_collapses_whitespace_and_clips(self) -> None:
        self.assertEqual(sanitize_label("  first\n\tsecond\x00 third  "), "first second third")
        self.assertEqual(sanitize_label("abcdefgh", limit=5), "abcde")


class SnapshotReductionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = new_snapshot("session-1", "/safe/project", "2026-08-13T00:00:00Z")

    @staticmethod
    def event(event_id: str, sequence: int, event_type: str, node_id: str, **payload: object) -> dict[str, object]:
        return {
            "schema_version": 1,
            "event_id": event_id,
            "session_id": "session-1",
            "sequence": sequence,
            "timestamp": f"2026-08-13T00:00:{sequence:02d}Z",
            "event_type": event_type,
            "source": "test",
            "node_id": node_id,
            "payload": payload,
        }

    def test_duplicate_start_is_idempotent_and_terminal_node_does_not_restart(self) -> None:
        started = self.event(
            "event-1",
            1,
            "node.started",
            "agent:abc123",
            kind="claude_agent",
            label="Research",
            role="harness-researcher",
        )
        reduce_event(self.snapshot, started)
        reduce_event(self.snapshot, {**started, "event_id": "event-2", "sequence": 2})
        self.assertEqual(len(self.snapshot["nodes"]), 2)  # session root plus agent
        self.assertEqual(self.snapshot["nodes"]["agent:abc123"]["state"], "running")

        reduce_event(
            self.snapshot,
            self.event("event-3", 3, "node.finished", "agent:abc123", state="passed"),
        )
        before = copy.deepcopy(self.snapshot["nodes"]["agent:abc123"])
        reduce_event(
            self.snapshot,
            self.event("event-4", 4, "node.started", "agent:abc123", kind="claude_agent"),
        )
        self.assertEqual(self.snapshot["nodes"]["agent:abc123"], before)

    def test_session_root_records_its_creation_timestamp(self) -> None:
        self.assertEqual(
            self.snapshot["nodes"]["session:session-1"]["created_at"],
            "2026-08-13T00:00:00Z",
        )

    def test_task_dependencies_create_stable_edges(self) -> None:
        reduce_event(
            self.snapshot,
            self.event(
                "event-1",
                1,
                "task.created",
                "task:build",
                title="Build",
                dependencies=["task:plan", "task:research"],
            ),
        )
        reduce_event(
            self.snapshot,
            self.event(
                "event-2",
                2,
                "task.created",
                "task:build",
                title="Build",
                dependencies=["task:plan", "task:research"],
            ),
        )

        edges = self.snapshot["edges"]
        self.assertEqual(len(edges), 3)  # root contains task, plus two dependency edges
        dependency_edges = [edge for edge in edges.values() if edge["kind"] == "depends_on"]
        self.assertEqual(
            dependency_edges,
            [
                {
                    "id": "task:build|depends_on|task:plan",
                    "source": "task:build",
                    "target": "task:plan",
                    "kind": "depends_on",
                },
                {
                    "id": "task:build|depends_on|task:research",
                    "source": "task:build",
                    "target": "task:research",
                    "kind": "depends_on",
                },
            ],
        )

    def test_started_wrapper_node_dependencies_create_stable_edges(self) -> None:
        started = self.event(
            "event-1",
            1,
            "node.started",
            "gate:test",
            kind="quality_gate",
            label="Tests",
            dependencies=["gate:lint"],
        )

        reduce_event(self.snapshot, started)
        reduce_event(self.snapshot, {**started, "event_id": "event-2", "sequence": 2})

        self.assertEqual(
            self.snapshot["edges"]["gate:test|depends_on|gate:lint"],
            {
                "id": "gate:test|depends_on|gate:lint",
                "source": "gate:test",
                "target": "gate:lint",
                "kind": "depends_on",
            },
        )
        self.assertEqual(
            sum(edge["kind"] == "depends_on" for edge in self.snapshot["edges"].values()),
            1,
        )

    def test_invalid_node_identifier_is_rejected(self) -> None:
        for node_id in ("", "../escape", "/absolute", "task\\escape", "task%2fescape", "bad\nnode", "x" * 129):
            with self.subTest(node_id=node_id):
                with self.assertRaises(ValueError):
                    reduce_event(
                        self.snapshot,
                        self.event("event-invalid", 1, "node.started", node_id, kind="task"),
                    )

    def test_finish_without_start_creates_degraded_terminal_node(self) -> None:
        reduce_event(
            self.snapshot,
            self.event(
                "event-1",
                1,
                "node.finished",
                "agent:late",
                kind="claude_agent",
                label="Late agent",
                state="failed",
            ),
        )

        node = self.snapshot["nodes"]["agent:late"]
        self.assertEqual(node["state"], "failed")
        self.assertTrue(node["degraded"])
        self.assertTrue(self.snapshot["degraded"])

    def test_node_metadata_and_lifecycle_timestamps_are_idempotent(self) -> None:
        reduce_event(self.snapshot, self.event(
            "created", 1, "task.created", "task:5",
            label="Docker smoke test", description="Verify startup and rollback",
        ))
        reduce_event(self.snapshot, self.event(
            "started", 2, "task.updated", "task:5", state="running",
        ))
        reduce_event(self.snapshot, self.event(
            "metadata", 3, "node.updated", "task:5",
            description="Verify image startup, health check, and rollback",
        ))
        reduce_event(self.snapshot, self.event(
            "finished", 4, "task.updated", "task:5", state="passed",
        ))
        reduce_event(self.snapshot, self.event(
            "duplicate", 5, "task.updated", "task:5", state="passed",
        ))

        node = self.snapshot["nodes"]["task:5"]
        self.assertEqual(node["created_at"], "2026-08-13T00:00:01Z")
        self.assertEqual(node["started_at"], "2026-08-13T00:00:02Z")
        self.assertEqual(node["finished_at"], "2026-08-13T00:00:04Z")
        self.assertEqual(node["description"], "Verify image startup, health check, and rollback")

    def test_session_title_and_running_update_set_metadata_and_first_start_timestamp(self) -> None:
        reduce_event(self.snapshot, self.event(
            "session-title", 1, "session.started", "session:session-1",
            title="  Dashboard\nrun  ",
        ))
        reduce_event(self.snapshot, self.event(
            "created", 2, "task.created", "task:6", label="Prepare",
        ))
        reduce_event(self.snapshot, self.event(
            "running", 3, "task.updated", "task:6", state="running", role="operator",
        ))
        reduce_event(self.snapshot, self.event(
            "running-again", 4, "task.updated", "task:6", state="running", role="reviewer",
        ))

        self.assertEqual(self.snapshot["title"], "Dashboard run")
        self.assertEqual(self.snapshot["nodes"]["task:6"]["started_at"], "2026-08-13T00:00:03Z")
        self.assertEqual(self.snapshot["nodes"]["task:6"]["role"], "reviewer")

    def test_invalid_supersession_identifiers_are_rejected(self) -> None:
        reduce_event(self.snapshot, self.event("created", 1, "task.created", "task:7", label="Task"))

        with self.assertRaises(ValueError):
            reduce_event(self.snapshot, self.event(
                "invalid-successor", 2, "node.updated", "task:7", superseded_by="../task:8",
            ))
        with self.assertRaises(ValueError):
            reduce_event(self.snapshot, self.event(
                "invalid-compatibility", 3, "task.created", "task:8", supersedes="toolu_123",
            ))

    def test_ambiguous_compatibility_tasks_are_not_reconciled(self) -> None:
        for sequence, node_id in ((1, "task:compat-first"), (2, "task:compat-second")):
            reduce_event(self.snapshot, self.event(
                f"compat-{sequence}", sequence, "task.created", node_id, label="Implement report",
            ))

        reduce_event(self.snapshot, self.event(
            "stable", 3, "task.created", "task:stable", label="Implement report",
        ))

        self.assertNotIn("superseded_by", self.snapshot["nodes"]["task:compat-first"])
        self.assertNotIn("superseded_by", self.snapshot["nodes"]["task:compat-second"])

    def test_unique_compatibility_task_is_superseded_by_stable_task(self) -> None:
        reduce_event(self.snapshot, self.event(
            "compat", 1, "task.created", "task:compat-tool-use-1",
            label="Implement report", dependencies=["task:research"],
        ))

        reduce_event(self.snapshot, self.event(
            "stable", 2, "task.created", "task:stable", label="Implement report",
        ))

        self.assertEqual(
            self.snapshot["nodes"]["task:compat-tool-use-1"]["superseded_by"], "task:stable",
        )
        self.assertIn("task:compat-tool-use-1", self.snapshot["nodes"])
        self.assertEqual(
            self.snapshot["edges"]["task:stable|depends_on|task:research"],
            {
                "id": "task:stable|depends_on|task:research",
                "source": "task:stable",
                "target": "task:research",
                "kind": "depends_on",
            },
        )

    def test_stable_first_task_update_reconciles_unique_compatibility_task(self) -> None:
        reduce_event(self.snapshot, self.event(
            "compat", 1, "task.created", "task:compat-tool-use-2",
            label="Run tests", dependencies=["task:build"],
        ))

        reduce_event(self.snapshot, self.event(
            "stable-update", 2, "task.updated", "task:tests", label="Run tests", state="running",
        ))

        self.assertEqual(
            self.snapshot["nodes"]["task:compat-tool-use-2"]["superseded_by"], "task:tests",
        )
        self.assertIn("task:tests|depends_on|task:build", self.snapshot["edges"])

    def test_explicit_compatibility_supersedes_bypasses_label_matching(self) -> None:
        reduce_event(self.snapshot, self.event(
            "compat-first", 1, "task.created", "task:compat-first", label="First",
        ))
        reduce_event(self.snapshot, self.event(
            "compat-second", 2, "task.created", "task:compat-second", label="Second",
        ))

        reduce_event(self.snapshot, self.event(
            "stable", 3, "task.created", "task:stable", label="Different", supersedes="task:compat-second",
        ))

        self.assertNotIn("superseded_by", self.snapshot["nodes"]["task:compat-first"])
        self.assertEqual(
            self.snapshot["nodes"]["task:compat-second"]["superseded_by"], "task:stable",
        )

    def test_current_harness_roles_have_model_and_effort_metadata(self) -> None:
        expected = {
            "harness-orchestrator": ("claude-fable-5", "high"),
            "harness-orchestrator-opus": ("claude-opus-5", "high"),
            "harness-researcher": ("claude-sonnet-5", "high"),
            "harness-implementer": ("claude-sonnet-5", "high"),
            "harness-implementer-opus": ("claude-opus-5", "high"),
            "harness-architecture-reviewer": ("claude-opus-5", "high"),
            "harness-code-reviewer": ("claude-opus-5", "high"),
            "harness-judge": ("claude-fable-5", "high"),
            "harness-judge-opus": ("claude-opus-5", "high"),
            "harness-sol-plan-review": ("gpt-5.6-sol", "high"),
            "harness-sol-research": ("gpt-5.6-sol", "high"),
            "harness-sol-review": ("gpt-5.6-sol", "high"),
            "harness-sol-adversarial-review": ("gpt-5.6-sol", "high"),
            "harness-luna-implementation": ("gpt-5.6-luna", "max"),
        }
        self.assertEqual(
            {role: (ROLE_METADATA[role]["model"], ROLE_METADATA[role]["effort"]) for role in expected},
            expected,
        )
        self.assertEqual(
            ROLE_METADATA["harness-spark-ui-iteration"],
            {"model": "gpt-5.3-codex-spark"},
        )


if __name__ == "__main__":
    unittest.main()
