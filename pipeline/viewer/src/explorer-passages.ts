import type { Group } from "./contracts";
import { html } from "./explorer-dom";
import { type Model, PAPER_COLORS } from "./model";

// Evidence unfolds on the canvas under its label, never in a separate sidebar.
export function renderPassages(model: Model, group: Group): HTMLElement {
  const content = html("div", "gx-passages");
  const structural = group.members.every((m) => m.unit_type !== "paragraph");
  content.setAttribute(
    "aria-label",
    structural ? "Original sections across papers" : "Original paragraphs across papers",
  );
  for (const [index, paper] of model.papers.entries()) {
    const card = html("article", "gx-passage");
    card.style.setProperty("--paper", PAPER_COLORS[index % PAPER_COLORS.length]);
    card.append(html("h3", "paper-title", paper.title));
    const ids = new Set(
      group.members.filter((m) => m.paper === paper.paper_id).map((m) => m.unit_id),
    );
    // Section blocks (section checkpoints) show their sections' own text.
    const units = (structural ? paper.sections : paper.paragraphs)
      .filter((p) => ids.has(p.id))
      .sort((a, b) => a.ordinal - b.ordinal);
    if (!units.length)
      card.append(
        html("p", "group-column-empty", structural ? "No matched section" : "No matched paragraph"),
      );
    for (const unit of units) {
      card.append(
        html(
          "div",
          "gx-source",
          structural ? unit.title || unit.id : unit.title || unit.tag || unit.id,
        ),
      );
      card.append(html("p", "gx-source-text", unit.text));
    }
    content.append(card);
  }
  return content;
}
