// Membership comparisons use source IDs only. Question wording never picks a partner.
export function reviewRows(data) {
  return Object.keys(data.sources)
    .sort()
    .map((key) => {
      const left = data.assignments.left[key];
      const right = data.assignments.right[key];
      const oldPeers = left.members.filter((member) => member !== key);
      const newPeers = right.members.filter((member) => member !== key);
      const removed = oldPeers.filter((member) => !newPeers.includes(member));
      const added = newPeers.filter((member) => !oldPeers.includes(member));
      const scopeChanged = JSON.stringify(left.scope) !== JSON.stringify(right.scope);
      const status =
        added.length && removed.length
          ? "mixed"
          : added.length
            ? "added"
            : removed.length
              ? "removed"
              : scopeChanged
                ? "scope"
                : "same";
      return {
        key,
        source: data.sources[key],
        left,
        right,
        oldPeers,
        newPeers,
        removed,
        added,
        scopeChanged,
        status,
      };
    });
}

export function filterRows(rows, { filter, paper, search }, sources) {
  const query = search.trim().toLocaleLowerCase();
  return rows.filter((row) => {
    if (paper && row.source.paper !== paper) return false;
    const changed = row.added.length > 0 || row.removed.length > 0;
    if (filter === "changes" && !changed) return false;
    if (["added", "removed", "mixed", "scope"].includes(filter) && row.status !== filter)
      return false;
    if (filter === "kept" && (changed || !row.oldPeers.length)) return false;
    if (!query) return true;
    const peers = [...new Set([...row.oldPeers, ...row.newPeers])];
    return [
      row.key,
      row.source.title,
      row.source.text,
      row.source.tag,
      row.left.question,
      row.right.question,
      ...peers.flatMap((key) => [key, sources[key].title, sources[key].text]),
    ]
      .join(" ")
      .toLocaleLowerCase()
      .includes(query);
  });
}

export function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

export function sourceLabel(source, sections) {
  if (!source.section_id) return source.title || source.id;
  const section = sections[`${source.paper}:${source.section_id}`];
  const number = source.id.match(/p(\d+)$/)?.[1];
  return `${section?.title || source.section_id} / paragraph ${number ? Number(number) : source.id}`;
}

export function partitionPeers(row, side, sources) {
  const peers = side === "left" ? row.oldPeers : row.newPeers;
  return {
    crossPaper: peers.filter((key) => sources[key].paper !== row.source.paper),
    samePaper: peers.filter((key) => sources[key].paper === row.source.paper),
  };
}

