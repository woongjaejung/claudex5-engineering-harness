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

    def test_current_harness_roles_have_model_and_effort_metadata(self) -> None:
        expected = {
            "harness-orchestrator": ("claude-fable-5", "high"),
            "harness-orchestrator-opus": ("claude-opus-5", "high"),
            "harness-researcher": ("claude-sonnet-5", "high"),
            "harness-implementer": ("claude-sonnet-5", "high"),
            "harness-implementer-opus": ("claude-opus-5", "high"),
            "harness-architecture-reviewer": ("claude-opus-5", "high"),
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
