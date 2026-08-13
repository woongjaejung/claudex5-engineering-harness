from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import subprocess
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

    def test_fixed_page_retains_focused_graph_summary_and_state_regions(self) -> None:
        html = (ASSET_DIRECTORY / "index.html").read_text(encoding="utf-8")
        for marker in ("scanlines", "identity", "state-running", "state-interrupted", "privacy-card", 'id="graph"', 'id="next-runnable"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)
        css = (ASSET_DIRECTORY / "style.css").read_text(encoding="utf-8")
        for selector in (".edge.depends_on", ".node-running .node-frame", ".node-accent", ".state-interrupted"):
            with self.subTest(selector=selector):
                self.assertIn(selector, css)

    def test_graph_prerequisites_use_only_satisfied_states(self) -> None:
        app = (ASSET_DIRECTORY / "app.mjs").read_text(encoding="utf-8")
        self.assertIn('const SATISFIED = new Set(["passed", "skipped"]);', app)
        self.assertIn("SATISFIED.has(stateById.get(source))", app)
        self.assertNotIn("TERMINAL.has(stateById.get(source))", app)

    def test_focused_snapshot_event_renders_svg_edges_status_metadata_and_runnable_nodes(self) -> None:
        bundle = {
            "selection": {"mode": "session", "session_id": "selected-session"},
            "projects": [{"cwd": "/work", "running": [{
                "session_id": "selected-session", "cwd": "/work", "status": "running",
                "nodes": {
                    "task:done": {"id": "task:done", "kind": "task", "label": "Completed prerequisite", "state": "passed", "sequence": 1},
                    "agent:impl": {"id": "agent:impl", "kind": "claude_agent", "label": "Implement dashboard", "state": "running", "model": "claude-sonnet-5", "effort": "high", "sequence": 2},
                    "task:next": {"id": "task:next", "kind": "task", "label": "Run quality checks", "state": "waiting", "sequence": 3},
                },
                "edges": {"dependency": {"id": "dependency", "source": "task:next", "target": "task:done", "kind": "depends_on"}},
            }], "completed": []}],
        }
        script = """
class Element {
  constructor() { this.children = []; this.attributes = {}; this.dataset = {}; this.style = {}; this.textContent = \"\"; this.classList = { values: new Set(), add: (...v) => v.forEach((x) => this.classList.values.add(x)), remove: (...v) => v.forEach((x) => this.classList.values.delete(x)), toggle: (v, on) => on ? this.classList.values.add(v) : this.classList.values.delete(v) }; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
}
const ids = new Map([\"connection\", \"connection-text\", \"run-id\", \"project\", \"run-state\", \"progress-text\", \"progress-bar\", \"updated-at\", \"degraded\", \"empty-state\", \"graph\", \"next-runnable\"].map((id) => [id, new Element()]));
globalThis.document = { getElementById: (id) => ids.get(id), createElementNS: () => new Element(), createElement: () => new Element() };
globalThis.window = { location: { search: "?session=selected-session" } };
globalThis.EventSource = class { constructor() { this.listeners = new Map(); globalThis.source = this; } addEventListener(name, callback) { this.listeners.set(name, callback); } };
await import(\"./scripts/live_graph/assets/app.mjs\");
source.listeners.get(\"snapshot\")({ data: process.env.BUNDLE });
const graph = ids.get(\"graph\");
console.log(JSON.stringify({ edge: graph.children[1].attributes.class, nodes: graph.children.slice(2).map((node) => ({ className: node.attributes.class, meta: node.children[4].textContent })), next: ids.get(\"next-runnable\").children.map((node) => node.textContent) }));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ASSET_DIRECTORY.parents[2], env={**__import__("os").environ, "BUNDLE": json.dumps(bundle)},
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = json.loads(result.stdout)
        self.assertEqual(rendered["edge"], "edge depends_on")
        self.assertIn({"className": "node node-running", "meta": "claude-sonnet-5 · high"}, rendered["nodes"])
        self.assertEqual(rendered["next"], ["Run quality checks"])


if __name__ == "__main__":
    unittest.main()
