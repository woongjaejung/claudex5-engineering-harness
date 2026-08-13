from __future__ import annotations

from contextlib import contextmanager
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from scripts.live_graph.web import APP_JS, create_server


SAMPLE_SNAPSHOT = {
    "schema_version": 1,
    "session_id": "demo-session",
    "cwd": "/tmp/example-project",
    "status": "running",
    "degraded": False,
    "sequence": 3,
    "nodes": {
        "session:demo-session": {
            "id": "session:demo-session",
            "kind": "session",
            "label": "Claudex5 run",
            "state": "running",
            "sequence": 1,
        },
        "agent:impl": {
            "id": "agent:impl",
            "kind": "claude_agent",
            "label": "Implement dashboard",
            "state": "running",
            "model": "claude-sonnet-5",
            "effort": "high",
            "sequence": 2,
        },
    },
    "edges": {
        "session-agent": {
            "id": "session-agent",
            "source": "session:demo-session",
            "target": "agent:impl",
            "kind": "dispatches",
        }
    },
}


class MemoryStore:
    def __init__(self, snapshot: dict | None = SAMPLE_SNAPSHOT):
        self.snapshot = snapshot
        self.loaded_session_ids: list[str] = []
        self.latest_calls = 0

    def load(self, session_id: str) -> dict | None:
        self.loaded_session_ids.append(session_id)
        return self.snapshot

    def latest(self) -> dict | None:
        self.latest_calls += 1
        return self.snapshot


@contextmanager
def running_server(store: MemoryStore, session_id: str | None = None):
    server = create_server(store, session_id=session_id, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


class WebDashboardTests(unittest.TestCase):
    def test_next_runnable_requires_successful_prerequisites(self) -> None:
        self.assertIn('const SATISFIED = new Set(["passed", "skipped"]);', APP_JS)
        self.assertIn("SATISFIED.has(stateById.get(source))", APP_JS)
        self.assertNotIn("TERMINAL.has(stateById.get(source))", APP_JS)

    def test_fixed_routes_serve_local_assets_with_security_headers(self) -> None:
        with running_server(MemoryStore()) as base_url:
            for path, expected_type in (
                ("/", "text/html"),
                ("/app.js", "text/javascript"),
                ("/style.css", "text/css"),
            ):
                with self.subTest(path=path), urlopen(base_url + path) as response:
                    body = response.read().decode("utf-8")
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.headers["Content-Type"].startswith(expected_type))
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                    self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])
                    self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
                    self.assertTrue(body)

    def test_snapshot_route_returns_selected_run_as_json(self) -> None:
        store = MemoryStore()
        with running_server(store, session_id="selected-session") as base_url:
            with urlopen(base_url + "/api/snapshot") as response:
                payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload, SAMPLE_SNAPSHOT)
        self.assertEqual(store.loaded_session_ids, ["selected-session"])
        self.assertEqual(store.latest_calls, 0)

    def test_snapshot_route_selects_latest_run_and_represents_empty_state(self) -> None:
        store = MemoryStore(snapshot=None)
        with running_server(store) as base_url:
            with urlopen(base_url + "/api/snapshot") as response:
                payload = json.loads(response.read().decode("utf-8"))

        self.assertIsNone(payload)
        self.assertEqual(store.latest_calls, 1)

    def test_unknown_routes_return_plain_404_without_reflecting_the_path(self) -> None:
        with running_server(MemoryStore()) as base_url:
            with self.assertRaises(HTTPError) as raised:
                urlopen(base_url + "/%3Cscript%3Ealert(1)%3C/script%3E")

            error = raised.exception
            try:
                body = error.read().decode("utf-8")
                self.assertEqual(error.code, 404)
                self.assertEqual(body, "Not found.\n")
                self.assertNotIn("script", body)
                self.assertEqual(error.headers["Cache-Control"], "no-store")
            finally:
                error.close()

    def test_dynamic_session_identifier_is_html_escaped(self) -> None:
        session_id = '\"><script>alert("x")</script>'
        with running_server(MemoryStore(), session_id=session_id) as base_url:
            with urlopen(base_url + "/") as response:
                body = response.read().decode("utf-8")

        self.assertNotIn(session_id, body)
        self.assertIn("&quot;&gt;&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", body)

    def test_server_uses_ephemeral_loopback_port_and_rejects_other_binds(self) -> None:
        server = create_server(MemoryStore(), host="127.0.0.1", port=0)
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            self.assertGreater(server.server_address[1], 0)
        finally:
            server.server_close()

        for host in ("0.0.0.0", "192.0.2.10", "example.com", ""):
            with self.subTest(host=host), self.assertRaisesRegex(ValueError, "loopback"):
                create_server(MemoryStore(), host=host, port=0)


if __name__ == "__main__":
    unittest.main()
