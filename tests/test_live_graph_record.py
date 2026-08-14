from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.live_graph.record import normalize_hook, record_hook
from scripts.live_graph.store import StateStore


class HookNormalizationTests(unittest.TestCase):
    def test_official_task_hooks_preserve_safe_metadata_without_completing(self) -> None:
        created = normalize_hook(
            {
                "hook_event_name": "TaskCreated",
                "session_id": "session-1",
                "task_id": "task-001",
                "task_subject": "Implement user authentication",
                "task_description": "Add login and signup endpoints",
                "teammate_name": "implementer",
                "transcript_path": "/private/transcript.jsonl",
            }
        )[0]
        completed = normalize_hook(
            {
                "hook_event_name": "TaskCompleted",
                "session_id": "session-1",
                "task_id": "task-001",
                "task_subject": "Implement user authentication",
                "task_description": "Add login and signup endpoints",
                "team_name": "deprecated-team",
                "transcript_path": "/private/transcript.jsonl",
            }
        )[0]

        for event in (created, completed):
            self.assertEqual(event["event_type"], "task.created")
            self.assertEqual(event["node_id"], "task:task-001")
            self.assertEqual(event["payload"]["label"], "Implement user authentication")
            self.assertEqual(event["payload"]["description"], "Add login and signup endpoints")
            self.assertNotIn("state", event["payload"])
            encoded = json.dumps(event)
            self.assertNotIn("teammate_name", encoded)
            self.assertNotIn("team_name", encoded)
            self.assertNotIn("transcript", encoded)

    def test_session_start_includes_non_empty_session_title_only(self) -> None:
        event = normalize_hook(
            {
                "hook_event_name": "SessionStart",
                "session_id": "session-1",
                "cwd": "/tmp/project",
                "session_title": "  Build\nDashboard ",
                "transcript_path": "/private/transcript.jsonl",
            }
        )[0]

        self.assertEqual(event["payload"]["title"], "Build Dashboard")
        self.assertNotIn("transcript", json.dumps(event))

    def test_normalizes_supported_lifecycle_without_private_fields(self) -> None:
        fixtures = (
            (
                {"hook_event_name": "SessionStart", "session_id": "session-1", "cwd": "/tmp/project"},
                "session.started",
                "session:session-1",
            ),
            (
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "tool_name": "TaskCreate",
                    "tool_use_id": "toolu-1",
                    "tool_input": {"subject": "Implement parser", "blockedBy": ["7"]},
                },
                "task.created",
                "task:compat-toolu-1",
            ),
            (
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "session-1",
                    "tool_name": "TaskUpdate",
                    "tool_input": {"taskId": "toolu-1", "status": "completed"},
                    "tool_response": {"task": {"id": "toolu-1", "status": "completed"}},
                },
                "task.updated",
                "task:toolu-1",
            ),
            (
                {
                    "hook_event_name": "SubagentStart",
                    "session_id": "session-1",
                    "agent_id": "agent-1",
                    "agent_type": "harness-researcher",
                },
                "node.started",
                "agent:agent-1",
            ),
            (
                {
                    "hook_event_name": "SubagentStop",
                    "session_id": "session-1",
                    "agent_id": "agent-1",
                    "agent_type": "harness-researcher",
                },
                "node.finished",
                "agent:agent-1",
            ),
            (
                {"hook_event_name": "Stop", "session_id": "session-1"},
                "checkpoint",
                "session:session-1",
            ),
            (
                {"hook_event_name": "SessionEnd", "session_id": "session-1", "reason": "clear"},
                "session.ended",
                "session:session-1",
            ),
        )

        for payload, expected_type, expected_node in fixtures:
            with self.subTest(event=payload["hook_event_name"]):
                normalized = normalize_hook(payload)
                self.assertEqual(len(normalized), 1)
                self.assertEqual(normalized[0]["event_type"], expected_type)
                self.assertEqual(normalized[0]["node_id"], expected_node)
                encoded = json.dumps(normalized)
                self.assertNotIn("tool_response", encoded)
                self.assertNotIn("reason", encoded)

    def test_task_and_role_fields_are_safe_and_explicit(self) -> None:
        task = normalize_hook(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-1",
                "tool_name": "TaskCreate",
                "tool_use_id": "toolu-1",
                "tool_input": {
                    "subject": "  Build\nparser  ",
                    "blockedBy": ["7", "task:8", "../unsafe"],
                    "description": "must not persist",
                },
            }
        )[0]
        self.assertEqual(task["payload"]["label"], "Build parser")
        self.assertEqual(task["payload"]["dependencies"], ["task:7", "task:8"])
        self.assertNotIn("description", task["payload"])

    def test_pre_task_create_prefers_explicit_stable_identifier(self) -> None:
        event = normalize_hook(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-1",
                "tool_name": "TaskCreate",
                "tool_use_id": "tool-use-1",
                "tool_input": {"taskId": "stable-001", "id": "stable-002", "subject": "Stable task"},
            }
        )[0]

        self.assertEqual(event["node_id"], "task:stable-001")
        self.assertNotIn("tool-use-1", json.dumps(event))

    def test_post_task_create_explicitly_supersedes_compatibility_node(self) -> None:
        event = normalize_hook(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "session-1",
                "tool_name": "TaskCreate",
                "tool_use_id": "tool-use-1",
                "tool_input": {
                    "subject": "Create safe task",
                    "description": "Input description",
                    "prompt": "prompt-secret-value",
                },
                "tool_response": {
                    "task": {
                        "taskId": "stable-001",
                        "description": "Response description",
                        "telemetry": {"secret": "telemetry-secret-value"},
                    },
                    "output": "tool-output-secret-value",
                },
            }
        )[0]

        self.assertEqual(event["event_type"], "task.created")
        self.assertEqual(event["node_id"], "task:stable-001")
        self.assertEqual(
            event["payload"],
            {
                "kind": "task",
                "label": "Create safe task",
                "description": "Input description",
                "supersedes": "task:compat-tool-use-1",
            },
        )
        encoded = json.dumps(event)
        self.assertNotIn("prompt-secret-value", encoded)
        self.assertNotIn("telemetry-secret-value", encoded)
        self.assertNotIn("tool-output-secret-value", encoded)

    def test_agent_description_requires_explicit_structured_agent_id(self) -> None:
        event = normalize_hook(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "session-1",
                "tool_name": "Agent",
                "tool_input": {
                    "description": "A" * 200,
                    "prompt": "prompt-secret-value",
                },
                "tool_response": {
                    "agentId": "agent-001",
                    "outputFile": "/private/output-secret.json",
                    "telemetry": {"secret": "telemetry-secret-value"},
                },
            }
        )

        self.assertEqual(
            event,
            [
                {
                    "event_type": "node.updated",
                    "node_id": "agent:agent-001",
                    "payload": {"description": "A" * 160},
                    "source": "claude-hook",
                }
            ],
        )
        self.assertNotIn("prompt-secret-value", json.dumps(event))
        self.assertNotIn("output-secret.json", json.dumps(event))
        self.assertNotIn("telemetry-secret-value", json.dumps(event))
        self.assertEqual(
            normalize_hook(
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "session-1",
                    "tool_name": "Agent",
                    "tool_input": {"description": "Known description"},
                    "tool_response": {"title": "Subagent but not an identifier"},
                }
            ),
            [],
        )

        agent = normalize_hook(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "session-1",
                "agent_id": "agent-1",
                "agent_type": "harness-architecture-reviewer",
            }
        )[0]
        self.assertEqual(
            agent["payload"],
            {
                "kind": "review",
                "label": "harness-architecture-reviewer",
                "role": "harness-architecture-reviewer",
                "model": "claude-opus-5",
                "effort": "high",
            },
        )

        code_review_agent = normalize_hook(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "session-1",
                "agent_id": "agent-2",
                "agent_type": "harness-code-reviewer",
            }
        )[0]
        self.assertEqual(
            code_review_agent["payload"],
            {
                "kind": "review",
                "label": "harness-code-reviewer",
                "role": "harness-code-reviewer",
                "model": "claude-opus-5",
                "effort": "high",
            },
        )

    def test_unknown_or_unsafe_hook_payload_is_ignored(self) -> None:
        self.assertEqual(normalize_hook(None), [])
        self.assertEqual(normalize_hook({"hook_event_name": "Unknown", "session_id": "session-1"}), [])
        self.assertEqual(normalize_hook({"hook_event_name": "Stop", "session_id": "../escape"}), [])
        self.assertEqual(
            normalize_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "tool_name": "Bash",
                    "tool_input": {"command": "echo private"},
                }
            ),
            [],
        )

    def test_non_string_labels_and_roles_cannot_serialize_nested_hook_data(self) -> None:
        task = normalize_hook(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-1",
                "tool_name": "TaskCreate",
                "tool_use_id": "task-1",
                "tool_input": {"subject": {"private": "nested-secret"}},
            }
        )[0]
        agent = normalize_hook(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "session-1",
                "agent_id": "agent-1",
                "agent_type": {"private": "nested-secret"},
            }
        )[0]

        encoded = json.dumps([task, agent])
        self.assertEqual(task["payload"]["label"], "Task")
        self.assertEqual(agent["payload"]["label"], "Claude subagent")
        self.assertNotIn("nested-secret", encoded)


class HookPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.project = self.base / "project"
        self.project.mkdir()
        self.store = StateStore(self.base / "state" / "runs")

    def record(self, **payload: object) -> list[dict[str, object]]:
        return record_hook(payload, self.store)

    def test_records_full_safe_lifecycle_and_stop_is_only_checkpoint(self) -> None:
        self.record(hook_event_name="SessionStart", session_id="session-1", cwd=str(self.project))
        self.record(
            hook_event_name="PreToolUse",
            session_id="session-1",
            tool_name="TaskCreate",
            tool_use_id="task-tool-1",
            tool_input={"subject": "Implement feature", "blockedBy": []},
        )
        self.record(
            hook_event_name="SubagentStart",
            session_id="session-1",
            agent_id="agent-1",
            agent_type="harness-implementer",
        )
        self.record(hook_event_name="Stop", session_id="session-1")
        snapshot = self.store.load("session-1")
        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["nodes"]["agent:agent-1"]["state"], "running")
        self.assertEqual(snapshot["cwd"], str(self.project.resolve()))

        self.record(
            hook_event_name="SubagentStop",
            session_id="session-1",
            agent_id="agent-1",
            agent_type="harness-implementer",
        )
        self.record(
            hook_event_name="PostToolUse",
            session_id="session-1",
            tool_name="TaskUpdate",
            tool_input={"taskId": "task-tool-1", "status": "completed"},
            tool_response={"task": {"id": "task-tool-1", "status": "completed"}},
        )
        self.record(hook_event_name="SessionEnd", session_id="session-1", reason="clear")
        snapshot = self.store.load("session-1")
        self.assertEqual(snapshot["status"], "passed")
        self.assertEqual(snapshot["nodes"]["agent:agent-1"]["state"], "passed")
        self.assertEqual(snapshot["nodes"]["task:task-tool-1"]["state"], "passed")

    def test_private_hook_fields_never_reach_state_files(self) -> None:
        secret_values = (
            "Bearer " + "abcdefghijklmnopqrstuvwxyz012345",
            "/private/transcript-secret.jsonl",
            "echo command-secret-value",
            "tool-output-secret-value",
            "assistant-message-secret-value",
        )
        self.record(
            hook_event_name="SessionStart",
            session_id="session-1",
            cwd=str(self.project),
            transcript_path=secret_values[1],
        )
        self.record(
            hook_event_name="PreToolUse",
            session_id="session-1",
            tool_name="TaskCreate",
            tool_use_id="task-1",
            tool_input={
                "subject": secret_values[0],
                "description": secret_values[2],
                "command": secret_values[2],
            },
            tool_output=secret_values[3],
            last_assistant_message=secret_values[4],
            transcript_path=secret_values[1],
        )

        persisted = b"\n".join(path.read_bytes() for path in self.store.root.rglob("*") if path.is_file())
        for secret in secret_values:
            with self.subTest(secret=secret):
                self.assertNotIn(secret.encode(), persisted)
        self.assertIn(b"[REDACTED]", persisted)

    def test_persists_stable_tasks_agent_description_and_no_private_hook_values(self) -> None:
        private_values = (
            "prompt-secret-value",
            "command-secret-value",
            "tool-output-secret-value",
            "assistant-message-secret-value",
            "/private/output-secret.json",
            "/private/transcript-secret.jsonl",
        )
        self.record(
            hook_event_name="SessionStart",
            session_id="session-1",
            cwd=str(self.project),
            session_title="Dashboard session",
            transcript_path=private_values[5],
        )
        self.record(
            hook_event_name="PreToolUse",
            session_id="session-1",
            tool_name="TaskCreate",
            tool_use_id="tool-use-1",
            tool_input={
                "subject": "Legacy stable task",
                "command": private_values[1],
                "description": private_values[0],
            },
            transcript_path=private_values[5],
        )
        self.record(
            hook_event_name="PostToolUse",
            session_id="session-1",
            tool_name="TaskCreate",
            tool_use_id="tool-use-1",
            tool_input={
                "subject": "Legacy stable task",
                "description": "Safe stable description",
                "prompt": private_values[0],
            },
            tool_response={
                "task": {"id": "stable-task-1"},
                "output": private_values[2],
            },
            last_assistant_message=private_values[3],
            transcript_path=private_values[5],
        )
        snapshot = self.store.load("session-1")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        visible_task_ids = [
            node_id
            for node_id, node in snapshot["nodes"].items()
            if node["kind"] == "task" and not node.get("superseded_by")
        ]
        self.assertEqual(visible_task_ids, ["task:stable-task-1"])
        self.assertEqual(
            snapshot["nodes"]["task:compat-tool-use-1"]["superseded_by"], "task:stable-task-1"
        )
        self.assertEqual(snapshot["nodes"]["task:stable-task-1"]["description"], "Safe stable description")

        self.record(
            hook_event_name="TaskCreated",
            session_id="session-1",
            task_id="task-001",
            task_subject="Official task",
            task_description="Safe official description",
            transcript_path=private_values[5],
        )
        self.record(
            hook_event_name="SubagentStart",
            session_id="session-1",
            agent_id="agent-001",
            agent_type="harness-implementer",
        )
        self.record(
            hook_event_name="PostToolUse",
            session_id="session-1",
            tool_name="Agent",
            tool_input={"description": "Safe agent description", "prompt": private_values[0]},
            tool_response={"agentId": "agent-001", "outputFile": private_values[4]},
            transcript_path=private_values[5],
        )
        self.record(
            hook_event_name="TaskCompleted",
            session_id="session-1",
            task_id="task-001",
            task_subject="Official task",
            task_description="Safe official description",
            transcript_path=private_values[5],
        )
        snapshot = self.store.load("session-1")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["nodes"]["task:task-001"]["state"], "waiting")
        self.assertNotIn("finished_at", snapshot["nodes"]["task:task-001"])
        self.assertEqual(snapshot["nodes"]["agent:agent-001"]["description"], "Safe agent description")

        self.record(
            hook_event_name="PostToolUse",
            session_id="session-1",
            tool_name="TaskUpdate",
            tool_input={"taskId": "task-001", "status": "completed"},
            tool_response={"task": {"id": "task-001", "status": "completed"}},
            transcript_path=private_values[5],
        )
        self.record(
            hook_event_name="SubagentStop",
            session_id="session-1",
            agent_id="agent-001",
            agent_type="harness-implementer",
        )
        self.record(hook_event_name="SessionEnd", session_id="session-1", transcript_path=private_values[5])

        snapshot = self.store.load("session-1")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["title"], "Dashboard session")
        task = snapshot["nodes"]["task:task-001"]
        self.assertEqual(task["state"], "passed")
        self.assertIn("finished_at", task)

        persisted = b"\n".join(path.read_bytes() for path in self.store.root.rglob("*") if path.is_file())
        for private_value in private_values:
            with self.subTest(private_value=private_value):
                self.assertNotIn(private_value.encode(), persisted)

    def test_store_timeout_is_non_blocking(self) -> None:
        class UnavailableStore:
            def append(self, *args: object, **kwargs: object) -> dict[str, object]:
                raise TimeoutError

        events = record_hook(
            {"hook_event_name": "Stop", "session_id": "session-1"},
            UnavailableStore(),  # type: ignore[arg-type]
        )
        self.assertEqual(events, [])


class HookEntryPointTests(unittest.TestCase):
    def test_malformed_input_exits_zero_without_echoing_secret(self) -> None:
        hook = Path(__file__).parents[1] / "claude" / "hooks" / "claudex5-live-graph.py"
        secret = "Bearer " + "abcdefghijklmnopqrstuvwxyz012345"
        process = subprocess.run(
            [str(hook)],
            input='{"private":"' + secret + '"',
            text=True,
            capture_output=True,
            env={**os.environ, "XDG_STATE_HOME": str(Path(self.id()).parent)},
            check=False,
        )

        self.assertEqual(process.returncode, 0)
        self.assertIn("invalid-input", process.stderr)
        self.assertNotIn(secret, process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()
