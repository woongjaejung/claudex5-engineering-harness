"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const TERMINAL = new Set(["passed", "failed", "blocked", "skipped", "interrupted"]);
const SATISFIED = new Set(["passed", "skipped"]);
const STATES = new Set(["waiting", "running", ...TERMINAL]);
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
      if (candidate > (rank.get(successor) || 0)) { rank.set(successor, candidate); changed = true; }
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
  svg.setAttribute("viewBox", `0 0 ${Math.max(760, graph.ranks.size * 280 + 58)} ${Math.max(566, widestRank * 126 + 76)}`);
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
    svg.append(svgElement("path", {d: `M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`, class: `edge ${String(edge.kind || "contains").replace(/[^a-z_]/g, "")}`}));
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
    const meta = svgElement("text", {class: "node-meta", x: 16, y: 62});
    meta.textContent = clipped([node.model, node.effort].filter(Boolean).join(" · ") || state, 33);
    group.append(meta);
    svg.append(group);
  }
  byId("empty-state").classList.add("hidden");
  svg.classList.add("visible");
}

function updateSummary(snapshot) {
  const nodes = Object.values(snapshot.nodes || {});
  const complete = nodes.filter((node) => node && SATISFIED.has(node.state)).length;
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
    if (edge && edge.kind === "depends_on" && dependencies.has(String(edge.source))) dependencies.get(String(edge.source)).push(String(edge.target));
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

function focusedSnapshot(bundle) {
  for (const project of bundle.projects || []) {
    const snapshot = [...(project.running || []), ...(project.completed || [])][0];
    if (snapshot) return snapshot;
  }
  return null;
}

function setConnection(state, message) {
  byId("connection").dataset.state = state;
  byId("connection-text").textContent = message;
}

function applyBundle(bundle) {
  const snapshot = focusedSnapshot(bundle);
  if (!snapshot) {
    byId("empty-state").classList.remove("hidden");
    byId("graph").classList.remove("visible");
    return;
  }
  updateSummary(snapshot);
  drawGraph(snapshot);
}

function selectionQuery() {
  const params = new URLSearchParams(window.location.search);
  return params.get("selection") === "all" ? "selection=all" : `session=${encodeURIComponent(params.get("session") || "")}`;
}

function connect() {
  const source = new EventSource(`/api/events?${selectionQuery()}`);
  source.addEventListener("snapshot", (event) => {
    setConnection("connected", "LOCAL / CONNECTED");
    byId("degraded").classList.remove("warning");
    applyBundle(JSON.parse(event.data));
  });
  source.addEventListener("degraded", () => {
    byId("degraded").classList.add("warning");
    byId("degraded").textContent = "STATE READ DEGRADED";
  });
  source.onerror = () => setConnection("disconnected", "LOCAL / RECONNECTING");
}

connect();
