"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const TERMINAL = new Set(["passed", "failed", "blocked", "skipped", "interrupted"]);
const SATISFIED = new Set(["passed", "skipped"]);
const byId = (id) => document.getElementById(id);
let source;

function setConnection(state, message) {
  byId("connection").dataset.state = state;
  byId("connection-text").textContent = message;
}

function sessions(bundle) {
  return (bundle.projects || []).flatMap((project) => [...(project.running || []), ...(project.completed || [])]);
}

function update(bundle) {
  const runs = sessions(bundle);
  const snapshot = runs[0];
  if (!snapshot) {
    byId("empty-state").classList.remove("hidden");
    byId("graph").classList.remove("visible");
    return;
  }
  const nodes = Object.values(snapshot.nodes || {});
  const active = nodes.filter((node) => !TERMINAL.has(node.state)).length;
  byId("run-id").textContent = bundle.selection.mode === "all" ? `${runs.length} sessions` : snapshot.session_id;
  byId("project").textContent = snapshot.cwd || "—";
  byId("run-state").textContent = snapshot.status || "—";
  byId("progress-text").textContent = `${nodes.length - active} / ${nodes.length}`;
  byId("progress-bar").style.width = `${nodes.length ? ((nodes.length - active) / nodes.length) * 100 : 0}%`;
  byId("updated-at").textContent = snapshot.updated_at || "Live update";
  byId("empty-state").classList.add("hidden");
  drawGraph(snapshot);
  renderNext(snapshot);
}

function drawGraph(snapshot) {
  const graph = byId("graph");
  graph.replaceChildren();
  const nodes = Object.values(snapshot.nodes || {}).filter((node) => node && node.id);
  nodes.sort((a, b) => Number(a.sequence || 0) - Number(b.sequence || 0));
  graph.setAttribute("viewBox", `0 0 720 ${Math.max(140, nodes.length * 70 + 30)}`);
  nodes.forEach((node, index) => {
    const group = document.createElementNS(SVG_NS, "g");
    const rect = document.createElementNS(SVG_NS, "rect");
    rect.setAttribute("x", "30"); rect.setAttribute("y", String(20 + index * 70)); rect.setAttribute("width", "660"); rect.setAttribute("height", "52");
    rect.setAttribute("fill", "#12191b"); rect.setAttribute("stroke", node.state === "running" ? "#9be8c1" : "#334042");
    const label = document.createElementNS(SVG_NS, "text");
    label.setAttribute("x", "48"); label.setAttribute("y", String(51 + index * 70)); label.setAttribute("fill", "#e8eadf"); label.textContent = `${node.kind || "node"}: ${node.label || node.id}`;
    group.append(rect, label); graph.append(group);
  });
  graph.classList.add("visible");
}

function renderNext(snapshot) {
  const nodes = Object.values(snapshot.nodes || {});
  const edges = Object.values(snapshot.edges || {});
  const stateById = new Map(nodes.map((node) => [node.id, node.state]));
  const ready = nodes.filter((node) => node.state === "waiting" && edges.filter((edge) => edge.target === node.id).every((edge) => {
    const source = edge.source;
    return SATISFIED.has(stateById.get(source));
  }));
  const list = byId("next-runnable"); list.replaceChildren();
  for (const node of ready.slice(0, 5)) { const item = document.createElement("li"); item.textContent = node.label || node.id; list.append(item); }
  if (!ready.length) { const item = document.createElement("li"); item.textContent = "No runnable nodes"; list.append(item); }
}

function selectionQuery() {
  const params = new URLSearchParams(window.location.search);
  return params.get("selection") === "all" ? "selection=all" : `session=${encodeURIComponent(params.get("session") || "")}`;
}

function connect() {
  source = new EventSource(`/api/events?${selectionQuery()}`);
  source.addEventListener("snapshot", (event) => { setConnection("connected", "LOCAL / CONNECTED"); byId("degraded").classList.remove("warning"); byId("degraded").textContent = "EVENT LOG HEALTHY"; update(JSON.parse(event.data)); });
  source.addEventListener("degraded", () => { byId("degraded").classList.add("warning"); byId("degraded").textContent = "STATE READ DEGRADED"; });
  source.onerror = () => setConnection("disconnected", "LOCAL / RECONNECTING");
}

connect();
