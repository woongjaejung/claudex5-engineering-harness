"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const TERMINAL = new Set(["passed", "failed", "blocked", "skipped", "interrupted"]);
const SATISFIED = new Set(["passed", "skipped"]);
const STATES = new Set(["waiting", "running", ...TERMINAL]);
const byId = (id) => document.getElementById(id);

function safeText(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function clipped(value, limit) {
  const text = safeText(value);
  return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 1))}…`;
}

function parseTime(value) {
  const milliseconds = Date.parse(String(value || ""));
  return Number.isFinite(milliseconds) ? milliseconds : null;
}

export function formatDuration(startedAt, now = new Date()) {
  const start = parseTime(startedAt);
  const finish = now instanceof Date ? now.getTime() : (Number.isFinite(Number(now)) ? Number(now) : parseTime(now));
  if (start === null || !Number.isFinite(finish)) return "—";
  const seconds = Math.max(0, Math.floor((finish - start) / 1000));
  const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  return `${hours}:${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatAge(updatedAt, now = new Date()) {
  const updated = parseTime(updatedAt);
  if (updated === null) return "age unknown";
  const seconds = Math.max(0, Math.floor((now.getTime() - updated) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function progress(snapshot) {
  const nodes = Object.values(snapshot?.nodes || {}).filter(Boolean);
  return {complete: nodes.filter((node) => SATISFIED.has(String(node.state))).length, total: nodes.length};
}

function sessionView(snapshot, now) {
  const state = safeText(snapshot.status || "unknown");
  const counts = progress(snapshot);
  return {
    snapshot,
    sessionId: safeText(snapshot.session_id),
    title: safeText(snapshot.title || snapshot.session_id || "Untitled session"),
    state,
    progress: counts,
    updatedAge: formatAge(snapshot.updated_at, now),
    elapsed: formatDuration(snapshot.started_at || snapshot.created_at || snapshot.updated_at, state === "running" ? now : (snapshot.finished_at || snapshot.updated_at)),
    mini: sessionMiniModel(snapshot),
  };
}

export function sessionMiniModel(snapshot) {
  const result = {running: 0, waiting: 0, terminal: 0};
  for (const node of Object.values(snapshot?.nodes || {})) {
    if (node?.state === "running") result.running += 1;
    else if (node?.state === "waiting") result.waiting += 1;
    else if (node) result.terminal += 1;
  }
  return result;
}

export function buildAllViewModel(bundle, now = new Date()) {
  const projects = Array.isArray(bundle?.projects) ? bundle.projects : [];
  return {
    projects: projects.map((project) => ({
      cwd: safeText(project.cwd || "/"),
      running: (Array.isArray(project.running) ? project.running : []).map((snapshot) => sessionView(snapshot, now)),
      completed: (Array.isArray(project.completed) ? project.completed : []).map((snapshot) => sessionView(snapshot, now)),
      completedCollapsed: true,
    })).sort((left, right) => left.cwd.localeCompare(right.cwd)),
  };
}

export function canApplyPollResult(currentGeneration, capturedGeneration, streamHealthy) {
  return currentGeneration === capturedGeneration && !streamHealthy;
}

function normaliseQuery(query) {
  return String(query || "selection=all");
}

export function createTransport({EventSourceImpl, fetchImpl, timers = globalThis, onBundle = () => {}, onConnection = () => {}, onElapsed = () => {}, onInitialFailure = () => {}} = {}) {
  let selectionGeneration = 0;
  let stream = null;
  let streamHealthy = false;
  let fallbackTimer = null;
  let retryTimer = null;
  let elapsedTimer = null;
  let query = "selection=all";
  let stopped = true;
  let sourceAttempt = 0;
  let activeSourceAttempt = 0;
  let pollAttempt = 0;
  let pollInFlight = false;

  const clear = (id) => { if (id !== null) timers.clearTimeout(id); };
  const clearTimers = () => { clear(fallbackTimer); clear(retryTimer); clear(elapsedTimer); fallbackTimer = retryTimer = elapsedTimer = null; };
  const closeStream = () => { activeSourceAttempt = ++sourceAttempt; if (stream && typeof stream.close === "function") stream.close(); stream = null; };
  const scheduleElapsed = () => {
    clear(elapsedTimer);
    elapsedTimer = timers.setTimeout(() => { if (!stopped) { onElapsed(); scheduleElapsed(); } }, 1000);
  };
  const scheduleRetry = (generation) => {
    clear(retryTimer);
    retryTimer = timers.setTimeout(() => {
      if (generation !== selectionGeneration || stopped || streamHealthy) return;
      openEventSource(generation);
      if (!streamHealthy) scheduleRetry(generation);
    }, 5000);
  };
  const poll = (generation) => {
    if (generation !== selectionGeneration || stopped || pollInFlight) return;
    const attempt = ++pollAttempt;
    pollInFlight = true;
    Promise.resolve(fetchImpl?.(`/api/snapshot?${query}`)).then(async (response) => {
      if (!response?.ok || !canApplyPollResult(selectionGeneration, generation, streamHealthy)) return;
      const bundle = await response.json();
      if (attempt !== pollAttempt || !canApplyPollResult(selectionGeneration, generation, streamHealthy) || stopped) return;
      onBundle(bundle, {source: "poll", generation});
    }).catch(() => {}).finally(() => {
      pollInFlight = false;
      if (attempt === pollAttempt && generation === selectionGeneration && !stopped && !streamHealthy) {
        clear(fallbackTimer);
        fallbackTimer = timers.setTimeout(() => poll(generation), 5000);
      }
    });
  };
  const startFallbackPolling = (generation, immediate = false) => {
    if (generation !== selectionGeneration || stopped || streamHealthy) return;
    clear(fallbackTimer); fallbackTimer = null;
    if (immediate) poll(generation);
    else fallbackTimer = timers.setTimeout(() => poll(generation), 5000);
  };
  const healthySnapshot = (event, generation, source, attempt) => {
    if (generation !== selectionGeneration || stopped || stream !== source || activeSourceAttempt !== attempt) return;
    try {
      const bundle = JSON.parse(event.data);
      streamHealthy = true;
      clear(fallbackTimer); fallbackTimer = null;
      clear(retryTimer); retryTimer = null;
      onConnection("connected");
      onBundle(bundle, {source: "sse", generation});
    } catch { /* malformed telemetry never replaces the visible bundle */ }
  };
  const openEventSource = (generation) => {
    if (generation !== selectionGeneration || stopped || stream) return;
    if (typeof EventSourceImpl !== "function") { startFallbackPolling(generation, true); scheduleRetry(generation); return; }
    let source;
    const attempt = ++sourceAttempt;
    try { source = new EventSourceImpl(`/api/events?${query}`); stream = source; activeSourceAttempt = attempt; }
    catch { stream = null; startFallbackPolling(generation, true); scheduleRetry(generation); return; }
    source.addEventListener("snapshot", (event) => healthySnapshot(event, generation, source, attempt));
    source.addEventListener("degraded", () => {
      if (generation === selectionGeneration && !stopped && stream === source && activeSourceAttempt === attempt) onConnection("degraded");
    });
    const fail = () => {
      if (generation !== selectionGeneration || stopped || stream !== source || activeSourceAttempt !== attempt) return;
      const initial = !streamHealthy;
      closeStream(); streamHealthy = false;
      onConnection("reconnecting");
      startFallbackPolling(generation, false);
      scheduleRetry(generation);
      if (initial) onInitialFailure(generation);
    };
    source.addEventListener("error", fail);
  };
  return {
    open(nextQuery, generation) {
      stopped = false; query = normaliseQuery(nextQuery); selectionGeneration = generation;
      pollAttempt += 1; closeStream(); clearTimers(); streamHealthy = false;
      onConnection("connecting"); scheduleElapsed(); openEventSource(generation);
    },
    close() { stopped = true; pollAttempt += 1; closeStream(); clearTimers(); streamHealthy = false; },
    startFallbackPolling: (generation, immediate = true) => startFallbackPolling(generation, immediate),
    state: () => ({generation: selectionGeneration, activeStreams: stream ? 1 : 0, streamHealthy, fallbackPolling: fallbackTimer !== null, retryPending: retryTimer !== null}),
  };
}

export function createSelectionController({fetchImpl, transport, apply = () => {}, sync = () => {}, refreshCatalog = () => {}, onError = () => {}, clearError = () => {}} = {}) {
  let selectionGeneration = 0;
  let selectionAttemptGeneration = 0;
  let query = "selection=all";
  let bundle = null;
  let previous = null;
  let candidateController = null;
  let candidateAwaitingFirstSnapshot = false;
  const commit = (nextQuery, nextBundle) => {
    previous = bundle ? {query, bundle} : null;
    selectionGeneration += 1; query = normaliseQuery(nextQuery); bundle = nextBundle;
    candidateAwaitingFirstSnapshot = true;
    transport.close(); sync(query); refreshCatalog(bundle.catalog || [], query); apply(bundle); clearError(); transport.open(query, selectionGeneration);
  };
  return {
    seed(initialQuery, initialBundle) {
      query = normaliseQuery(initialQuery); bundle = initialBundle; selectionGeneration += 1;
      previous = null; candidateAwaitingFirstSnapshot = false;
      sync(query); refreshCatalog(bundle.catalog || [], query); apply(bundle); clearError(); transport.open(query, selectionGeneration);
    },
    async select(nextQuery) {
      const candidate = normaliseQuery(nextQuery);
      const attempt = ++selectionAttemptGeneration;
      if (candidateController?.abort) candidateController.abort();
      candidateController = typeof AbortController === "function" ? new AbortController() : null;
      let nextBundle;
      try {
        const response = await fetchImpl(`/api/snapshot?${candidate}`, candidateController ? {signal: candidateController.signal} : {});
        if (!response?.ok) throw new Error("selection unavailable");
        nextBundle = await response.json();
      } catch {
        if (attempt === selectionAttemptGeneration) { sync(query); onError("Selection unavailable"); }
        return false;
      }
      if (attempt !== selectionAttemptGeneration) return false;
      commit(candidate, nextBundle); return true;
    },
    acceptStreamSnapshot(generation, acceptedBundle = null) {
      if (generation !== selectionGeneration) return false;
      candidateAwaitingFirstSnapshot = false; previous = null;
      if (acceptedBundle) { bundle = acceptedBundle; refreshCatalog(bundle.catalog || [], query); apply(bundle); }
      clearError(); return true;
    },
    async initialStreamFailed(generation = selectionGeneration) {
      const failedQuery = query;
      let response;
      try { response = await fetchImpl(`/api/snapshot?${failedQuery}`); } catch { return; }
      if (generation !== selectionGeneration || !candidateAwaitingFirstSnapshot || response?.status !== 404 || !previous) return;
      const restore = previous; previous = null; selectionGeneration += 1; query = restore.query; bundle = restore.bundle;
      candidateAwaitingFirstSnapshot = false;
      transport.close(); sync(query); refreshCatalog(bundle.catalog || [], query); apply(bundle); clearError(); transport.open(query, selectionGeneration);
    },
    state: () => ({query, bundle, selectionGeneration, selectionAttemptGeneration, candidateAwaitingFirstSnapshot}),
  };
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

function orderedGraph(snapshot) {
  const nodes = Object.values(snapshot.nodes || {}).filter((node) => node && node.id).sort((a, b) => (Number(a.sequence || 0) - Number(b.sequence || 0)) || String(a.id).localeCompare(String(b.id)));
  const ids = new Set(nodes.map((node) => String(node.id)));
  const edges = Object.values(snapshot.edges || {}).filter((edge) => edge && ids.has(String(edge.source)) && ids.has(String(edge.target))).sort((a, b) => String(a.id || "").localeCompare(String(b.id || "")));
  const ranks = new Map(nodes.map((node) => [String(node.id), 0]));
  for (let pass = 0; pass < nodes.length; pass += 1) for (const edge of edges) {
    const predecessor = edge.kind === "depends_on" ? String(edge.target) : String(edge.source);
    const successor = edge.kind === "depends_on" ? String(edge.source) : String(edge.target);
    ranks.set(successor, Math.max(ranks.get(successor) || 0, Math.min(nodes.length - 1, (ranks.get(predecessor) || 0) + 1)));
  }
  const groups = new Map();
  nodes.forEach((node) => { const rank = ranks.get(String(node.id)) || 0; if (!groups.has(rank)) groups.set(rank, []); groups.get(rank).push(node); });
  return {nodes, edges, ranks: groups};
}

function nodePosition(graph, nodeId) {
  for (const [rank, nodes] of graph.ranks) { const index = nodes.findIndex((node) => String(node.id) === nodeId); if (index >= 0) return {x: 30 + rank * 230, y: 30 + index * 94}; }
  return {x: 30, y: 30};
}

function drawGraph(snapshot, onNode) {
  const graph = orderedGraph(snapshot); const svg = byId("graph"); svg.replaceChildren();
  if (!graph.nodes.length) { svg.classList.remove("visible"); return; }
  const tallest = Math.max(1, ...Array.from(graph.ranks.values(), (nodes) => nodes.length));
  svg.setAttribute("viewBox", `0 0 ${Math.max(520, graph.ranks.size * 230 + 50)} ${Math.max(190, tallest * 94 + 32)}`);
  const defs = svgElement("defs"); const marker = svgElement("marker", {id:"arrow", viewBox:"0 0 8 8", refX:7, refY:4, markerWidth:7, markerHeight:7, orient:"auto"}); marker.append(svgElement("path", {d:"M 0 0 L 8 4 L 0 8 z", fill:"#4d6670"})); defs.append(marker); svg.append(defs);
  for (const edge of graph.edges) { const from=nodePosition(graph, String(edge.source)); const to=nodePosition(graph, String(edge.target)); svg.append(svgElement("path", {d:`M ${from.x + 180} ${from.y + 31} C ${from.x + 202} ${from.y + 31}, ${to.x - 22} ${to.y + 31}, ${to.x} ${to.y + 31}`, class:`edge ${safeText(edge.kind).replace(/[^a-z_]/g, "")}`})); }
  for (const node of graph.nodes) {
    const state=STATES.has(String(node.state)) ? String(node.state) : "waiting"; const pos=nodePosition(graph, String(node.id)); const group=svgElement("g", {class:`node node-${state}`, transform:`translate(${pos.x} ${pos.y})`, tabindex:0, role:"button"});
    const title=svgElement("title"); title.textContent=safeText(node.label || node.id); group.append(title);
    group.append(svgElement("rect", {class:"node-frame", width:180, height:62})); group.append(svgElement("rect", {class:"node-accent", width:4, height:62}));
    const subject=svgElement("text", {class:"node-label", x:12, y:22}); subject.textContent=clipped(node.label || node.id, 25); group.append(subject);
    const line=svgElement("text", {class:"node-meta", x:12, y:42}); if (!TERMINAL.has(state)) { line.dataset.elapsed="node"; line.dataset.startedAt=String(node.started_at || ""); } line.textContent=clipped(`${state} · ${formatDuration(node.started_at, TERMINAL.has(state) ? node.finished_at : new Date())}`, 29); group.append(line);
    const model=svgElement("text", {class:"node-kind", x:12, y:55}); model.textContent=clipped([node.model,node.effort].filter(Boolean).join(" · ") || node.kind || "node", 28); group.append(model);
    group.addEventListener("click", () => onNode(node)); group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onNode(node); } }); svg.append(group);
  }
  svg.classList.add("visible");
}

function renderCard(view, parent, focus) {
  const card = document.createElement("button"); card.type="button"; card.className=`session-card state-${view.state}`; card.dataset.session=view.sessionId;
  const title=document.createElement("strong"); title.textContent=view.title; card.append(title);
  const meta=document.createElement("span"); meta.textContent=`${view.state.toUpperCase()} · ${view.progress.complete}/${view.progress.total}`; card.append(meta);
  const timing=document.createElement("span"); timing.className="card-timing";
  if (view.state === "running") { timing.dataset.elapsed="true"; timing.dataset.startedAt=String(view.snapshot.started_at || view.snapshot.created_at || view.snapshot.updated_at || ""); timing.dataset.prefix=view.updatedAge; }
  timing.textContent=`${view.updatedAge} · ${view.elapsed}`; card.append(timing);
  const graph=document.createElement("span"); graph.className="micro-graph"; graph.dataset.running=String(view.mini.running); graph.dataset.waiting=String(view.mini.waiting); graph.dataset.terminal=String(view.mini.terminal); graph.setAttribute("aria-label", `${view.mini.running} running, ${view.mini.waiting} waiting, ${view.mini.terminal} terminal nodes`);
  for (const state of ["running", "waiting", "terminal"]) { const segment=document.createElement("i"); segment.className=`micro-${state}`; segment.style.flexGrow=String(Math.max(0.25, view.mini[state])); graph.append(segment); }
  card.append(graph);
  card.addEventListener("click", () => focus(view.snapshot)); parent.append(card);
}

export function renderAll(bundle, focus, now = new Date(), {openProjects = new Set()} = {}) {
  const root=byId("all-view"); root.hidden=false; byId("focused-view").hidden=true; root.replaceChildren(); const model=buildAllViewModel(bundle, now);
  for (const project of model.projects) {
    const section=document.createElement("section"); section.className="project-section"; const heading=document.createElement("h2"); heading.textContent=project.cwd; section.append(heading);
    const running=document.createElement("div"); running.className="session-grid"; for (const view of project.running) renderCard(view,running,focus); section.append(running);
    const completed=document.createElement("details"); completed.className="completed-sessions"; completed.open=openProjects.has(project.cwd); completed.addEventListener("toggle", () => { if (completed.open) openProjects.add(project.cwd); else openProjects.delete(project.cwd); }); const summary=document.createElement("summary"); summary.textContent=`Completed sessions (${project.completed.length})`; completed.append(summary); const grid=document.createElement("div"); grid.className="session-grid"; for (const view of project.completed) renderCard(view,grid,focus); completed.append(grid); section.append(completed); root.append(section);
  }
  byId("empty-state").classList.toggle("hidden", model.projects.length > 0);
}

export function renderFocused(snapshot, onBack) {
  byId("all-view").hidden=true; const focused=byId("focused-view"); focused.hidden=false;
  byId("focus-title").textContent=safeText(snapshot.title || snapshot.session_id); byId("focus-path").textContent=safeText(snapshot.cwd); const detail=byId("node-detail"); detail.replaceChildren();
  drawGraph(snapshot, (node) => { detail.replaceChildren(); const heading=document.createElement("h3"); heading.textContent=safeText(node.label || node.id); const description=document.createElement("p"); description.textContent=safeText(node.description || "No safe task description recorded."); detail.append(heading,description); });
  const back=byId("back-button"); back.onclick=onBack; back.focus();
}

export function applyBundle(bundle, {focusedSnapshot = null, focus, now = new Date()} = {}) {
  if (focusedSnapshot) renderFocused(focusedSnapshot, () => focus?.(null)); else renderAll(bundle, (snapshot) => focus?.(snapshot), now);
}

export function findSnapshot(bundle, sessionId) {
  for (const project of bundle?.projects || []) for (const snapshot of [...(project.running || []), ...(project.completed || [])]) if (safeText(snapshot.session_id) === safeText(sessionId)) return snapshot;
  return null;
}

export function updateElapsed(root = document, now = new Date()) {
  for (const node of root.querySelectorAll?.('[data-elapsed="true"]') || []) {
    const prefix=safeText(node.dataset.prefix || node.textContent.split(" · ")[0]);
    node.textContent=`${prefix} · ${formatDuration(node.dataset.startedAt, now)}`;
  }
  for (const node of root.querySelectorAll?.('[data-elapsed="node"]') || []) {
    const state=safeText(node.textContent.split(" · ")[0]);
    node.textContent=clipped(`${state} · ${formatDuration(node.dataset.startedAt, now)}`,29);
  }
}

function queryFromLocation() { const params=new URLSearchParams(window.location.search); return params.get("selection") === "all" ? "selection=all" : `session=${encodeURIComponent(params.get("session") || "")}`; }

function boot() {
  let lastBundle=null; let focusedSessionId=null; let originSessionId=null; let scrollY=0; let controller; const openProjects=new Set();
  const setConnection=(state) => { const messages={connected:"LOCAL / CONNECTED", connecting:"LOCAL / CONNECTING", reconnecting:"LOCAL / RECONNECTING", degraded:"LOCAL / DEGRADED"}; byId("connection").dataset.state=state; byId("connection-text").textContent=messages[state] || messages.connecting; };
  const render=() => { const focused=focusedSessionId ? findSnapshot(lastBundle, focusedSessionId) : null; if (focusedSessionId && !focused) focusedSessionId=null; if (focused) renderFocused(focused, () => { focusedSessionId=null; renderAll(lastBundle, chooseFocus, new Date(), {openProjects}); const origin=document.querySelector(`[data-session="${CSS.escape(originSessionId || "")}"]`); origin?.focus(); window.scrollTo(0,scrollY); }); else renderAll(lastBundle || {projects:[]}, chooseFocus, new Date(), {openProjects}); };
  const chooseFocus=(snapshot) => { scrollY=window.scrollY; originSessionId=safeText(snapshot.session_id); focusedSessionId=originSessionId; render(); };
  const transport=createTransport({EventSourceImpl:globalThis.EventSource, fetchImpl:globalThis.fetch?.bind(globalThis), onBundle:(bundle,meta) => controller?.acceptStreamSnapshot(meta.generation,bundle), onConnection:setConnection, onElapsed:() => updateElapsed(document,new Date()), onInitialFailure:(generation) => controller?.initialStreamFailed(generation)});
  controller=createSelectionController({fetchImpl:globalThis.fetch?.bind(globalThis), transport, apply:(bundle) => { lastBundle=bundle; render(); }, sync:(query) => { const url=`${window.location.pathname}?${query}`; window.history.replaceState({}, "", url); byId("session-selector").value=query; }, refreshCatalog:(catalog,query) => populateSelector(catalog,query), onError:(message) => { byId("selection-error").textContent=message; }, clearError:() => { byId("selection-error").textContent=""; }});
  byId("session-selector").addEventListener("change", (event) => controller.select(event.target.value));
  const initial=queryFromLocation(); fetch(`/api/snapshot?${initial}`).then((response) => response.ok ? response.json() : Promise.reject()).then((bundle) => controller.seed(initial,bundle)).catch(() => { setConnection("reconnecting"); render(); });
}

export function populateSelector(catalog, selected) {
  const selector=byId("session-selector"); selector.replaceChildren(); const all=document.createElement("option"); all.value="selection=all"; all.textContent="All sessions"; selector.append(all);
  const selectedSession=new URLSearchParams(selected).get("session"); const rows=Array.isArray(catalog) ? catalog : [];
  for (const row of rows) { const option=document.createElement("option"); option.value=`session=${encodeURIComponent(safeText(row.session_id))}`; option.textContent=`${safeText(row.title || row.session_id)} — ${safeText(row.cwd)}`; selector.append(option); }
  if (selectedSession && !rows.some((row) => safeText(row.session_id) === selectedSession)) { const option=document.createElement("option"); option.value=`session=${encodeURIComponent(selectedSession)}`; option.textContent=`${selectedSession} — active session`; selector.append(option); }
  selector.value=selected;
}

if (typeof document !== "undefined" && document.getElementById("all-view")) boot();
