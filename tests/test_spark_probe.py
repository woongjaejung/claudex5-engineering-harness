import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.spark_probe import ProbeState, probe_spark


class SparkProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fake_codex = Path(self.temporary_directory.name) / "codex"
        self.fake_codex.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                import time

                if sys.argv[1:] != ["app-server"]:
                    raise SystemExit(64)

                scenario = os.environ.get("FAKE_SPARK_SCENARIO", "unavailable")
                if scenario == "timeout":
                    time.sleep(10)
                    raise SystemExit(0)

                initialize = json.loads(sys.stdin.readline())
                if scenario == "malformed":
                    print("not-json", flush=True)
                    raise SystemExit(0)
                print(json.dumps({"id": initialize["id"], "result": {}}), flush=True)
                json.loads(sys.stdin.readline())

                while True:
                    request = json.loads(sys.stdin.readline())
                    if scenario == "error":
                        print(json.dumps({"id": request["id"], "error": {"code": -1, "message": "denied"}}), flush=True)
                        break
                    cursor = request.get("params", {}).get("cursor")
                    if scenario == "paginated" and cursor is None:
                        data = [{"id": "gpt-5.6-sol", "model": "gpt-5.6-sol"}]
                        next_cursor = "page-2"
                    elif scenario in {"available", "paginated"}:
                        data = [{"id": "gpt-5.3-codex-spark", "model": "gpt-5.3-codex-spark"}]
                        next_cursor = None
                    else:
                        data = [{"id": "gpt-5.6-sol", "model": "gpt-5.6-sol"}]
                        next_cursor = None
                    print(json.dumps({"id": request["id"], "result": {"data": data, "nextCursor": next_cursor}}), flush=True)
                    if next_cursor is None:
                        break
                """
            ),
            encoding="utf-8",
        )
        self.fake_codex.chmod(0o755)

    def probe(self, scenario: str, timeout: float = 2.0) -> ProbeState:
        previous = os.environ.get("FAKE_SPARK_SCENARIO")
        os.environ["FAKE_SPARK_SCENARIO"] = scenario
        try:
            return probe_spark(str(self.fake_codex), timeout).state
        finally:
            if previous is None:
                os.environ.pop("FAKE_SPARK_SCENARIO", None)
            else:
                os.environ["FAKE_SPARK_SCENARIO"] = previous

    def test_available_model_is_detected(self):
        self.assertEqual(self.probe("available"), ProbeState.AVAILABLE)

    def test_completed_catalog_without_spark_is_unavailable(self):
        self.assertEqual(self.probe("unavailable"), ProbeState.UNAVAILABLE)

    def test_paginated_catalog_is_followed(self):
        self.assertEqual(self.probe("paginated"), ProbeState.AVAILABLE)

    def test_malformed_protocol_is_unknown(self):
        self.assertEqual(self.probe("malformed"), ProbeState.UNKNOWN)

    def test_app_server_error_is_unknown(self):
        self.assertEqual(self.probe("error"), ProbeState.UNKNOWN)

    def test_timeout_is_unknown(self):
        self.assertEqual(self.probe("timeout", timeout=0.1), ProbeState.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
