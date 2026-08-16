import json
import subprocess
import sys
import tempfile
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

    def test_payload_model_and_effort_override_the_fixed_role_mapping(self):
        payload = {
            "tasks": [
                {
                    "id": "override",
                    "name": "harness-code-reviewer",
                    "description": "review",
                    "model": "claude-sonnet-5",
                    "effort": "high",
                },
            ]
        }

        result = self.run_renderer(json.dumps(payload))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [json.loads(line) for line in result.stdout.splitlines()],
            [
                {
                    "id": "override",
                    "content": "harness-code-reviewer [Claude Sonnet 5 · high] · review",
                }
            ],
        )

    def test_unknown_agents_with_a_resolved_model_get_a_labeled_row(self):
        payload = {
            "tasks": [
                {
                    "id": "resolved",
                    "name": "general-purpose",
                    "description": "task",
                    "model": "claude-opus-5",
                },
                {
                    "id": "numeric-effort",
                    "name": "Explore",
                    "model": "claude-haiku-4-5-20251001",
                    "effort": 8192,
                },
                {"id": "unresolved", "name": "general-purpose", "description": "task"},
            ]
        }

        result = self.run_renderer(json.dumps(payload))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [json.loads(line) for line in result.stdout.splitlines()],
            [
                {
                    "id": "resolved",
                    "content": "general-purpose [Claude Opus 5] · task",
                },
                {
                    "id": "numeric-effort",
                    "content": "Explore [Claude Haiku 4.5 · 8192]",
                },
            ],
        )

    def test_nameless_payload_from_claude_code_2_1_233_still_shows_the_model(self):
        # Real captured shape: 2.1.233 omits "name"; the panel prints the
        # subagent name as a fixed prefix, so the body starts at the label.
        payload = {
            "columns": 130,
            "tasks": [
                {
                    "id": "a0aed344c22e8c26a",
                    "type": "local_agent",
                    "status": "running",
                    "description": "Final fix wave (review findings)",
                    "label": "Final fix wave (review findings)",
                    "model": "claude-sonnet-5",
                    "tokenCount": 10213,
                },
                {
                    "id": "unresolved-nameless",
                    "type": "local_agent",
                    "status": "running",
                    "description": "starting up",
                },
            ]
        }

        result = self.run_renderer(json.dumps(payload))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [json.loads(line) for line in result.stdout.splitlines()],
            [
                {
                    "id": "a0aed344c22e8c26a",
                    "content": "[Claude Sonnet 5] · Final fix wave (review findings)",
                }
            ],
        )

    def test_agent_name_is_recovered_from_the_task_transcript(self):
        # 2.1.233 payloads omit the name, and a custom row replaces the whole
        # body — so the renderer reads it back from the subagent transcript.
        with tempfile.TemporaryDirectory() as root:
            transcript = Path(root) / "session-1.jsonl"
            transcript.write_text("{}\n")
            subagents = Path(root) / "session-1" / "subagents"
            subagents.mkdir(parents=True)
            entries = [
                {"type": "user", "agentId": "abc123"},
                {"type": "assistant", "attributionAgent": "harness-implementer"},
            ]
            (subagents / "agent-abc123.jsonl").write_text(
                "\n".join(json.dumps(entry) for entry in entries) + "\n"
            )
            payload = {
                "transcript_path": str(transcript),
                "tasks": [
                    {
                        "id": "abc123",
                        "type": "local_agent",
                        "status": "running",
                        "description": "Implement model profiles switch",
                        "model": "claude-sonnet-5",
                        "effort": "high",
                    },
                    {
                        "id": "no-transcript",
                        "type": "local_agent",
                        "status": "running",
                        "description": "starting",
                        "model": "claude-opus-5",
                    },
                ],
            }

            result = self.run_renderer(json.dumps(payload))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [json.loads(line) for line in result.stdout.splitlines()],
            [
                {
                    "id": "abc123",
                    "content": (
                        "harness-implementer [Claude Sonnet 5 · high]"
                        " · Implement model profiles switch"
                    ),
                },
                {
                    "id": "no-transcript",
                    "content": "[Claude Opus 5] · starting",
                },
            ],
        )

    def test_malformed_input_fails_without_echoing_it(self):
        sensitive_invalid_input = '{"tasks": ["private-value"}'

        result = self.run_renderer(sensitive_invalid_input)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("private-value", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
