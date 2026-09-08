import type { Group } from "./contracts";
import { html } from "./explorer-dom";
import { type Model, PAPER_COLORS } from "./model";

// Evidence unfolds on the canvas under its question, never in a separate sidebar.
export function renderPassages(model: Model, group: Group): HTMLElement {
  const content = html("div", "gx-passages");
  content.setAttribute("aria-label", "Original paragraphs across papers");
  for (const [index, paper] of model.papers.entries()) {
    const card = html("article", "gx-passage");
    card.style.setProperty("--paper", PAPER_COLORS[index % PAPER_COLORS.length]);
    card.append(html("h3", "paper-title", paper.title));
    const ids = new Set(
      group.members.filter((m) => m.paper === paper.paper_id).map((m) => m.unit_id),
    );
    const units = paper.paragraphs
      .filter((p) => ids.has(p.id))
      .sort((a, b) => a.ordinal - b.ordinal);
    if (!units.length) card.append(html("p", "group-column-empty", "No matched paragraph"));
    for (const unit of units) {
      card.append(html("div", "gx-source", unit.title || unit.tag || unit.id));
      card.append(html("p", "gx-source-text", unit.text));
    }
    content.append(card);
  }
  return content;
}
