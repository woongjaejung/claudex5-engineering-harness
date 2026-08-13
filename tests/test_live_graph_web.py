from __future__ import annotations

from contextlib import contextmanager
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.live_graph.sessions import SessionSelection
from scripts.live_graph.web import create_server


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
        self.snapshots_calls = 0

    def snapshots(self) -> list[dict]:
        self.snapshots_calls += 1
        return [] if self.snapshot is None else [self.snapshot]


class FlakyMemoryStore(MemoryStore):
    def __init__(self, snapshot: dict | None = SAMPLE_SNAPSHOT):
        super().__init__(snapshot)
        self.failures: list[Exception] = []

    def snapshots(self) -> list[dict]:
        self.snapshots_calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return [] if self.snapshot is None else [self.snapshot]


@contextmanager
def running_server(store: MemoryStore, selection: SessionSelection | None = None, **options: object):
    server = create_server(store, selection or SessionSelection.all(), host="127.0.0.1", port=0, **options)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def read_sse_frame(response) -> str:
    lines: list[str] = []
    while True:
        line = response.readline().decode("utf-8")
        if line == "\n":
            return "".join(lines)
        lines.append(line)


class WebDashboardTests(unittest.TestCase):
    def test_fixed_routes_serve_local_assets_with_security_headers(self) -> None:
        with running_server(MemoryStore()) as base_url:
            for path, expected_type in (
                ("/", "text/html"),
                ("/app.mjs", "text/javascript"),
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

    def test_snapshot_routes_accept_only_valid_logical_selections(self) -> None:
        store = MemoryStore()
        selected = dict(SAMPLE_SNAPSHOT, session_id="selected-session")
        store.snapshot = selected
        with running_server(store, SessionSelection.one("selected-session")) as base_url:
            with urlopen(base_url + "/api/snapshot?session=selected-session") as response:
                focused = json.loads(response.read().decode("utf-8"))
            with urlopen(base_url + "/api/snapshot?selection=all") as response:
                all_sessions = json.loads(response.read().decode("utf-8"))
            for query in ("", "?session=missing-session", "?session=bad%2Fid", "?selection=all&session=selected-session", "?selection=all&selection=all"):
                with self.subTest(query=query), self.assertRaises(HTTPError) as raised:
                    urlopen(base_url + "/api/snapshot" + query)
                error = raised.exception
                try:
                    self.assertEqual(error.code, 404 if query == "?session=missing-session" else 400)
                    self.assertEqual(error.read().decode("utf-8"), "Selected session unavailable.\n" if query == "?session=missing-session" else "Invalid selection.\n")
                finally:
                    error.close()

        self.assertEqual(focused["selection"], {"mode": "session", "session_id": "selected-session"})
        self.assertEqual(focused["projects"][0]["running"][0]["session_id"], "selected-session")
        self.assertEqual(all_sessions["selection"], {"mode": "all", "session_id": None})
        self.assertEqual(all_sessions["projects"][0]["running"][0]["session_id"], "selected-session")
        self.assertEqual(store.snapshots_calls, 3)

    def test_rejects_foreign_host_header_before_reading_selection_or_storage(self) -> None:
        store = MemoryStore()
        with running_server(store) as base_url:
            for path in ("/api/snapshot?selection=all", "/api/events?selection=all"):
                request = Request(base_url + path, headers={"Host": "attacker.example"})
                with self.subTest(path=path), self.assertRaises(HTTPError) as raised:
                    urlopen(request)
                error = raised.exception
                try:
                    self.assertEqual(error.code, 403)
                    self.assertEqual(error.read().decode("utf-8"), "Forbidden.\n")
                finally:
                    error.close()

        self.assertEqual(store.snapshots_calls, 0)

    def test_sse_sends_initial_changed_only_and_keepalive_frames(self) -> None:
        store = MemoryStore(dict(SAMPLE_SNAPSHOT, session_id="selected-session"))
        with running_server(
            store, SessionSelection.one("selected-session"), stream_interval=0.01, keepalive_interval=0.03,
        ) as base_url:
            response = urlopen(base_url + "/api/events?session=selected-session", timeout=2)
            try:
                self.assertEqual(response.headers["Content-Type"], "text/event-stream; charset=utf-8")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])
                self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
                self.assertIsNone(response.headers.get("Content-Length"))
                initial = read_sse_frame(response)
                self.assertTrue(initial.startswith("event: snapshot\ndata: "))
                initial_bundle = json.loads(initial.split("data: ", 1)[1])
                self.assertEqual(initial_bundle["selection"]["session_id"], "selected-session")
                self.assertEqual(read_sse_frame(response), ": keepalive\n")
                store.snapshot = dict(store.snapshot, sequence=4)
                changed = read_sse_frame(response)
                self.assertTrue(changed.startswith("event: snapshot\ndata: "))
                self.assertNotEqual(json.loads(changed.split("data: ", 1)[1])["revision"], initial_bundle["revision"])
            finally:
                response.close()

            with urlopen(base_url + "/api/events?session=selected-session", timeout=2) as second:
                self.assertTrue(read_sse_frame(second).startswith("event: snapshot\n"))
            with urlopen(base_url + "/api/snapshot?session=selected-session", timeout=2) as snapshot:
                self.assertEqual(snapshot.status, 200)

    def test_sse_degrades_once_recovers_and_fails_initial_read_without_headers(self) -> None:
        store = FlakyMemoryStore(dict(SAMPLE_SNAPSHOT, session_id="selected-session"))
        with running_server(
            store, SessionSelection.one("selected-session"), stream_interval=0.01, keepalive_interval=1,
        ) as base_url:
            response = urlopen(base_url + "/api/events?session=selected-session", timeout=2)
            try:
                first = read_sse_frame(response)
                first_revision = json.loads(first.split("data: ", 1)[1])["revision"]
                store.failures.append(TimeoutError("state database path /private"))
                self.assertEqual(read_sse_frame(response), "event: degraded\ndata: {\"status\":\"degraded\"}\n")
                store.snapshot = dict(store.snapshot, sequence=4)
                recovered = read_sse_frame(response)
                self.assertTrue(recovered.startswith("event: snapshot\n"))
                self.assertNotEqual(json.loads(recovered.split("data: ", 1)[1])["revision"], first_revision)
            finally:
                response.close()

        unavailable = FlakyMemoryStore()
        unavailable.failures.append(TimeoutError("private storage failure"))
        with running_server(unavailable, SessionSelection.all()) as base_url:
            with self.assertRaises(HTTPError) as raised:
                urlopen(base_url + "/api/events?selection=all", timeout=2)
            error = raised.exception
            try:
                self.assertEqual(error.code, 503)
                self.assertEqual(error.read().decode("utf-8"), "Dashboard state unavailable.\n")
                self.assertFalse(error.headers.get("Content-Type", "").startswith("text/event-stream"))
            finally:
                error.close()

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

    def test_static_page_does_not_embed_the_selection(self) -> None:
        with running_server(MemoryStore(), SessionSelection.one("selected-session")) as base_url:
            with urlopen(base_url + "/?session=selected-session") as response:
                body = response.read().decode("utf-8")

        self.assertNotIn("selected-session", body)

    def test_server_uses_ephemeral_loopback_port_and_rejects_other_binds(self) -> None:
        server = create_server(MemoryStore(), SessionSelection.all(), host="127.0.0.1", port=0)
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            self.assertGreater(server.server_address[1], 0)
        finally:
            server.server_close()

        for host in ("0.0.0.0", "192.0.2.10", "example.com", ""):
            with self.subTest(host=host), self.assertRaisesRegex(ValueError, "loopback"):
                create_server(MemoryStore(), SessionSelection.all(), host=host, port=0)


if __name__ == "__main__":
    unittest.main()
