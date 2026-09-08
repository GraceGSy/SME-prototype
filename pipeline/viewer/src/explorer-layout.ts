import type { Group } from "./contracts";
import { type Model, unitKey } from "./model";

export interface ExplorerNode {
  group: Group;
  x: number;
  y: number;
  papers: string[];
}
export interface ExplorerEdge {
  source: string;
  target: string;
  paper: string;
}
export interface ExplorerGraph {
  nodes: ExplorerNode[];
  edges: ExplorerEdge[];
  width: number;
  height: number;
}
export interface CollapsedEdge {
  source: string;
  target: string;
  papers: string[];
}

// Collapse only the drawing, never the underlying directed paper paths.
export function collapseEdges(edges: ExplorerEdge[]): CollapsedEdge[] {
  const collapsed = new Map<string, CollapsedEdge>();
  for (const edge of edges) {
    const key = JSON.stringify([edge.source, edge.target]);
    const item = collapsed.get(key) ?? { source: edge.source, target: edge.target, papers: [] };
    if (!item.papers.includes(edge.paper)) item.papers.push(edge.paper);
    collapsed.set(key, item);
  }
  return [...collapsed.values()];
}
export const NODE_WIDTH = 224;
export const NODE_HEIGHT = 106;

// Layout positions are presentation only. Membership and reading order come
// exclusively from the exported graph and the original document ordinals.
export function explorerGraph(
  model: Model,
  sectionId: string | null,
  includeSubsections = false,
): ExplorerGraph {
  const parent = model.sections.find((g) => g.group_id === sectionId);
  if (sectionId !== null && !parent) throw new Error("Unknown explorer section");
  const groups =
    sectionId === null
      ? model.sections.filter(
          (g) => includeSubsections || g.members.some((m) => m.unit_type === "section"),
        )
      : [
          ...model.sections.filter(
            (group) =>
              group.group_id !== sectionId &&
              group.members.some((member) => {
                const paper = model.papers.find((p) => p.paper_id === member.paper);
                const source = paper?.sections.find((s) => s.id === member.unit_id);
                return parent!.members.some(
                  (m) => m.paper === member.paper && m.unit_id === source?.parent_id,
                );
              }),
          ),
          ...[...model.groups.values()]
            .map((entry) => entry.group)
            .filter((group) => group.parent_group_id === sectionId),
        ];
  const membership = new Map<string, string>();
  for (const group of groups) {
    for (const member of group.members) {
      const key = unitKey(member.paper, member.unit_id);
      const paper = model.papers.find((p) => p.paper_id === member.paper);
      const units = paper && (member.unit_type === "paragraph" ? paper.paragraphs : paper.sections);
      if (!units?.some((unit) => unit.id === member.unit_id))
        throw new Error("Unknown explorer source unit");
      if (membership.has(key)) throw new Error("Duplicate explorer membership");
      membership.set(key, group.group_id);
    }
  }
  const positions = new Map<string, number[]>();
  const edges: ExplorerEdge[] = [];
  model.papers.forEach((paper) => {
    // Flatten source sections and their paragraphs in document order. A section
    // heading precedes its text; these are reading-order edges, not relations.
    const ordered = paper.sections
      .slice()
      .sort((a, b) => a.ordinal - b.ordinal)
      .flatMap((section) => [
        section,
        ...paper.paragraphs
          .filter((p) => p.section_id === section.id)
          .sort((a, b) => a.ordinal - b.ordinal),
      ]);
    const units = ordered.filter((unit) => membership.has(unitKey(paper.paper_id, unit.id)));
    let previous: string | undefined;
    const seenEdges = new Set<string>();
    units.forEach((unit, index) => {
      const node = membership.get(unitKey(paper.paper_id, unit.id))!;
      const values = positions.get(node) ?? [];
      values.push(index / Math.max(1, units.length - 1));
      positions.set(node, values);
      const key = `${previous}:${node}`;
      if (previous && previous !== node && !seenEdges.has(key)) {
        edges.push({ source: previous, target: node, paper: paper.paper_id });
        seenEdges.add(key);
      }
      previous = node;
    });
  });
  const rows = Math.max(3, Math.ceil(groups.length / Math.max(1, model.papers.length)));
  const occupied: { x: number; y: number }[] = [];
  const nodes = groups
    .map((group) => {
      const papers = [...new Set(group.members.map((m) => m.paper))];
      const indexes = papers.map((id) => model.papers.findIndex((p) => p.paper_id === id));
      if (indexes.some((index) => index < 0) || !positions.has(group.group_id))
        throw new Error("Unknown explorer source unit");
      const values = positions.get(group.group_id)!;
      return {
        group,
        papers,
        x:
          papers.length > 1
            ? 48 + Math.floor(model.papers.length / 2) * 280
            : 48 +
              (indexes[0] >= Math.floor(model.papers.length / 2) ? indexes[0] + 1 : indexes[0]) *
                280,
        y: 75 + (values.reduce((a, b) => a + b, 0) / values.length) * rows * 145,
      };
    })
    .sort((a, b) => a.y - b.y || a.group.group_id.localeCompare(b.group.group_id));
  for (const node of nodes) {
    while (
      occupied.some(
        (p) =>
          Math.abs(p.x - node.x) < NODE_WIDTH + 18 && Math.abs(p.y - node.y) < NODE_HEIGHT + 28,
      )
    )
      node.y += NODE_HEIGHT + 28;
    occupied.push(node);
  }
  return {
    nodes,
    edges,
    width: Math.max(700, (model.papers.length + 1) * 280 + 40),
    height: Math.max(400, ...nodes.map((node) => node.y + NODE_HEIGHT + 70)),
  };
}
