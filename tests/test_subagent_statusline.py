import json
import subprocess
import sys
import unittest
from pathlib import Path


class SubagentStatusLineTests(unittest.TestCase):
    repository = Path(__file__).resolve().parents[1]
    renderer = repository / "claude/statuslines/claudex5-subagent-models.py"

    def run_renderer(self, payload: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.renderer)],
            input=payload,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_all_claudex5_roles_show_their_model_and_effort(self):
        expected = {
            "harness-orchestrator": "Claude Fable 5 · high",
            "harness-orchestrator-opus": "Claude Opus 5 · high",
            "harness-researcher": "Claude Sonnet 5 · high",
            "harness-implementer": "Claude Sonnet 5 · high",
            "harness-implementer-opus": "Claude Opus 5 · high",
            "harness-architecture-reviewer": "Claude Opus 5 · high",
            "harness-code-reviewer": "Claude Opus 5 · high",
            "harness-judge": "Claude Fable 5 · high",
            "harness-judge-opus": "Claude Opus 5 · high",
        }
        tasks = [
            {
                "id": f"task-{index}",
                "name": name,
                "description": f"Work item {index}",
            }
            for index, name in enumerate(expected, start=1)
        ]

        result = self.run_renderer(json.dumps({"columns": 160, "tasks": tasks}))

        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(rows), len(expected))
        for index, (name, label) in enumerate(expected.items(), start=1):
            self.assertEqual(rows[index - 1]["id"], f"task-{index}")
            self.assertEqual(
                rows[index - 1]["content"],
                f"{name} [{label}] · Work item {index}",
            )

    def test_unknown_agents_are_left_to_claudes_default_renderer(self):
        payload = {
            "tasks": [
                {"id": "third-party", "name": "fable-advisor:grok", "description": "work"},
                {"id": "known", "name": "harness-researcher", "description": "inspect"},
                {"id": "superpowers", "name": "general-purpose", "description": "task"},
            ]
        }

        result = self.run_renderer(json.dumps(payload))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [json.loads(line) for line in result.stdout.splitlines()],
            [
                {
                    "id": "known",
                    "content": "harness-researcher [Claude Sonnet 5 · high] · inspect",
                }
            ],
        )

    def test_description_is_single_line_and_cannot_inject_terminal_controls(self):
        payload = {
            "tasks": [
                {
                    "id": "safe",
                    "name": "harness-implementer",
                    "description": "Implement\nTask\t1\x1b[31m",
                },
                {"id": "empty", "name": "harness-judge"},
            ]
        }

        result = self.run_renderer(json.dumps(payload))

        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(
            rows[0]["content"],
            "harness-implementer [Claude Sonnet 5 · high] · Implement Task 1 [31m",
        )
        self.assertNotIn("\x1b", result.stdout)
        self.assertEqual(rows[1]["content"], "harness-judge [Claude Fable 5 · high]")

    def test_malformed_input_fails_without_echoing_it(self):
        sensitive_invalid_input = '{"tasks": ["private-value"}'

        result = self.run_renderer(sensitive_invalid_input)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("private-value", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
