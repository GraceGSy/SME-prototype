import { type Model, PAPER_COLORS, unitKey } from "./model";
import type { ExplorerGraph } from "./explorer-layout";
import { html, button } from "./explorer-dom";

interface InspectorActions {
  navigate: (id: string) => void;
  select: (id: string) => void;
  toggleCompare: () => void;
}

export function renderInspector(
  inspector: HTMLElement,
  model: Model,
  graph: ExplorerGraph,
  section: string | null,
  selected: string | null,
  comparing: boolean,
  actions: InspectorActions,
): void {
  inspector.replaceChildren();
  const group = graph.nodes.find((n) => n.group.group_id === selected)?.group;
  if (!group) {
    inspector.append(
      html("div", "gx-eyebrow", section ? "02 / PARAGRAPH LANDSCAPE" : "01 / STRUCTURAL SKELETON"),
      html("h3", "", section ? "One section. Different answers." : "Start with a shared question."),
      html(
        "p",
        "",
        "Select a node to compare its original passages. Colored paths connect displayed units in each paper's source order. Scroll to move closer.",
      ),
    );
    const jump = html("select", "gx-jump");
    jump.setAttribute("aria-label", "Jump to a role");
    const placeholder = html("option", "", "Jump to a question...");
    placeholder.value = "";
    jump.append(placeholder);
    for (const node of graph.nodes) {
      const option = html("option", "", node.group.overarching_question);
      option.value = node.group.group_id;
      jump.append(option);
    }
    jump.addEventListener("change", () => {
      if (!jump.value) return;
      actions.select(jump.value);
    });
    inspector.append(jump);
    if (section) {
      const parent = model.sections.find((g) => g.group_id === section)!;
      inspector.append(html("h4", "", parent.overarching_question));
      inspector.append(
        html(
          "p",
          "",
          "This graph contains paragraphs assigned to this exact section role. Subsections have their own nodes in the overview.",
        ),
      );
    }
    inspector.append(
      html("h4", "", "Three ways to look"),
      html("p", "", "Common structure: multiple papers occupy a shared role."),
      html(
        "p",
        "",
        "Aligned differences: compare the different answers inside that role. The graph does not classify their differences.",
      ),
      html(
        "p",
        "",
        "Unmatched structure: a dashed node has no accepted cross-paper match. This is not proof that no analogy exists.",
      ),
    );
    return;
  }
  const count = new Set(group.members.map((m) => m.paper)).size;
  inspector.append(
    html(
      "div",
      "gx-eyebrow",
      count > 1 ? "COMMON ROLE / COMPARE THE DIFFERENCES" : "UNMATCHED ROLE / INSPECT IN CONTEXT",
    ),
    html("h3", "", group.overarching_question),
  );
  inspector.append(
    button(comparing ? "Return to graph" : "Compare side by side", () => {
      actions.toggleCompare();
    }),
  );
  if (!section) {
    const children = [...model.groups.values()].filter(
      (g) => g.group.parent_group_id === group.group_id,
    );
    const open = button(
      `Explore paragraphs (${children.length} roles)`,
      () => actions.navigate(group.group_id),
      "gx-button primary",
    );
    open.disabled = !children.length;
    inspector.append(open);
    if (!children.length)
      inspector.append(
        html("p", "", "No directly assigned paragraphs. Explore the subsection nodes below."),
      );
    const childIds = new Set<string>();
    for (const member of group.members) {
      const paper = model.papers.find((p) => p.paper_id === member.paper)!;
      for (const section of paper.sections.filter((s) => s.parent_id === member.unit_id)) {
        const owner = model.sections.find((g) =>
          g.members.some((m) => m.paper === member.paper && m.unit_id === section.id),
        );
        if (owner) childIds.add(owner.group_id);
      }
    }
    for (const id of childIds) {
      const child = model.sections.find((g) => g.group_id === id)!;
      inspector.append(
        button(
          "Subsection: " + child.overarching_question,
          () => actions.navigate(id),
          "gx-related",
        ),
      );
    }
  }
  const compare = html("div", "gx-passages");
  // Keep present evidence adjacent; absent slots remain explicit after it.
  const present = new Set(group.members.map((m) => m.paper));
  const papers = model.papers
    .slice()
    .sort((a, b) => Number(present.has(b.paper_id)) - Number(present.has(a.paper_id)));
  if (comparing)
    inspector.append(
      html(
        "p",
        "",
        "Matched passages are adjacent. Scroll horizontally for the remaining papers and unmatched slots.",
      ),
    );
  for (const paper of papers) {
    const members = group.members
      .filter((m) => m.paper === paper.paper_id)
      .sort((a, b) => a.ordinal - b.ordinal);
    const card = html("article", "gx-passage" + (!members.length ? " missing" : ""));
    card.style.setProperty(
      "--paper",
      PAPER_COLORS[model.papers.indexOf(paper) % PAPER_COLORS.length],
    );
    card.append(html("h4", "", paper.title));
    if (!members.length)
      card.append(
        html(
          "p",
          "",
          "No member in this role. This is an unmatched slot, not evidence that the paper lacks the idea.",
        ),
      );
    for (const member of members) {
      const unit = (section ? paper.paragraphs : paper.sections).find(
        (u) => u.id === member.unit_id,
      )!;
      card.append(
        html("div", "gx-source", `${unit.title || member.tag} / ${member.unit_id}`),
        html("p", "gx-source-text", unit.text),
      );
      if (section) {
        const para = model.paragraphs.get(unitKey(paper.paper_id, member.unit_id))!;
        const sequence = paper.paragraphs
          .filter((p) => p.section_id === para.section_id)
          .slice()
          .sort((a, b) => a.ordinal - b.ordinal);
        const index = sequence.findIndex((p) => p.id === para.id);
        const nav = html("div", "gx-neighbors");
        for (const [label, neighbor] of [
          ["Previous passage", sequence[index - 1]],
          ["Next passage", sequence[index + 1]],
        ] as const) {
          if (!neighbor) continue;
          const owner = model.membership.get(unitKey(paper.paper_id, neighbor.id))!.group;
          nav.append(
            button(label, () => {
              actions.select(owner.group_id);
            }),
          );
        }
        card.append(nav);
      }
    }
    compare.append(card);
  }
  inspector.append(compare);
  inspector.scrollTop = 0;
}
