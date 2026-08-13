"""Loopback-only HTTP and SVG dashboard for Claudex5 live snapshots."""

from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import socket
from typing import Any
import webbrowser


CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'none'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'"
)


INDEX_HTML = """<!doctype html>
<html lang="en" data-session="{{SESSION_ID}}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Claudex5 Live Graph</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="/style.css">
  <script src="/app.js" defer></script>
</head>
<body>
  <div class="scanlines" aria-hidden="true"></div>
  <header class="masthead">
    <div class="identity">
      <span class="signal-mark" aria-hidden="true"></span>
      <div>
        <p class="eyebrow">CLAUDEX5 / LIVE ORCHESTRATION</p>
        <h1>Flight graph</h1>
      </div>
    </div>
    <div class="connection" id="connection" data-state="connecting" role="status" aria-live="polite">
      <span class="connection-light" aria-hidden="true"></span>
      <span id="connection-text">CONNECTING</span>
    </div>
  </header>

  <main>
    <section class="run-strip" aria-label="Current run summary">
      <div><span>RUN</span><strong id="run-id">Awaiting telemetry</strong></div>
      <div><span>PROJECT</span><strong id="project">—</strong></div>
      <div><span>STATE</span><strong id="run-state">—</strong></div>
      <div class="progress-cell">
        <span>PROGRESS</span><strong id="progress-text">0 / 0</strong>
        <div class="progress-track" aria-hidden="true"><i id="progress-bar"></i></div>
      </div>
    </section>

    <section class="workspace">
      <div class="graph-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">NODE / EDGE TELEMETRY</p>
            <h2>Active execution map</h2>
          </div>
          <p id="updated-at">No events received</p>
        </div>
        <div class="empty-state" id="empty-state">
          <div class="radar" aria-hidden="true"><i></i></div>
          <p>Waiting for a Claudex5 run</p>
          <small>Start a Claude Code session, then keep this page open.</small>
        </div>
        <svg id="graph" role="img" aria-label="Claudex5 task and agent dependency graph"></svg>
      </div>

      <aside>
        <section class="side-card">
          <p class="eyebrow">STATE INDEX</p>
          <h2>Signal legend</h2>
          <ul class="legend" aria-label="Node state colors">
            <li><i class="state-running"></i>Running</li>
            <li><i class="state-waiting"></i>Waiting</li>
            <li><i class="state-passed"></i>Passed</li>
            <li><i class="state-failed"></i>Failed</li>
            <li><i class="state-blocked"></i>Blocked</li>
            <li><i class="state-skipped"></i>Skipped</li>
            <li><i class="state-interrupted"></i>Interrupted</li>
          </ul>
        </section>
        <section class="side-card next-card">
          <p class="eyebrow">QUEUE</p>
          <h2>Next runnable</h2>
          <ol id="next-runnable"><li>Waiting for graph data</li></ol>
        </section>
        <section class="side-card privacy-card">
          <p class="eyebrow">LOCAL LINK</p>
          <h2>Private by design</h2>
          <p>Loopback only. Labels and lifecycle metadata are rendered; prompts, code, and credentials stay out.</p>
        </section>
      </aside>
    </section>
  </main>

  <footer>
    <span>1 SECOND REFRESH</span>
    <span>ZERO EXTERNAL ASSETS</span>
    <span id="degraded">EVENT LOG HEALTHY</span>
  </footer>
</body>
</html>
"""


