from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import time
import unittest


REPOSITORY = Path(__file__).parents[1]
COMMAND = REPOSITORY / "bin" / "claudex5"


class LiveGraphCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.home = self.base / "home"
        self.state_home = self.base / "state"
        self.bin_dir = self.base / "bin"
        self.home.mkdir()
        self.bin_dir.mkdir()
        self.environment = {
            **os.environ,
            "HOME": str(self.home),
            "XDG_STATE_HOME": str(self.state_home),
            "PATH": f"{self.bin_dir}:{os.environ.get('PATH', '')}",
        }

    def run_cli(self, *arguments: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(COMMAND), *arguments],
            cwd=REPOSITORY,
            env=self.environment,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )

    def start_session(self, session_id: str = "session-1") -> None:
        result = self.run_cli(
            "event",
            "--session-id",
            session_id,
            "--type",
            "session.started",
            "--node-id",
            f"session:{session_id}",
            "--cwd",
            str(REPOSITORY),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_event_status_dashboard_and_clean(self) -> None:
        self.start_session()
        created = self.run_cli(
            "event",
            "--session-id",
            "session-1",
            "--type",
            "node.started",
            "--node-id",
            "task:one",
            "--kind",
            "task",
            "--label",
            "Implement one",
            "--parent-id",
            "session:session-1",
        )
        self.assertEqual(created.returncode, 0, created.stderr)

        status = self.run_cli("status", "--session-id", "session-1", "--json")
        self.assertEqual(status.returncode, 0, status.stderr)
        snapshot = json.loads(status.stdout)
        self.assertEqual(snapshot["nodes"]["task:one"]["state"], "running")

        dashboard = self.run_cli("dashboard", "--session-id", "session-1", "--once")
        self.assertEqual(dashboard.returncode, 0, dashboard.stderr)
        self.assertIn("Implement one", dashboard.stdout)

        cleaned = self.run_cli("clean", "--all")
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
        self.assertIn("1 run", cleaned.stdout)
        empty = self.run_cli("dashboard", "--once")
        self.assertEqual(empty.stdout, "No Claudex5 run is available.\n")

    def test_codex_run_uses_fixed_role_and_prompt_stdin(self) -> None:
        self.start_session()
        arguments_file = self.base / "codex-arguments.json"
        prompt_file = self.base / "prompt.txt"
        prompt_file.write_text("Review this plan without storing it", encoding="utf-8")
        fake = self.bin_dir / "codex"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            "pathlib.Path(os.environ['FAKE_CODEX_ARGS']).write_text(json.dumps(sys.argv[1:]))\n"
            "pathlib.Path(os.environ['FAKE_CODEX_STDIN']).write_text(sys.stdin.read())\n"
            "raise SystemExit(int(os.environ.get('FAKE_CODEX_EXIT', '0')))\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.environment["FAKE_CODEX_ARGS"] = str(arguments_file)
        self.environment["FAKE_CODEX_STDIN"] = str(self.base / "codex-stdin.txt")
        self.environment["FAKE_CODEX_EXIT"] = "7"

        result = self.run_cli(
            "codex-run",
            "--session-id",
            "session-1",
            "--role",
            "harness_sol_plan_review",
            "--label",
            "Plan review",
            "--sandbox",
            "read-only",
            "--prompt-file",
            str(prompt_file),
        )

        self.assertEqual(result.returncode, 7)
        arguments = json.loads(arguments_file.read_text(encoding="utf-8"))
        self.assertEqual(
            arguments,
            [
                "exec",
                "--ephemeral",
                "--model",
                "gpt-5.6-sol",
                "-c",
                'model_reasoning_effort="high"',
                "--sandbox",
                "read-only",
                "-",
            ],
        )
        self.assertEqual(
            (self.base / "codex-stdin.txt").read_text(encoding="utf-8"),
            "Review this plan without storing it",
        )
        snapshot = json.loads(self.run_cli("status", "--session-id", "session-1", "--json").stdout)
        review = next(node for node in snapshot["nodes"].values() if node.get("label") == "Plan review")
        self.assertEqual(review["state"], "failed")
        self.assertEqual(review["model"], "gpt-5.6-sol")
        persisted = b"\n".join(path.read_bytes() for path in self.state_home.rglob("*") if path.is_file())
        self.assertNotIn(b"Review this plan without storing it", persisted)

    def test_codex_run_accepts_prompt_on_stdin_and_rejects_unknown_role(self) -> None:
        self.start_session()
        fake = self.bin_dir / "codex"
        fake.write_text("#!/usr/bin/env sh\ncat >/dev/null\n", encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

        accepted = self.run_cli(
            "codex-run",
            "--session-id",
            "session-1",
            "--role",
            "harness_luna_implementation",
            "--label",
            "Alternative implementation",
            input_text="bounded prompt",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        rejected = self.run_cli(
            "codex-run",
            "--session-id",
            "session-1",
            "--role",
            "arbitrary_model",
            input_text="prompt",
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("invalid choice", rejected.stderr)

    def test_gate_run_does_not_use_a_shell_and_preserves_exit_status(self) -> None:
        self.start_session()
        child = self.bin_dir / "gate-child"
        child.write_text("#!/usr/bin/env sh\nexit 9\n", encoding="utf-8")
        child.chmod(child.stat().st_mode | stat.S_IXUSR)

        result = self.run_cli(
            "gate-run",
            "--session-id",
            "session-1",
            "--group-id",
            "quality:all",
            "--name",
            "lint; touch should-not-exist",
            "--",
            "gate-child",
        )
        self.assertEqual(result.returncode, 9)
        self.assertFalse((REPOSITORY / "should-not-exist").exists())
        snapshot = json.loads(self.run_cli("status", "--session-id", "session-1", "--json").stdout)
        child_node = next(node for node in snapshot["nodes"].values() if node.get("kind") == "quality_gate")
        self.assertEqual(child_node["state"], "failed")

    def test_gate_run_forwards_termination_and_records_interrupted(self) -> None:
        self.start_session()
        child = self.bin_dir / "waiting-child"
        marker = self.base / "child-signal.txt"
        ready = self.base / "child-ready.txt"
        child.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, signal, time\n"
            "ready = pathlib.Path(os.environ['CHILD_READY'])\n"
            "marker = pathlib.Path(os.environ['CHILD_SIGNAL'])\n"
            "def stop(signum, frame):\n"
            "    marker.write_text(str(signum))\n"
            "    raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            "ready.write_text(str(os.getpid()))\n"
            "while True: time.sleep(0.05)\n",
            encoding="utf-8",
        )
        child.chmod(child.stat().st_mode | stat.S_IXUSR)
        environment = {**self.environment, "CHILD_READY": str(ready), "CHILD_SIGNAL": str(marker)}
        process = subprocess.Popen(
            [
                str(COMMAND), "gate-run", "--session-id", "session-1",
                "--name", "long test", "--", "waiting-child",
            ],
            cwd=REPOSITORY,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(ready.exists(), "child process did not start")
        process.send_signal(signal.SIGTERM)
        _stdout, stderr = process.communicate(timeout=5)

        self.assertEqual(process.returncode, 128 + signal.SIGTERM, stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), str(signal.SIGTERM))
        snapshot = json.loads(self.run_cli("status", "--session-id", "session-1", "--json").stdout)
        child_node = next(
            node for node in snapshot["nodes"].values() if node.get("label") == "long test"
        )
        self.assertEqual(child_node["state"], "interrupted")


if __name__ == "__main__":
    unittest.main()
