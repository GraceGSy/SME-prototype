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

  function passage(text) {
    return `<div class="passage-block"><p class="passage passage-preview">${esc(text)}</p><details class="passage-details"${$("full-text").checked ? " open" : ""}><summary>Full passage</summary><p class="passage">${esc(text)}</p></details></div>`;
  }

  function partner(key, state, sourcePaper) {
    const source = report.levels[level].sources[key];
    const samePaper = source.paper === sourcePaper;
    return `<div class="partner ${state}"><div class="partner-head"><span class="partner-sign" aria-hidden="true">${state === "added" ? "+" : state === "removed" ? "-" : "="}</span><div><span class="partner-state">${state === "same" ? "Kept in both runs" : state === "added" ? "Added in comparison" : "Removed in comparison"}${samePaper ? " / same-paper co-member" : ""}</span><strong>${esc(titles[source.paper] || source.paper)}</strong> / ${esc(sourceLabel(source, report.levels.section.sources))}</div></div>${passage(source.text)}<code class="partner-id">${esc(key)}</code></div>`;
  }

  function column(row, side) {
    // Cross-paper partners come first; adjacent same-paper co-members remain visible.
    const peers = [...(side === "left" ? row.oldPeers : row.newPeers)].sort(
      (a, b) =>
        Number(report.levels[level].sources[a].paper === row.source.paper) -
        Number(report.levels[level].sources[b].paper === row.source.paper),
    );
    const changed = side === "left" ? row.removed : row.added;
    const state = side === "left" ? "removed" : "added";
    const otherPaperCount = peers.filter(
      (key) => report.levels[level].sources[key].paper !== row.source.paper,
    ).length;
    return `<section class="run-column" aria-label="${side === "left" ? "Baseline" : "Comparison"} partners"><h4 class="column-heading"><span>${esc(names[side])} <small>/ ${side === "left" ? "baseline" : "comparison"}</small></span><small>${otherPaperCount} cross-paper</small></h4>${peers.length ? peers.map((key) => partner(key, changed.includes(key) ? state : "same", row.source.paper)).join("") : '<div class="no-match">No matching partner. This passage stands alone.</div>'}<div class="group-question"><small>${peers.length ? "GROUP QUESTION" : "SINGLETON QUESTION"}</small><p>${esc(row[side].question || "No saved question")}</p></div></section>`;
  }

  function scopeLabel(key) {
    const source = report.levels.section.sources[key];
    return source
      ? `${titles[source.paper] || source.paper} / ${source.title} (${source.id})`
      : key;
  }

  function card(row) {
    const questions = report.levels[level].unit_questions.rows.find(
      (item) => item.unit === row.key,
    );
    return `<article class="diff-card" id="unit-${esc(row.key)}" data-unit="${esc(row.key)}" data-status="${row.status}"><header class="source-heading"><h3><strong>${esc(titles[row.source.paper] || row.source.paper)}</strong>${esc(sourceLabel(row.source, report.levels.section.sources))}</h3><span class="badge ${row.status}">${signs[row.status]} ${statusLabels[row.status]}</span></header><div class="source-body"><p class="eyebrow">SOURCE ${level === "paragraph" ? "PARAGRAPH" : "STRUCTURAL UNIT"} / IDENTICAL TEXT IN BOTH RUNS</p>${passage(row.source.text)}<code>${esc(row.key)}</code></div><div class="diff-columns">${column(row, "left")}${column(row, "right")}</div><details class="card-details"><summary>Source questions &amp; parent scope${row.scopeChanged ? " (scope changed)" : ""}</summary><div class="context-columns">${["left", "right"].map((side) => `<div><strong>${esc(names[side])}</strong><p>${esc(questions?.[side] || "No saved source question")}</p><strong>Parent scope</strong>${row[side].scope.length ? row[side].scope.map((key) => `<code>${esc(scopeLabel(key))}</code>`).join("") : "<p>No parent scope</p>"}</div>`).join("")}</div></details></article>`;
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
    const counts = {
      changes: data.membership_changed_units,
      scope: data.scope_only_changed_units,
      ...Object.fromEntries(
        ["added", "removed", "mixed"].map((status) => [
          status,
          rowsByLevel[level].filter((row) => row.status === status).length,
        ]),
      ),
      kept: rowsByLevel[level].filter(
        (row) => !row.added.length && !row.removed.length && row.oldPeers.length,
      ).length,
      all: data.common_units,
    };
    for (const option of $("filter").options) {
      option.dataset.label ||= option.textContent;
      option.textContent = `${option.dataset.label} (${counts[option.value]})`;
    }
  }

  function render() {
    visible = filterRows(
      rowsByLevel[level],
      { filter: $("filter").value, paper: $("paper").value, search: $("search").value },
      report.levels[level].sources,
    );
    $("result-count").textContent =
      `${visible.length} of ${report.levels[level].common_units} shared ${level === "paragraph" ? "paragraphs" : "structural units"} shown`;
    $("cards").innerHTML = visible.length
      ? visible.map(card).join("")
      : '<div class="empty"><h3>No passages in this view</h3><p>Try a different filter, another paper, or a broader search.</p><button class="text-button" data-reset>Clear filters and show match changes</button></div>';
    let paper = "";
    $("source-index").innerHTML = visible
      .map((row) => {
        const heading =
          row.source.paper !== paper
            ? `<p class="index-paper">${esc(titles[row.source.paper] || row.source.paper)}</p>`
            : "";
        paper = row.source.paper;
        return `${heading}<a class="index-link" href="#${level}/${encodeURIComponent(row.key)}"><span class="index-sign ${row.status}">${signs[row.status]}</span><span>${esc(sourceLabel(row.source, report.levels.section.sources))}<code>${esc(row.source.id)}</code></span></a>`;
      })
      .join("");
    $("cards").querySelector("[data-reset]")?.addEventListener("click", reset);
  }

  function reset() {
    $("search").value = "";
    $("paper").value = "";
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
      $("paper").value = "";
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
  for (const name of ["paragraph", "section"])
    $(name + "-total").textContent = report.levels[name].common_units;
  for (const id of ["paper", "filter"]) $(id).addEventListener("change", render);
  $("search").addEventListener("input", render);
  $("reset").addEventListener("click", reset);
  $("full-text").addEventListener("change", () => {
    document.querySelectorAll(".passage-details").forEach((details) => {
      details.open = $("full-text").checked;
    });
  });
  document.querySelectorAll("[data-level]").forEach((button) =>
    button.addEventListener("click", () => {
      level = button.dataset.level;
      overview();
      render();
    }),
  );
  window.addEventListener("hashchange", followHash);
  overview();
  render();
  followHash();
}
