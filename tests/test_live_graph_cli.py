from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import io
import tempfile
import time
import unittest
import unittest.mock

import scripts.live_graph_cli as live_graph_cli


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
            "--dependency",
            "task:plan",
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
        self.assertIn(
            f"{review['id']}|depends_on|task:plan",
            snapshot["edges"],
        )
        self.assertEqual(
            snapshot["edges"][f"{review['id']}|depends_on|task:plan"]["target"],
            "task:plan",
        )
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

    def test_final_telemetry_failure_does_not_replace_child_exit_status(self) -> None:
        class FailingFinalStore:
            def __init__(self) -> None:
                self.calls = 0

            def append(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 2:
                    raise OSError("state disk unavailable")

            def latest(self, *_args, **_kwargs):
                return None

        arguments = live_graph_cli._parser().parse_args(
            ["gate-run", "--session-id", "session-1", "--name", "tests", "--", "child"]
        )
        store = FailingFinalStore()

        with unittest.mock.patch.object(
            live_graph_cli, "_run_child", return_value=(9, False)
        ), unittest.mock.patch("sys.stderr") as stderr:
            result = live_graph_cli._gate_run(arguments, store)

        self.assertEqual(result, 9)
        self.assertEqual(store.calls, 2)
        self.assertTrue(stderr.write.called)

    def test_dashboard_target_options_are_mutually_exclusive(self) -> None:
        parser = live_graph_cli._parser()
        for arguments in (
            ["dashboard", "--session-id", "session-1", "--all"],
            ["dashboard", "--session-id", "session-1", "--select"],
            ["dashboard", "--all", "--select"],
        ):
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as error:
                parser.parse_args(arguments)
            self.assertEqual(error.exception.code, 2)

    def test_explicit_missing_dashboard_session_is_a_command_error(self) -> None:
        result = self.run_cli("dashboard", "--session-id", "missing-session", "--once")

        self.assertEqual(result.returncode, 2)
        self.assertIn("selected session is unavailable", result.stderr)

    def test_web_all_passes_an_immutable_all_session_selection_to_the_server(self) -> None:
        with unittest.mock.patch("scripts.live_graph.web.serve_dashboard", return_value=0) as serve:
            result = live_graph_cli.main(["dashboard", "--web", "--all", "--no-open"])

        self.assertEqual(result, 0)
        self.assertEqual(serve.call_args.args[1], live_graph_cli.SessionSelection.all())

    def test_web_session_selection_is_passed_as_an_immutable_selection(self) -> None:
        with unittest.mock.patch("scripts.live_graph.web.serve_dashboard", return_value=0) as serve:
            result = live_graph_cli.main([
                "dashboard", "--web", "--session-id", "fixed-session", "--no-open",
            ])

        self.assertEqual(result, 0)
        self.assertEqual(serve.call_args.args[1], live_graph_cli.SessionSelection.one("fixed-session"))

    def test_interactive_selector_accepts_default_numeric_all_invalid_eof_and_quit(self) -> None:
        rows = [
            {"session_id": "session-1", "cwd": "/work/one", "title": "One", "status": "running", "updated_at": "2026-08-14T12:00:00Z"},
            {"session_id": "session-2", "cwd": "/work/two", "title": "Two", "status": "passed", "updated_at": "2026-08-14T12:00:00Z"},
        ]
        for entered, expected in (("2\n", "session-2"), ("\n", "session-1"), ("A\n", "all"), ("bad\n1\n", "session-1"), ("Q\n", None), ("", None)):
            with self.subTest(entered=entered):
                output = io.StringIO()
                selected = live_graph_cli._select_session(rows, io.StringIO(entered), output)
                self.assertEqual(selected.mode if selected else None, "all" if expected == "all" else "session" if expected else None)
                self.assertEqual(selected.session_id if selected else None, expected if expected not in {None, "all"} else None)
                if entered.startswith("bad"):
                    self.assertIn("Invalid selection", output.getvalue())

    def test_resolver_uses_path_candidates_and_non_tty_is_unambiguous_only(self) -> None:
        class Store:
            def __init__(self, snapshots): self._snapshots = snapshots
            def snapshots(self): return list(self._snapshots)
        current = str(REPOSITORY.resolve())
        running = {"session_id": "session-1", "cwd": current, "status": "running", "updated_at": "2026-08-14T12:00:00Z"}
        other = {"session_id": "session-2", "cwd": "/other", "status": "running", "updated_at": "2026-08-14T12:00:00Z"}
        arguments = live_graph_cli._parser().parse_args(["dashboard", "--once"])
        selected = live_graph_cli._resolve_dashboard_selection(Store([running, other]), arguments, cwd=REPOSITORY, isatty=False)
        self.assertEqual(selected.session_id, "session-1")
        retained = dict(running, status="passed")
        self.assertEqual(live_graph_cli._resolve_dashboard_selection(Store([retained]), arguments, cwd=REPOSITORY, isatty=False).session_id, "session-1")
        with self.assertRaisesRegex(ValueError, "--session-id.*--all"):
            live_graph_cli._resolve_dashboard_selection(Store([running, dict(running, session_id="session-3")]), arguments, cwd=REPOSITORY, isatty=False)
        output = io.StringIO()
        interactive_arguments = live_graph_cli._parser().parse_args(["dashboard"])
        self.assertEqual(
            live_graph_cli._resolve_dashboard_selection(Store([other]), interactive_arguments, cwd=REPOSITORY, isatty=True, input_stream=io.StringIO("1\n"), output_stream=output).session_id,
            "session-2",
        )

    def test_once_does_not_prompt_without_explicit_select(self) -> None:
        class Store:
            def snapshots(self):
                return [
                    {"session_id": "session-1", "cwd": str(REPOSITORY), "status": "running", "updated_at": "2026-08-14T12:00:00Z"},
                    {"session_id": "session-2", "cwd": str(REPOSITORY), "status": "running", "updated_at": "2026-08-14T12:00:00Z"},
                ]
        arguments = live_graph_cli._parser().parse_args(["dashboard", "--once"])

        with self.assertRaisesRegex(ValueError, "--session-id.*--all"):
            live_graph_cli._resolve_dashboard_selection(
                Store(), arguments, cwd=REPOSITORY, isatty=True,
                input_stream=io.StringIO("1\n"), output_stream=io.StringIO(),
            )

    def test_follow_mode_pins_selection_and_recovers_from_transient_read_failure(self) -> None:
        selected = live_graph_cli.SessionSelection.one("session-1")
        bundle = {"selection": {"mode": "session", "session_id": "session-1"}, "projects": [{"cwd": "/work", "running": [{"session_id": "session-1", "nodes": {}, "edges": {}}], "completed": []}]}
        outputs = []
        with unittest.mock.patch.object(live_graph_cli, "_resolve_dashboard_selection", return_value=selected) as resolve, \
             unittest.mock.patch.object(live_graph_cli, "build_bundle", side_effect=[bundle, TimeoutError("state busy"), bundle]), \
             unittest.mock.patch.object(live_graph_cli, "_render_dashboard_bundle", return_value="GRAPH\n"), \
             unittest.mock.patch.object(live_graph_cli.sys, "stdout", new=io.StringIO()) as stdout, \
             unittest.mock.patch.object(live_graph_cli.sys, "stdin") as stdin, \
             unittest.mock.patch.object(live_graph_cli.time, "sleep", side_effect=[None, None, KeyboardInterrupt()]) as sleep:
            stdin.isatty.return_value = True
            result = live_graph_cli.main(["dashboard"])
            outputs.append(stdout.getvalue())
        self.assertEqual(result, 130)
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(sleep.call_count, 3)
        self.assertIn("STATE READ DEGRADED", outputs[0])


if __name__ == "__main__":
    unittest.main()
