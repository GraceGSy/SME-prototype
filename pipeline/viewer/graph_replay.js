(function () {
  "use strict";

  const NODE_COLOR = "#52748a";
  const PAPER_COLORS = ["#1971c2", "#e8590c", "#2f9e44", "#9c36b5", "#0b7285", "#c92a2a", "#5f3dc4", "#f08c00"];
  const ACTION_LABELS = {
    paper_added: "Paper added",
    match_recorded: "Match judgment recorded",
    node_created: "Node created",
    member_added: "Section or paragraph added to node",
    node_merged: "Node merged",
    edge_created: "Hierarchy edge added",
    question_generated: "Display question generated",
    projected_edge_ignored: "Projected edge ignored",
    rerepresentation_merge_ignored: "Rerepresentation merge ignored",
  };

  let host = null;
  let replay = null;
  let papers = [];
  let index = 0;
  let scope = "section";
  let selectedNodeId = null;
  let timer = null;
  let speed = 500;
  let showHierarchy = false;

  function mount(container, replayData, paperData) {
    destroy();
    host = container;
    replay = replayData;
    papers = paperData || [];
    index = 0;
    scope = "section";
    selectedNodeId = null;
    showHierarchy = false;
    renderShell();
  }

  function destroy() {
    stop();
    host = null;
    replay = null;
    papers = [];
    selectedNodeId = null;
  }

  function resize() {
    if (host && replay) renderGraph(currentState());
  }

  function renderShell() {
    if (!host || !replay) return;
    const scopeKeys = Object.keys(replay.layouts || {}).sort((left, right) => {
      if (left === "section") return -1;
      if (right === "section") return 1;
      return left.localeCompare(right);
    });
    const scopeOptions = scopeKeys.map(key => {
      const selected = key === scope ? " selected" : "";
      if (key === "section") return `<option value="section"${selected}>Section nodes</option>`;
      return `<option value="paragraph"${selected}>Paragraph nodes</option>`;
    }).join("");
    const paperDots = papers.map((paper, paperIndex) => `<button type="button" class="graph-replay-paper-step" data-paper-index="${paperIndex + 1}" title="Jump to ${escapeHtml(paper.title || paper.paper_id)}" style="--paper-color:${PAPER_COLORS[paperIndex % PAPER_COLORS.length]}"></button>`).join("");
    host.innerHTML = `<div class="graph-replay">
      <div>
        <div class="graph-replay-toolbar">
          <label class="graph-replay-scope">Graph <select id="graphReplayScope">${scopeOptions}</select></label>
          <label><input id="graphReplayHierarchy" type="checkbox"> Show hierarchy</label>
          <button type="button" id="graphReplayStart" title="Beginning">|&lt;</button>
          <button type="button" id="graphReplayPrevious" title="Previous event">Previous</button>
          <button type="button" id="graphReplayPlay">Play</button>
          <button type="button" id="graphReplayNext" title="Next event">Next</button>
          <button type="button" id="graphReplayEnd" title="Final graph">&gt;|</button>
          <input class="graph-replay-scrubber" id="graphReplayScrubber" type="range" min="0" max="${replay.events.length}" value="0" step="1">
          <span class="graph-replay-counter" id="graphReplayCounter"></span>
          <label>Speed <select id="graphReplaySpeed"><option value="900">Slow</option><option value="500" selected>Normal</option><option value="180">Fast</option></select></label>
          <div class="graph-replay-paper-strip" aria-label="Jump to paper">${paperDots}</div>
        </div>
        <div class="graph-replay-legend">
          <span>Dashed arrows show section containment when enabled.</span>
        </div>
      </div>
      <div class="graph-replay-body">
        <div class="graph-replay-canvas" id="graphReplayCanvas"></div>
        <aside class="graph-replay-inspector" id="graphReplayInspector"></aside>
      </div>
    </div>`;
    bindControls();
    render();
  }

  function bindControls() {
    byId("graphReplayScope").addEventListener("change", event => { scope = event.target.value; selectedNodeId = null; render(); });
    byId("graphReplayHierarchy").addEventListener("change", event => { showHierarchy = event.target.checked; render(); });
    byId("graphReplayStart").addEventListener("click", () => seek(0));
    byId("graphReplayPrevious").addEventListener("click", () => seek(index - 1));
    byId("graphReplayPlay").addEventListener("click", togglePlay);
    byId("graphReplayNext").addEventListener("click", () => seek(index + 1));
    byId("graphReplayEnd").addEventListener("click", () => seek(replay.events.length));
    byId("graphReplayScrubber").addEventListener("input", event => seek(Number(event.target.value), false));
    byId("graphReplaySpeed").addEventListener("change", event => { speed = Number(event.target.value); if (timer) { stop(); start(); } });
    host.querySelectorAll("[data-paper-index]").forEach(button => {
      button.addEventListener("click", () => jumpToPaper(Number(button.dataset.paperIndex)));
    });
  }

  function currentState() {
    return reduceEvents(index);
  }

  function reduceEvents(endIndex) {
    const state = { papers: [], nodes: new Map(), edges: new Map() };
    replay.events.slice(0, endIndex).forEach(event => applyEvent(state, event));
    return state;
  }

  function applyEvent(state, event) {
    if (event.action === "paper_added") state.papers.push(event.paper_id);
    else if (event.action === "node_created") {
      state.nodes.set(event.node_id, {
        nodeId: event.node_id,
        level: event.level,
        parentId: event.parent_id || null,
        members: [event.member],
        question: "",
      });
    } else if (event.action === "member_added") state.nodes.get(event.node_id)?.members.push(event.member);
    else if (event.action === "node_merged") {
      const target = state.nodes.get(event.target_node_id);
      if (target) target.members.push(...event.members);
      state.nodes.delete(event.source_node_id);
      state.edges.forEach((edge, edgeId) => {
        if (edge.source === event.source_node_id || edge.target === event.source_node_id) {
          state.edges.delete(edgeId);
        }
      });
    }
    else if (event.action === "edge_created") state.edges.set(event.edge_id, event);
    else if (event.action === "question_generated") {
      const node = state.nodes.get(event.node_id);
      if (node) node.question = event.question;
    }
  }

  function render() {
    if (!host || !replay) return;
    const state = currentState();
    byId("graphReplayScrubber").value = String(index);
    byId("graphReplayCounter").textContent = `${index} / ${replay.events.length}`;
    byId("graphReplayStart").disabled = index === 0;
    byId("graphReplayPrevious").disabled = index === 0;
    byId("graphReplayNext").disabled = index === replay.events.length;
    byId("graphReplayEnd").disabled = index === replay.events.length;
    byId("graphReplayPlay").textContent = timer ? "Pause" : "Play";
    byId("graphReplayPlay").classList.toggle("active", Boolean(timer));
    byId("graphReplayHierarchy").disabled = scope !== "section";
    host.querySelectorAll("[data-paper-index]").forEach(button => {
      button.classList.toggle("reached", Number(button.dataset.paperIndex) <= state.papers.length);
    });
    renderGraph(state);
    renderInspector(state);
  }

  function renderGraph(state) {
    const canvas = byId("graphReplayCanvas");
    if (!canvas) return;
    const layout = showHierarchy && scope === "section"
      ? replay.hierarchy_layouts?.section || replay.layouts?.section || {}
      : replay.layouts?.[scope] || {};
    const visibleNodes = Array.from(state.nodes.values()).filter(node => scope === "section"
      ? node.level === "section"
      : node.level === "paragraph");
    const visibleIds = new Set(visibleNodes.map(node => node.nodeId));
    if (!visibleNodes.length) {
      canvas.innerHTML = `<div class="graph-replay-empty">No nodes exist in this scope at event ${index}.</div>`;
      return;
    }
    const width = showHierarchy && scope === "section"
      ? Math.max(canvas.clientWidth, visibleNodes.length * 15, 620)
      : Math.max(canvas.clientWidth, 620);
    const height = Math.max(canvas.clientHeight, 440);
    const currentEvent = replay.events[index - 1] || {};
    const point = nodeId => {
      const saved = layout[nodeId] || fallbackPoint(nodeId, visibleNodes);
      return { x: 54 + saved.x * (width - 108), y: 46 + saved.y * (height - 92) };
    };
    const edges = Array.from(state.edges.values()).filter(edge =>
      visibleIds.has(edge.source) && visibleIds.has(edge.target)
      && (edge.kind !== "contains" || showHierarchy)
    );
    const edgeSvg = edges.map(edge => {
      const source = point(edge.source);
      const target = point(edge.target);
      const active = currentEvent.edge_id === edge.edge_id ? " current" : "";
      const kind = edge.kind === "contains" ? " contains" : "";
      return `<line class="graph-replay-edge${kind}${active}" x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}" marker-end="url(#replayArrow)"></line>`;
    }).join("");
    const nodeSvg = visibleNodes.map(node => {
      const position = point(node.nodeId);
      const active = currentEvent.node_id === node.nodeId
        || currentEvent.absorbed_group_id === node.nodeId
        || currentEvent.target_node_id === node.nodeId;
      const selected = selectedNodeId === node.nodeId;
      const classes = `graph-replay-node${active ? " current" : ""}${selected ? " selected" : ""}`;
      const compact = visibleNodes.length > 40;
      const radius = compact ? 9 : node.level === "section" ? 25 : 20;
      const label = shortText(node.question || node.nodeId, 32);
      const visibleLabel = !compact || active || selected
        ? `<text y="${radius + 16}">${escapeHtml(label)}</text>`
        : "";
      return `<g class="${classes}" data-replay-node="${escapeHtml(node.nodeId)}" transform="translate(${position.x},${position.y})">
        <title>${escapeHtml(node.question || node.nodeId)}</title>
        <circle r="${radius}" fill="${NODE_COLOR}"></circle>
        <text class="member-count" y="3">${node.members.length}</text>
        ${visibleLabel}
      </g>`;
    }).join("");
    canvas.innerHTML = `<svg viewBox="0 0 ${width} ${height}" style="width:${width}px" role="img" aria-label="Incremental node graph">
      <defs><marker id="replayArrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#d18b26"></path></marker></defs>
      ${edgeSvg}${nodeSvg}
    </svg>`;
    canvas.querySelectorAll("[data-replay-node]").forEach(node => {
      node.addEventListener("click", () => { selectedNodeId = node.dataset.replayNode; render(); });
    });
  }

  function renderInspector(state) {
    const inspector = byId("graphReplayInspector");
    const event = replay.events[index - 1];
    const selected = selectedNodeId ? state.nodes.get(selectedNodeId) : null;
    const eventHtml = event ? `<section>
      <div class="graph-replay-kicker">Event ${event.sequence}</div>
      <h2>${escapeHtml(ACTION_LABELS[event.action] || event.action)}</h2>
      <p>${escapeHtml(eventSummary(event))}</p>
      ${detailList(event)}
    </section>` : `<section><div class="graph-replay-kicker">Initial state</div><h2>Before the first paper</h2><p>Use Play or Next to begin the deterministic replay.</p></section>`;
    const nodeHtml = selected ? `<section>
      <div class="graph-replay-kicker">Selected node</div>
      <h2>${escapeHtml(selected.question || selected.nodeId)}</h2>
      <p>${selected.members.length} member${selected.members.length === 1 ? "" : "s"}</p>
      <dl class="graph-replay-detail-list">${selected.members.map(member => `<dt>${escapeHtml(member.paper_id)} &middot; ${escapeHtml(member.unit_kind || selected.level)}</dt><dd>${escapeHtml(member.unit_id)}</dd>`).join("")}</dl>
    </section>` : "";
    inspector.innerHTML = eventHtml + nodeHtml;
  }

  function eventSummary(event) {
    if (event.action === "paper_added") return `${event.title || event.paper_id} enters the corpus.`;
    if (event.action === "match_recorded") return event.target_id ? `${event.source_id} selected ${event.target_id}.` : `${event.source_id} selected no match.`;
    if (event.action === "node_created") return `${event.member.paper_id}:${event.member.unit_id} starts a new node.`;
    if (event.action === "member_added") return `${event.member.paper_id}:${event.member.unit_id} joins ${event.node_id}.`;
    if (event.action === "node_merged") {
      const reason = event.reason === "structural_rerepresentation"
        ? "through structural rerepresentation"
        : "as adjacent paragraph fan-in";
      return `${event.source_node_id} joins ${event.target_node_id} ${reason}.`;
    }
    if (event.action === "edge_created") return `${event.source} points to ${event.target}.`;
    if (event.action === "question_generated") return event.question;
    if (event.action === "projected_edge_ignored") return `The selection was retained as provenance; no ${event.source_group_id} -> ${event.absorbed_group_id} edge was added.`;
    if (event.action === "rerepresentation_merge_ignored") return `${event.source_group_id} remains a singleton because ${event.target_group_id} already represents ${event.paper_id}.`;
    return "The saved pipeline event has no graph mutation.";
  }

  function detailList(event) {
    const omitted = new Set(["sequence", "event_id", "action", "candidate_ids", "member", "question", "previous"]);
    const rows = Object.entries(event).filter(([key, value]) => !omitted.has(key) && value !== null && value !== "")
      .map(([key, value]) => `<dt>${escapeHtml(key.replaceAll("_", " "))}</dt><dd>${escapeHtml(typeof value === "object" ? JSON.stringify(value) : String(value))}</dd>`).join("");
    return rows ? `<dl class="graph-replay-detail-list">${rows}</dl>` : "";
  }

  function seek(nextIndex, stopPlayback = true) {
    if (stopPlayback) stop();
    index = Math.max(0, Math.min(replay.events.length, nextIndex));
    render();
  }

  function jumpToPaper(paperIndex) {
    const eventIndex = replay.events.findIndex(event => event.action === "paper_added" && event.paper_index === paperIndex);
    if (eventIndex >= 0) seek(eventIndex + 1);
  }

  function togglePlay() {
    if (timer) stop();
    else start();
    render();
  }

  function start() {
    if (index >= replay.events.length) index = 0;
    timer = window.setInterval(() => {
      if (index >= replay.events.length) { stop(); render(); return; }
      index += 1;
      render();
    }, speed);
  }

  function stop() {
    if (timer) window.clearInterval(timer);
    timer = null;
  }

  function fallbackPoint(nodeId, nodes) {
    const position = nodes.map(node => node.nodeId).sort().indexOf(nodeId);
    const angle = (Math.PI * 2 * position) / Math.max(nodes.length, 1) - Math.PI / 2;
    return { x: .5 + .38 * Math.cos(angle), y: .5 + .38 * Math.sin(angle) };
  }

  function shortText(value, length) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length > length ? `${text.slice(0, length - 3)}...` : text;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[character]);
  }

  function byId(id) {
    return host?.querySelector(`#${id}`);
  }

  window.GraphReplayView = { mount, destroy, resize };
}());
