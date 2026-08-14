from __future__ import annotations

from datetime import datetime, timezone
import unittest

from scripts.live_graph.terminal import (
    format_duration,
    render_all_sessions,
    render_session_catalog,
    render_snapshot,
)


def sample_snapshot() -> dict:
    return {
        "session_id": "demo-session",
        "cwd": "/tmp/example-project",
        "status": "running",
        "degraded": False,
        "sequence": 8,
        "nodes": {
            "session:demo-session": {
                "id": "session:demo-session",
                "kind": "session",
                "label": "Claudex5 run",
                "state": "running",
                "sequence": 1,
            },
            "task:plan": {
                "id": "task:plan",
                "kind": "task",
                "label": "Plan feature",
                "state": "passed",
                "sequence": 2,
            },
            "agent:impl": {
                "id": "agent:impl",
                "kind": "claude_agent",
                "label": "Implement feature",
                "state": "running",
                "role": "harness-implementer",
                "model": "claude-sonnet-5",
                "effort": "high",
                "sequence": 3,
            },
            "review:sol": {
                "id": "review:sol",
                "kind": "review",
                "label": "Independent review",
                "state": "waiting",
                "role": "harness_sol_review",
                "model": "gpt-5.6-sol",
                "effort": "high",
                "sequence": 4,
            },
            "gate:test": {
                "id": "gate:test",
                "kind": "quality_gate",
                "label": "Tests",
                "state": "failed",
                "sequence": 5,
            },
            "gate:block": {
                "id": "gate:block",
                "kind": "quality_gate",
                "label": "Deploy",
                "state": "blocked",
                "sequence": 6,
            },
            "task:skip": {
                "id": "task:skip",
                "kind": "task",
                "label": "Optional benchmark",
                "state": "skipped",
                "sequence": 7,
            },
            "task:interrupt": {
                "id": "task:interrupt",
                "kind": "task",
                "label": "Cancelled work",
                "state": "interrupted",
                "sequence": 8,
            },
        },
        "edges": {
            "plan-impl": {
                "id": "plan-impl",
                "source": "task:plan",
                "target": "agent:impl",
                "kind": "dispatches",
            },
            "impl-review": {
                "id": "impl-review",
                "source": "agent:impl",
                "target": "review:sol",
                "kind": "reviews",
            },
            "review-test": {
                "id": "review-test",
                "source": "review:sol",
                "target": "gate:test",
                "kind": "gates",
            },
            "skip-plan": {
                "id": "skip-plan",
                "source": "task:skip",
                "target": "task:plan",
                "kind": "depends_on",
            },
        },
    }


class TerminalRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)

    def test_format_duration_uses_lifecycle_times_and_honest_task_fallback(self) -> None:
        self.assertEqual(
            format_duration({"state": "running", "started_at": "2026-08-14T11:56:42Z"}, self.now),
            "running 3m 18s",
        )
        self.assertEqual(
            format_duration({"state": "waiting", "created_at": "2026-08-14T11:48:00Z"}, self.now),
            "waiting 12m",
        )
        self.assertEqual(
            format_duration({"state": "passed", "started_at": "2026-08-14T11:50:00Z", "finished_at": "2026-08-14T11:57:42Z"}, self.now),
            "passed in 7m 42s",
        )
        self.assertEqual(
            format_duration({"kind": "task", "state": "passed", "created_at": "2026-08-14T11:50:00Z", "finished_at": "2026-08-14T11:57:42Z"}, self.now),
            "passed in 7m 42s",
        )

    def test_format_duration_refuses_degraded_late_or_malformed_times(self) -> None:
        for kind in ("claude_agent", "review", "quality_gate", "session"):
            with self.subTest(kind=kind):
                self.assertEqual(
                    format_duration({"kind": kind, "state": "passed", "degraded": True, "created_at": "2026-08-14T11:50:00Z", "finished_at": "2026-08-14T11:57:42Z"}, self.now),
                    "duration unknown",
                )
        self.assertEqual(
            format_duration({"state": "passed", "started_at": "not-a-time", "finished_at": "2026-08-14T11:57:42Z"}, self.now),
            "duration unknown",
        )
        self.assertEqual(
            format_duration({"state": "running", "started_at": "2026-08-14T12:00:01Z"}, self.now),
            "duration unknown",
        )

    def test_wide_snapshot_shows_subject_then_description_and_duration(self) -> None:
        snapshot = sample_snapshot()
        node = snapshot["nodes"]["task:plan"]
        node.update({
            "description": "D" * 160,
            "created_at": "2026-08-14T11:50:00Z",
            "finished_at": "2026-08-14T11:57:42Z",
        })
        rendered = render_snapshot(snapshot, columns=200, color=False, unicode=True, now=self.now)

        lines = rendered.splitlines()
        subject_index = next(index for index, line in enumerate(lines) if "Plan feature" in line)
        self.assertEqual(lines[subject_index + 1].strip(), f"{'D' * 160} · passed in 7m 42s")

    def test_narrow_snapshot_clips_description_before_subject_state_or_duration_in_ascii(self) -> None:
        snapshot = sample_snapshot()
        snapshot["nodes"]["task:plan"].update({
            "description": "D" * 160,
            "created_at": "2026-08-14T11:50:00Z",
            "finished_at": "2026-08-14T11:57:42Z",
        })
        rendered = render_snapshot(snapshot, columns=60, color=False, unicode=False, now=self.now)

        self.assertIn("[OK] Plan feature; passed in 7m 42s", rendered)
        self.assertNotIn("D" * 20, rendered)
        self.assertNotIn("…", rendered)
        self.assertTrue(all(len(line) <= 60 for line in rendered.splitlines()))

    def test_session_catalog_and_all_session_views_are_human_readable(self) -> None:
        rows = [{
            "session_id": "session-1", "cwd": "/work/example", "title": "Example run",
            "status": "running", "updated_at": "2026-08-14T11:59:42Z",
        }]
        self.assertIn("Example run", render_session_catalog(rows, self.now, unicode=False))
        self.assertIn("18s ago", render_session_catalog(rows, self.now, unicode=False))
        bundle = {"projects": [{"cwd": "/work/example", "running": [{
            "session_id": "session-1", "title": "Example run", "status": "running",
            "updated_at": "2026-08-14T11:59:42Z", "nodes": {
                "agent:run": {"id": "agent:run", "label": "Run tests", "state": "running", "started_at": "2026-08-14T11:58:00Z"},
                "task:done": {"id": "task:done", "label": "Done", "state": "passed"},
            }, "edges": {},
        }], "completed": []}]}
        rendered = render_all_sessions(bundle, 100, self.now, unicode=False)
        self.assertIn("/work/example", rendered)
        self.assertIn("Example run", rendered)
        self.assertIn("Run tests · running 2m", rendered)

    def test_wide_view_shows_graph_statuses_and_model(self) -> None:
        rendered = render_snapshot(sample_snapshot(), columns=140, color=False, unicode=True)

        self.assertIn("Claudex5 live graph", rendered)
        self.assertIn("example-project", rendered)
        self.assertIn("✓ Plan feature", rendered)
        self.assertIn("● Implement feature", rendered)
        self.assertIn("claude-sonnet-5 · high", rendered)
        self.assertIn("○ Independent review", rendered)
        self.assertIn("gpt-5.6-sol · high", rendered)
        self.assertIn("! Tests", rendered)
        self.assertIn("◆ Deploy", rendered)
        self.assertIn("– Optional benchmark", rendered)
        self.assertIn("× Cancelled work", rendered)
        self.assertIn("Plan feature", rendered)
        self.assertIn("└", rendered)
        self.assertIn("2/8 complete", rendered)

    def test_narrow_view_lists_dependencies_and_clips(self) -> None:
        snapshot = sample_snapshot()
        snapshot["nodes"]["agent:impl"]["label"] = "A" * 200
        rendered = render_snapshot(snapshot, columns=60, color=False, unicode=True)

        self.assertIn("depends on", rendered)
        self.assertIn("Optional benchmark; depends on Plan feature", rendered)
        self.assertIn("…", rendered)
        self.assertTrue(all(len(line) <= 60 for line in rendered.splitlines()))

    def test_ascii_view_uses_plain_symbols_and_is_deterministic(self) -> None:
        first = render_snapshot(sample_snapshot(), columns=120, color=False, unicode=False)
        second = render_snapshot(sample_snapshot(), columns=120, color=False, unicode=False)

        self.assertEqual(first, second)
        self.assertNotIn("✓", first)
        self.assertIn("[RUN]", first)
        self.assertIn("+-", first)

    def test_empty_state_is_successfully_renderable(self) -> None:
        self.assertEqual(
            render_snapshot(None, columns=80, color=False, unicode=True),
            "No Claudex5 run is available.\n",
        )


if __name__ == "__main__":
    unittest.main()
