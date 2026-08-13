from __future__ import annotations

import unittest

from scripts.live_graph.terminal import render_snapshot


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
        },
    }


class TerminalRendererTests(unittest.TestCase):
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