if (typeof document !== "undefined") {
  const report = JSON.parse(document.getElementById("comparison-data").textContent);
  const $ = (id) => document.getElementById(id);
  const esc = escapeHtml;
  const percent = (n) => (n == null ? "N/A" : `${(n * 100).toFixed(1)}%`);
  const names = Object.fromEntries(
    ["left", "right"].map((side) => [
      side,
      report[side].settings.jev ? "Jev-assisted" : "LLM-only",
    ]),
  );
  const titles = report.paper_titles;
  const defaultPaper = report.left.summary.paper_order.find((paper) =>
    report.common_papers.includes(paper),
  );
  $("comparison-context").textContent =
    report.common_papers.map((paper) => titles[paper] || paper).join(" + ") +
    (report.warnings.some((warning) => warning.includes("not a controlled"))
      ? ". Historical comparison: settings differ, so this does not isolate Jev's effect."
      : ". Only identical shared source text is compared.");
  const rowsByLevel = Object.fromEntries(
    Object.entries(report.levels).map(([level, data]) => [level, reviewRows(data)]),
  );
  const statusLabels = {
    added: "Added partners",
    removed: "Removed partners",
    mixed: "Changed partners",
    scope: "Parent scope only",
    same: "Same partners",
  };
  const signs = { added: "+", removed: "-", mixed: "+/-", scope: "~", same: "=" };
  let level = "paragraph";
  let visible = [];

  function passageBox(key, state) {
    const source = report.levels[level].sources[key];
    const label = sourceLabel(source, report.levels.section.sources);
    const stateText =
      state === "source"
        ? "Shared source"
        : state === "same"
          ? "Kept in both runs"
          : state === "added"
            ? "+ Only in " + names.right
            : "- Only in " + names.left;
    return `<button class="passage-card ${state}" data-passage="${esc(key)}" aria-label="Read ${esc(titles[source.paper] || source.paper)}: ${esc(label)}"><span class="box-state">${esc(stateText)}</span><span class="box-paper">${esc(titles[source.paper] || source.paper)}</span><span class="box-title">${esc(label)}</span><span class="box-excerpt">${esc(source.text)}</span><span class="box-footer"><code>${esc(source.id)}</code><span>Read passage</span></span></button>`;
  }

  function column(row, side) {
    const peers = partitionPeers(row, side, report.levels[level].sources);
    const changed = side === "left" ? row.removed : row.added;
    const state = (key) =>
      changed.includes(key) ? (side === "left" ? "removed" : "added") : "same";
    const coMembers = peers.samePaper
      .map((key) => {
        const source = report.levels[level].sources[key];
        return `<button class="co-member ${state(key)}" data-passage="${esc(key)}" title="${esc(sourceLabel(source, report.levels.section.sources))}">${state(key) === "same" ? "=" : side === "left" ? "-" : "+"} ${esc(source.id)}</button>`;
      })
      .join("");
    return `<section class="match-column ${side}" aria-label="${side === "left" ? "Baseline" : "Comparison"} partners"><h4 class="column-label"><span>${esc(names[side])}</span><small>${peers.crossPaper.length} cross-paper ${peers.crossPaper.length === 1 ? "match" : "matches"}</small></h4><div class="partner-stack">${peers.crossPaper.length ? peers.crossPaper.map((key) => passageBox(key, state(key))).join("") : '<div class="no-match"><strong>No cross-paper match</strong><span>This run leaves the source without a partner in another paper.</span></div>'}${coMembers ? `<div class="co-members"><span>Also grouped from the source paper</span>${coMembers}</div>` : ""}</div></section>`;
  }

  function showPassage(key) {
    const source = report.levels[level].sources[key];
    $("passage-title").textContent =
      `${titles[source.paper] || source.paper} / ${sourceLabel(source, report.levels.section.sources)}`;
    $("passage-id").textContent = key;
    $("passage-text").textContent = source.text;
    const questions = report.levels[level].unit_questions.rows.find((item) => item.unit === key);
    $("passage-questions").innerHTML = ["left", "right"]
      .map(
        (side) =>
          `<div><strong>${esc(names[side])}</strong><p>${esc(questions?.[side] || "No saved source question")}</p></div>`,
      )
      .join("");
    $("passage-dialog").showModal();
  }

  function drawLinks() {
    if (!window.matchMedia("(min-width: 651px)").matches) return;
    for (const layout of document.querySelectorAll(".match-layout")) {
      const bounds = layout.getBoundingClientRect();
      const source = layout.querySelector(".source-column .passage-card").getBoundingClientRect();
      const svg = layout.querySelector(".match-links");
      svg.setAttribute("viewBox", `0 0 ${bounds.width} ${bounds.height}`);
      // Connect actual cross-paper partners only, never an empty state or same-paper chip.
      svg.innerHTML = ["left", "right"]
        .flatMap((side) =>
          [...layout.querySelectorAll(`.match-column.${side} .passage-card`)].map((card) => {
            const target = card.getBoundingClientRect();
            const x1 = (side === "left" ? target.right : source.right) - bounds.left;
            const x2 = (side === "left" ? source.left : target.left) - bounds.left;
            const y1 =
              (side === "left" ? target.top + target.height / 2 : source.top + source.height / 2) -
              bounds.top;
            const y2 =
              (side === "left" ? source.top + source.height / 2 : target.top + target.height / 2) -
              bounds.top;
            const middle = (x1 + x2) / 2;
            const state = card.classList.contains("added")
              ? "added"
              : card.classList.contains("removed")
                ? "removed"
                : "same";
            return `<path class="match-link ${state}" d="M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2} ${y2}"/>`;
          }),
        )
        .join("");
    }
  }

  function scopeLabel(key) {
    const source = report.levels.section.sources[key];
    return source
      ? `${titles[source.paper] || source.paper} / ${source.title} (${source.id})`
      : key;
  }

  function card(row, index) {
    const questions = report.levels[level].unit_questions.rows.find(
      (item) => item.unit === row.key,
    );
    return `<article class="diff-card" id="unit-${esc(row.key)}" data-unit="${esc(row.key)}" data-status="${row.status}"><header class="row-heading"><span class="row-number">${String(index + 1).padStart(2, "0")}</span><h3>${esc(sourceLabel(row.source, report.levels.section.sources))}</h3><span class="badge ${row.status}">${signs[row.status]} ${statusLabels[row.status]}</span></header><div class="match-layout"><svg class="match-links" aria-hidden="true"></svg>${column(row, "left")}<span class="link-gap" aria-hidden="true"></span><section class="source-column" aria-label="Source passage"><h4 class="column-label"><span>The same source</span><small>Identical text in both runs</small></h4>${passageBox(row.key, "source")}</section><span class="link-gap" aria-hidden="true"></span>${column(row, "right")}</div><details class="card-details"><summary>Compare questions &amp; parent scope${row.scopeChanged ? " (scope changed)" : ""}</summary><div class="context-columns">${["left", "right"].map((side) => `<div><strong>${esc(names[side])}</strong><p class="context-label">Group question</p><p>${esc(row[side].question || "No saved group question")}</p><p class="context-label">Source question</p><p>${esc(questions?.[side] || "No saved source question")}</p><p class="context-label">Parent scope</p>${row[side].scope.length ? row[side].scope.map((key) => `<code>${esc(scopeLabel(key))}</code>`).join("") : "<p>No parent scope</p>"}</div>`).join("")}</div></details></article>`;
  }

  function overview() {
    const data = report.levels[level];
    const graph = data.metrics.graph;
    const coverage = data.metrics.coverage;
    $("overview").innerHTML =
      `<div class="stat removed"><span class="stat-number">-${graph.removed_pairs.length}</span><span class="stat-label">Removed pairs</span><small>Baseline only</small></div><div class="stat added"><span class="stat-number">+${graph.added_pairs.length}</span><span class="stat-label">Added pairs</span><small>Comparison only</small></div><div class="stat"><span class="stat-number">${graph.unchanged_pairs}</span><span class="stat-label">Kept pairs</span><small>In both runs</small></div><div class="stat">${["left", "right"].map((side) => `<div class="coverage-row"><div class="coverage-title"><span>${esc(names[side])} coverage</span><strong>${coverage[side].matched_units}/${data.common_units} <span>(${percent(coverage[side].fraction)})</span></strong></div><div class="coverage-track"><div class="coverage-fill" style="width:${percent(coverage[side].fraction)}"></div></div></div>`).join("")}<p class="coverage-caption">${level === "paragraph" ? "Paragraphs" : "Structural units"} with a cross-paper partner. Pair counts are unique across all shared papers, unaffected by filters.</p></div>`;
    document
      .querySelectorAll("[data-level]")
      .forEach((button) =>
        button.setAttribute("aria-pressed", String(button.dataset.level === level)),
      );
  }

  function render() {
    const filters = { paper: $("paper").value, search: $("search").value };
    for (const option of $("filter").options) {
      option.dataset.label ||= option.textContent;
      const count = filterRows(
        rowsByLevel[level],
        { ...filters, filter: option.value },
        report.levels[level].sources,
      ).length;
      option.textContent = `${option.dataset.label} (${count})`;
    }
    visible = filterRows(
      rowsByLevel[level],
      { filter: $("filter").value, paper: $("paper").value, search: $("search").value },
      report.levels[level].sources,
    );
    const total = rowsByLevel[level].filter(
      (row) => !filters.paper || row.source.paper === filters.paper,
    ).length;
    $("result-count").textContent =
      `${visible.length} of ${total} ${level === "paragraph" ? "paragraphs" : "structural units"} shown${filters.paper ? " from " + titles[filters.paper] : " across all papers"}`;
    $("cards").classList.toggle("full-text", $("full-text").checked);
    $("cards").innerHTML = visible.length
      ? visible.map(card).join("")
      : '<div class="empty"><h3>No passages in this view</h3><p>Try a different filter, another paper, or a broader search.</p><button class="text-button" data-reset>Clear filters and show match changes</button></div>';
    $("source-index").innerHTML = visible
      .map(
        (row, index) =>
          `<a class="index-link ${row.status}" href="#${level}/${encodeURIComponent(row.key)}" title="${esc(titles[row.source.paper] || row.source.paper)}: ${esc(sourceLabel(row.source, report.levels.section.sources))}" aria-label="Jump to passage ${index + 1}: ${esc(sourceLabel(row.source, report.levels.section.sources))}">${String(index + 1).padStart(2, "0")} <span>${signs[row.status]}</span></a>`,
      )
      .join("");
    $("cards").querySelector("[data-reset]")?.addEventListener("click", reset);
    requestAnimationFrame(drawLinks);
  }

  function reset() {
    $("search").value = "";
    $("paper").value = defaultPaper;
    $("filter").value = "changes";
    render();
  }

  function followHash() {
    const match = location.hash.match(/^#(paragraph|section)\/(.+)$/);
    if (!match) return;
    let key;
    try {
      key = decodeURIComponent(match[2]);
    } catch {
      return;
    }
    if (!report.levels[match[1]].sources[key]) return;
    if (level !== match[1]) {
      level = match[1];
      overview();
      render();
    }
    if (!visible.some((row) => row.key === key)) {
      $("search").value = "";
      $("paper").value = report.levels[level].sources[key].paper;
      $("filter").value = "all";
      render();
    }
    $("unit-" + key).scrollIntoView({ block: "start" });
    document
      .querySelectorAll(".index-link")
      .forEach((link) => link.setAttribute("aria-current", String(link.hash === location.hash)));
  }

  for (const side of ["left", "right"]) {
    const run = report[side];
    const path = run.path.replaceAll("\\", "/").split("/");
    const runId = path.at(-3),
      revision = path.at(-1);
    const model = run.settings.model || {};
    const chip = `<div class="run-chip"><span class="run-name">${esc(names[side])}</span><small>${esc(run.settings.jev?.model || model.name || "Unknown model")} / ${esc(revision)}</small><code>${esc(runId)}</code></div>`;
    $("run-strip").insertAdjacentHTML(
      "beforeend",
      (side === "right" ? '<span class="versus">versus</span>' : "") + chip,
    );
    $("run-details").insertAdjacentHTML(
      "beforeend",
      `<article class="run-detail"><h3>${side === "left" ? "Baseline" : "Comparison"}: ${esc(names[side])}</h3><code>${esc(runId)} / ${esc(revision)}</code><p>${run.summary.paper_count} papers / ${esc(run.summary.max_granularity)} granularity<br>Generative model: ${esc(model.name || "Unknown")}<br>Jev selector: ${esc(run.settings.jev?.model || "Not enabled")}</p><code>Graph: ${esc(run.summary.graph_hash || "Not recorded")}</code><details><summary>Saved model &amp; policy settings</summary><pre>${esc(JSON.stringify(run.settings, null, 2))}</pre></details></article>`,
    );
  }
  $("warnings").innerHTML =
    report.warnings.map((warning) => `<li>${esc(warning)}</li>`).join("") +
    `<li>Shared papers: ${report.common_papers.map((paper) => esc(titles[paper] || paper)).join(", ")}. Run-only papers: baseline ${esc(report.left_only_papers.join(", ") || "none")}; comparison ${esc(report.right_only_papers.join(", ") || "none")}.</li>` +
    Object.entries(report.levels)
      .map(
        ([name, data]) =>
          `<li>${esc(name)} projection: ${data.common_units} identical source units; ${data.source_projection.left_excluded_units.length} baseline and ${data.source_projection.right_excluded_units.length} comparison units excluded; ${data.source_projection.metadata_changed_units.length} units have different scope metadata.</li>`,
      )
      .join("");
  $("paper").insertAdjacentHTML(
    "beforeend",
    report.common_papers
      .map((paper) => `<option value="${esc(paper)}">${esc(titles[paper] || paper)}</option>`)
      .join(""),
  );
  $("paper").value = defaultPaper;
  for (const name of ["paragraph", "section"])
    $(name + "-total").textContent = report.levels[name].common_units;
  for (const id of ["paper", "filter"]) $(id).addEventListener("change", render);
  $("search").addEventListener("input", render);
  $("reset").addEventListener("click", reset);
  $("full-text").addEventListener("change", () => {
    $("cards").classList.toggle("full-text", $("full-text").checked);
  });
  $("cards").addEventListener("click", (event) => {
    const button = event.target.closest("[data-passage]");
    if (button) showPassage(button.dataset.passage);
  });
  $("close-passage").addEventListener("click", () => $("passage-dialog").close());
  $("passage-dialog").addEventListener("click", (event) => {
    if (event.target === $("passage-dialog")) $("passage-dialog").close();
  });
  $("source-index").addEventListener("click", (event) => {
    if (event.target.closest("a")?.hash === location.hash) followHash();
  });
  document.querySelectorAll("[data-level]").forEach((button) =>
    button.addEventListener("click", () => {
      level = button.dataset.level;
      overview();
      render();
    }),
  );
  window.addEventListener("hashchange", followHash);
  new ResizeObserver(drawLinks).observe($("cards"));
  overview();
  render();
  followHash();
}