STYLE_CSS = r"""
:root {
  color-scheme: dark;
  --ink: #e8eadf;
  --muted: #8c948c;
  --void: #080b0d;
  --panel: #101518;
  --panel-2: #151c1f;
  --line: #2c3738;
  --mint: #9be8c1;
  --orange: #ff7a45;
  --yellow: #e0c56d;
  --red: #ff5f5f;
  --blue: #6db8d6;
  --violet: #a38ad8;
  --node-width: 218px;
}

* { box-sizing: border-box; }

html, body { min-height: 100%; }

body {
  margin: 0;
  color: var(--ink);
  background:
    radial-gradient(circle at 14% 8%, rgba(155, 232, 193, .08), transparent 25rem),
    linear-gradient(rgba(255,255,255,.018) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.018) 1px, transparent 1px),
    var(--void);
  background-size: auto, 28px 28px, 28px 28px, auto;
  font-family: "Avenir Next", "Segoe UI", sans-serif;
  letter-spacing: .01em;
}

.scanlines {
  position: fixed;
  inset: 0;
  z-index: 20;
  pointer-events: none;
  opacity: .18;
  background: repeating-linear-gradient(0deg, transparent 0 3px, rgba(0,0,0,.24) 4px);
}

.masthead {
  min-height: 106px;
  padding: 24px clamp(22px, 4vw, 62px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--line);
  background: rgba(8, 11, 13, .82);
  backdrop-filter: blur(12px);
}

.identity { display: flex; align-items: center; gap: 17px; }

.signal-mark {
  width: 42px;
  aspect-ratio: 1;
  border: 1px solid var(--mint);
  transform: rotate(45deg);
  box-shadow: inset 0 0 0 8px var(--void), inset 0 0 0 9px rgba(155,232,193,.35), 0 0 24px rgba(155,232,193,.2);
}

.eyebrow {
  margin: 0 0 6px;
  color: var(--mint);
  font: 700 10px/1.2 "SFMono-Regular", Consolas, monospace;
  letter-spacing: .2em;
}

h1, h2 { margin: 0; font-weight: 500; }
h1 { font: 500 clamp(28px, 3vw, 43px)/.95 Georgia, serif; letter-spacing: -.035em; }
h2 { font-size: 18px; letter-spacing: -.02em; }

.connection {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 13px;
  border: 1px solid var(--line);
  color: var(--muted);
  font: 700 10px/1 "SFMono-Regular", Consolas, monospace;
  letter-spacing: .15em;
}

.connection-light { width: 8px; height: 8px; border-radius: 50%; background: var(--yellow); }
.connection[data-state="connected"] { color: var(--mint); border-color: rgba(155,232,193,.35); }
.connection[data-state="connected"] .connection-light { background: var(--mint); box-shadow: 0 0 12px var(--mint); }
.connection[data-state="disconnected"] { color: var(--red); border-color: rgba(255,95,95,.4); }
.connection[data-state="disconnected"] .connection-light { background: var(--red); animation: blink 1s steps(2) infinite; }

main { padding: 0 clamp(22px, 4vw, 62px) 48px; }

.run-strip {
  display: grid;
  grid-template-columns: 1fr 1.3fr .7fr 1.3fr;
  border: 1px solid var(--line);
  border-top: 0;
  background: rgba(16, 21, 24, .88);
}

.run-strip > div { min-width: 0; padding: 15px 18px; border-right: 1px solid var(--line); }
.run-strip > div:last-child { border-right: 0; }
.run-strip span, footer {
  color: var(--muted);
  font: 700 9px/1 "SFMono-Regular", Consolas, monospace;
  letter-spacing: .15em;
}
.run-strip strong { display: block; margin-top: 7px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.progress-track { height: 3px; margin-top: 9px; background: #252d2f; overflow: hidden; }
.progress-track i { display: block; width: 0; height: 100%; background: var(--mint); transition: width .35s ease; }

.workspace { display: grid; grid-template-columns: minmax(0, 1fr) 238px; gap: 18px; margin-top: 28px; }
.graph-panel, .side-card { border: 1px solid var(--line); background: rgba(16, 21, 24, .9); }
.graph-panel { position: relative; min-height: 635px; overflow: hidden; }
.graph-panel::before { content: ""; position: absolute; inset: 0; pointer-events: none; background: linear-gradient(135deg, rgba(155,232,193,.035), transparent 38%); }
.panel-heading { position: relative; z-index: 2; display: flex; justify-content: space-between; align-items: flex-end; padding: 22px 24px; border-bottom: 1px solid var(--line); }
.panel-heading > p { margin: 0; color: var(--muted); font: 10px/1.4 "SFMono-Regular", Consolas, monospace; }

#graph { display: none; width: 100%; min-height: 566px; }
#graph.visible { display: block; }
.edge { fill: none; stroke: #425051; stroke-width: 1.2; marker-end: url(#arrow); }
.edge.depends_on, .edge.gates, .edge.reviews { stroke: var(--yellow); stroke-dasharray: 5 5; }
.node-frame { fill: #12191b; stroke: #334042; stroke-width: 1; rx: 3; }
.node-accent { rx: 2; }
.node-label { fill: var(--ink); font: 600 12px "Avenir Next", "Segoe UI", sans-serif; }
.node-meta, .node-kind { fill: var(--muted); font: 9px "SFMono-Regular", Consolas, monospace; letter-spacing: .06em; }
.node-kind { fill: var(--mint); }
.node-running .node-frame { stroke: var(--mint); filter: drop-shadow(0 0 7px rgba(155,232,193,.18)); }
.node-running .node-accent, .state-running { background: var(--mint); fill: var(--mint); }
.node-waiting .node-accent, .state-waiting { background: var(--yellow); fill: var(--yellow); }
.node-passed .node-accent, .state-passed { background: #77c99b; fill: #77c99b; }
.node-failed .node-accent, .state-failed { background: var(--red); fill: var(--red); }
.node-blocked .node-accent, .state-blocked { background: var(--orange); fill: var(--orange); }
.node-skipped .node-accent, .state-skipped { background: #6d7778; fill: #6d7778; }
.node-interrupted .node-accent, .state-interrupted { background: var(--violet); fill: var(--violet); }

.empty-state { position: absolute; inset: 89px 0 0; display: grid; place-content: center; justify-items: center; text-align: center; color: var(--muted); }
.empty-state.hidden { display: none; }
.empty-state p { margin: 25px 0 6px; color: var(--ink); }
.empty-state small { max-width: 290px; line-height: 1.5; }
.radar { position: relative; width: 82px; height: 82px; border: 1px solid var(--line); border-radius: 50%; background: linear-gradient(90deg, transparent 49%, var(--line) 50%, transparent 51%), linear-gradient(transparent 49%, var(--line) 50%, transparent 51%); }
.radar::before { content: ""; position: absolute; inset: 20px; border: 1px solid var(--line); border-radius: 50%; }
.radar i { position: absolute; left: 50%; top: 50%; width: 36px; height: 1px; transform-origin: left; background: linear-gradient(90deg, var(--mint), transparent); animation: sweep 2.8s linear infinite; }

aside { display: flex; flex-direction: column; gap: 18px; }
.side-card { padding: 19px; }
.legend, #next-runnable { margin: 17px 0 0; padding: 0; list-style: none; }
.legend { display: grid; grid-template-columns: 1fr 1fr; gap: 13px 8px; color: var(--muted); font-size: 11px; }
.legend i { display: inline-block; width: 7px; height: 7px; margin-right: 7px; border-radius: 50%; }
#next-runnable { counter-reset: queue; }
#next-runnable li { position: relative; padding: 10px 0 10px 28px; border-bottom: 1px solid var(--line); color: #c7cbc3; font-size: 11px; line-height: 1.35; }
#next-runnable li::before { counter-increment: queue; content: counter(queue, decimal-leading-zero); position: absolute; left: 0; color: var(--orange); font: 9px/1.5 "SFMono-Regular", Consolas, monospace; }
.privacy-card { margin-top: auto; border-color: rgba(155,232,193,.22); }
.privacy-card p:last-child { margin: 14px 0 0; color: var(--muted); font-size: 11px; line-height: 1.55; }

footer { display: flex; gap: 26px; padding: 17px clamp(22px, 4vw, 62px); border-top: 1px solid var(--line); background: #07090a; }
footer span:last-child { margin-left: auto; }
#degraded.warning { color: var(--orange); }

@keyframes sweep { to { transform: rotate(360deg); } }
@keyframes blink { 50% { opacity: .2; } }

@media (max-width: 900px) {
  .run-strip { grid-template-columns: 1fr 1fr; }
  .run-strip > div:nth-child(2) { border-right: 0; }
  .run-strip > div:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
  .workspace { grid-template-columns: 1fr; }
  aside { display: grid; grid-template-columns: repeat(3, 1fr); }
  .privacy-card { margin-top: 0; }
}

@media (max-width: 620px) {
  .masthead { align-items: flex-start; gap: 22px; }
  .signal-mark { display: none; }
  .connection { padding: 9px; }
  .run-strip { grid-template-columns: 1fr; }
  .run-strip > div { border-right: 0; border-bottom: 1px solid var(--line); }
  aside { grid-template-columns: 1fr; }
  footer { flex-wrap: wrap; }
  footer span:last-child { margin-left: 0; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
"""


