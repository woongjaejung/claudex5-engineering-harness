from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import threading
import unittest
from urllib.request import urlopen

from scripts.live_graph.sessions import SessionSelection
from scripts.live_graph.web import create_server


ASSET_DIRECTORY = Path(__file__).parents[1] / "scripts" / "live_graph" / "assets"


class MemoryStore:
    def snapshots(self) -> list[dict[str, object]]:
        return []


@contextmanager
def running_server():
    server = create_server(MemoryStore(), SessionSelection.all(), host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


class WebDashboardAssetTests(unittest.TestCase):
    def test_fixed_assets_are_local_and_html_references_only_them(self) -> None:
        expected = {
            "index.html": "text/html",
            "style.css": "text/css",
            "app.mjs": "text/javascript",
        }
        contents = {
            name: (ASSET_DIRECTORY / name).read_text(encoding="utf-8")
            for name in expected
        }
        html = contents["index.html"]
        self.assertEqual(re.findall(r'(?:href|src)="([^"]+)"', html), ["data:,", "/style.css", "/app.mjs"])
        self.assertNotIn("<script>", html)
        for content in contents.values():
            external_references = re.sub(r"https?://www\.w3\.org/2000/svg", "", content)
            self.assertNotRegex(external_references, r"https?://|//[^\n]*\b(?:analytics|tracking)\b")

        with running_server() as base_url:
            for path, content_type in (("/", expected["index.html"]), ("/style.css", expected["style.css"]), ("/app.mjs", expected["app.mjs"])):
                with self.subTest(path=path), urlopen(base_url + path) as response:
                    self.assertTrue(response.headers["Content-Type"].startswith(content_type))
                    self.assertTrue(response.read())

    def test_graph_prerequisites_use_only_satisfied_states(self) -> None:
        app = (ASSET_DIRECTORY / "app.mjs").read_text(encoding="utf-8")
        self.assertIn('const SATISFIED = new Set(["passed", "skipped"]);', app)
        self.assertIn("SATISFIED.has(stateById.get(source))", app)
        self.assertNotIn("TERMINAL.has(stateById.get(source))", app)


if __name__ == "__main__":
    unittest.main()