APP_JS = r"""
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const TERMINAL = new Set(["passed", "failed", "blocked", "skipped", "interrupted"]);
const SATISFIED = new Set(["passed", "skipped"]);
const STATES = new Set(["waiting", "running", ...TERMINAL]);
let lastSnapshot = null;

const byId = (id) => document.getElementById(id);

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

function clipped(value, limit) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 1))}…`;
}

function orderedGraph(snapshot) {
  const nodes = Object.values(snapshot.nodes || {}).filter((node) => node && node.id);
  nodes.sort((a, b) => (Number(a.sequence || 0) - Number(b.sequence || 0)) || String(a.id).localeCompare(String(b.id)));
  const ids = new Set(nodes.map((node) => String(node.id)));
  const edges = Object.values(snapshot.edges || {}).filter((edge) => edge && ids.has(String(edge.source)) && ids.has(String(edge.target)));
  edges.sort((a, b) => String(a.id || "").localeCompare(String(b.id || "")));

  const rank = new Map(nodes.map((node) => [String(node.id), 0]));
  for (let pass = 0; pass < nodes.length; pass += 1) {
    let changed = false;
    for (const edge of edges) {
      const source = String(edge.source);
      const target = String(edge.target);
      const predecessor = edge.kind === "depends_on" ? target : source;
      const successor = edge.kind === "depends_on" ? source : target;
      const candidate = Math.min(nodes.length - 1, (rank.get(predecessor) || 0) + 1);
      if (candidate > (rank.get(successor) || 0)) {
        rank.set(successor, candidate);
        changed = true;
      }
    }
    if (!changed) break;
  }

  const ranks = new Map();
  for (const node of nodes) {
    const value = rank.get(String(node.id)) || 0;
    if (!ranks.has(value)) ranks.set(value, []);
    ranks.get(value).push(node);
  }
  return {nodes, edges, ranks};
}

function nodePosition(graph, nodeId) {
  for (const [rank, nodes] of graph.ranks.entries()) {
    const index = nodes.findIndex((node) => String(node.id) === nodeId);
    if (index >= 0) return {x: 48 + rank * 280, y: 48 + index * 126};
  }
  return {x: 48, y: 48};
}

function drawGraph(snapshot) {
  const graph = orderedGraph(snapshot);
  const svg = byId("graph");
  svg.replaceChildren();

  if (!graph.nodes.length) {
    svg.classList.remove("visible");
    byId("empty-state").classList.remove("hidden");
    return;
  }

  const widestRank = Math.max(1, ...Array.from(graph.ranks.values(), (nodes) => nodes.length));
  const width = Math.max(760, graph.ranks.size * 280 + 58);
  const height = Math.max(566, widestRank * 126 + 76);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  const definitions = svgElement("defs");
  const marker = svgElement("marker", {id: "arrow", viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse"});
  marker.append(svgElement("path", {d: "M 0 0 L 8 4 L 0 8 z", fill: "#596667"}));
  definitions.append(marker);
  svg.append(definitions);

  for (const edge of graph.edges) {
    const from = nodePosition(graph, String(edge.source));
    const to = nodePosition(graph, String(edge.target));
    const startX = from.x + 218;
    const startY = from.y + 39;
    const endX = to.x;
    const endY = to.y + 39;
    const bend = Math.max(35, (endX - startX) / 2);
    const path = svgElement("path", {
      d: `M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`,
      class: `edge ${String(edge.kind || "contains").replace(/[^a-z_]/g, "")}`,
    });
    svg.append(path);
  }

  for (const node of graph.nodes) {
    const state = STATES.has(String(node.state)) ? String(node.state) : "waiting";
    const position = nodePosition(graph, String(node.id));
    const group = svgElement("g", {class: `node node-${state}`, transform: `translate(${position.x} ${position.y})`});
    group.append(svgElement("rect", {class: "node-frame", width: 218, height: 78}));
    group.append(svgElement("rect", {class: "node-accent", x: 0, y: 0, width: 4, height: 78}));

    const kind = svgElement("text", {class: "node-kind", x: 16, y: 19});
    kind.textContent = clipped(node.kind || "node", 24).toUpperCase();
    group.append(kind);

    const label = svgElement("text", {class: "node-label", x: 16, y: 41});
    label.textContent = clipped(node.label || node.id, 29);
    group.append(label);

    const model = [node.model, node.effort].filter(Boolean).join(" · ");
    const meta = svgElement("text", {class: "node-meta", x: 16, y: 62});
    meta.textContent = clipped(model || state, 33);
    group.append(meta);
    svg.append(group);
  }

  byId("empty-state").classList.add("hidden");
  svg.classList.add("visible");
}

function updateSummary(snapshot) {
  const nodes = Object.values(snapshot.nodes || {});
  const complete = nodes.filter((node) => node && ["passed", "skipped"].includes(node.state)).length;
  byId("run-id").textContent = clipped(snapshot.session_id || "unknown", 44);
  const parts = String(snapshot.cwd || "unknown").split(/[\\/]/).filter(Boolean);
  byId("project").textContent = clipped(parts.at(-1) || "/", 40);
  byId("run-state").textContent = String(snapshot.status || "unknown").toUpperCase();
  byId("progress-text").textContent = `${complete} / ${nodes.length}`;
  byId("progress-bar").style.width = `${nodes.length ? (complete / nodes.length) * 100 : 0}%`;
  byId("updated-at").textContent = snapshot.updated_at ? `UPDATED ${snapshot.updated_at}` : "UPDATE TIME UNKNOWN";
  byId("degraded").textContent = snapshot.degraded ? "EVENT LOG DEGRADED" : "EVENT LOG HEALTHY";
  byId("degraded").classList.toggle("warning", Boolean(snapshot.degraded));

  const dependencies = new Map(nodes.map((node) => [String(node.id), []]));
  for (const edge of Object.values(snapshot.edges || {})) {
    if (edge && edge.kind === "depends_on" && dependencies.has(String(edge.source))) {
      dependencies.get(String(edge.source)).push(String(edge.target));
    }
  }
  const stateById = new Map(nodes.map((node) => [String(node.id), String(node.state)]));
  const runnable = nodes.filter((node) => node && node.state === "waiting" && (dependencies.get(String(node.id)) || []).every((source) => SATISFIED.has(stateById.get(source))));
  const list = byId("next-runnable");
  list.replaceChildren();
  for (const node of runnable.slice(0, 5)) {
    const item = document.createElement("li");
    item.textContent = clipped(node.label || node.id, 54);
    list.append(item);
  }
  if (!runnable.length) {
    const item = document.createElement("li");
    item.textContent = nodes.some((node) => node && node.state === "running") ? "Active work in progress" : "No runnable nodes";
    list.append(item);
  }
}

function setConnection(state, message) {
  byId("connection").dataset.state = state;
  byId("connection-text").textContent = message;
}

async function poll() {
  try {
    const response = await fetch("/api/snapshot", {cache: "no-store", credentials: "same-origin"});
    if (!response.ok) throw new Error("snapshot unavailable");
    const snapshot = await response.json();
    setConnection("connected", "LOCAL / CONNECTED");
    if (snapshot) {
      lastSnapshot = snapshot;
      updateSummary(snapshot);
      drawGraph(snapshot);
    } else if (!lastSnapshot) {
      byId("empty-state").classList.remove("hidden");
      byId("graph").classList.remove("visible");
    }
  } catch (_error) {
    setConnection("disconnected", "LOCAL / DISCONNECTED");
  }
}

poll();
window.setInterval(poll, 1000);
"""


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def make_handler(store: Any, session_id: str | None = None) -> type[BaseHTTPRequestHandler]:
    """Build a fixed-route request handler for one store and optional run."""
    escaped_session = escape(session_id if session_id is not None else "latest", quote=True)
    index = INDEX_HTML.replace("{{SESSION_ID}}", escaped_session).encode("utf-8")
    assets: dict[str, tuple[str, bytes]] = {
        "/": ("text/html; charset=utf-8", index),
        "/app.js": ("text/javascript; charset=utf-8", APP_JS.encode("utf-8")),
        "/style.css": ("text/css; charset=utf-8", STYLE_CSS.encode("utf-8")),
    }

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "Claudex5Dashboard/1"
        sys_version = ""

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path in assets:
                content_type, body = assets[self.path]
                self._send(200, content_type, body)
                return
            if self.path == "/api/snapshot":
                try:
                    snapshot = store.load(session_id) if session_id is not None else store.latest()
                    body = json.dumps(
                        snapshot,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                except Exception:
                    self._send(503, "text/plain; charset=utf-8", b"Dashboard state unavailable.\n")
                    return
                self._send(200, "application/json; charset=utf-8", body)
                return
            self._send(404, "text/plain; charset=utf-8", b"Not found.\n")

        def log_message(self, _format: str, *args: object) -> None:
            del args

    return DashboardHandler


class _DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _IPv6DashboardServer(_DashboardServer):
    address_family = socket.AF_INET6


def create_server(
    store: Any,
    session_id: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Bind a dashboard server to a validated loopback address."""
    if not isinstance(host, str) or not _is_loopback(host):
        raise ValueError("dashboard host must be a loopback address")
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError("dashboard port must be between 0 and 65535")
    server_type = _IPv6DashboardServer if ":" in host else _DashboardServer
    return server_type((host, port), make_handler(store, session_id))


def serve_dashboard(
    store: Any,
    session_id: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> int:
    """Serve the dashboard until interrupted, returning a conventional status."""
    server = create_server(store, session_id=session_id, host=host, port=port)
    bound_host, bound_port = server.server_address[:2]
    display_host = f"[{bound_host}]" if ":" in str(bound_host) else bound_host
    url = f"http://{display_host}:{bound_port}/"
    print(f"Claudex5 dashboard: {url}", flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            print("Browser launch failed; open the URL above manually.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0
