import type { Group } from "./contracts";
import { type Model, unitKey } from "./model";

export interface ExplorerNode {
  group: Group;
  x: number;
  y: number;
  row: number;
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
  centerX: number;
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
export const COLUMN_GAP = 10;
export const ROW_GAP = 22;
const BOARD_PADDING = 72;
export const BOARD_TOP = 68;

function patternRows(
  ids: string[],
  edges: ExplorerEdge[],
  position: (id: string) => number,
): Map<string, number> {
  const next = new Map(ids.map((id) => [id, new Set<string>()]));
  const indegree = new Map(ids.map((id) => [id, 0]));
  const reaches = (from: string, to: string): boolean => {
    const pending = [from];
    const visited = new Set<string>();
    while (pending.length) {
      const id = pending.pop()!;
      if (id === to) return true;
      if (visited.has(id)) continue;
      visited.add(id);
      pending.push(...next.get(id)!);
    }
    return false;
  };
  // Prefer the most widely observed order when documents disagree. Keep every
  // original directed edge for display, including rejected cycle-forming ones.
  const transitions = collapseEdges(edges).sort(
    (a, b) =>
      b.papers.length - a.papers.length ||
      position(a.source) - position(b.source) ||
      position(a.target) - position(b.target) ||
      a.source.localeCompare(b.source) ||
      a.target.localeCompare(b.target),
  );
  for (const { source, target } of transitions) {
    if (reaches(target, source)) continue;
    next.get(source)!.add(target);
    indegree.set(target, indegree.get(target)! + 1);
  }
  const rows = new Map(ids.map((id) => [id, 0]));
  const ready = ids.filter((id) => indegree.get(id) === 0);
  for (let i = 0; i < ready.length; i++) {
    const source = ready[i];
    for (const target of next.get(source)!) {
      rows.set(target, Math.max(rows.get(target)!, rows.get(source)! + 1));
      indegree.set(target, indegree.get(target)! - 1);
      if (indegree.get(target) === 0) ready.push(target);
    }
  }
  return rows;
}

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
      ? [
          ...model.sections.filter(
            (g) => includeSubsections || g.members.some((m) => m.unit_type === "section"),
          ),
          // Manual cross-section matches have no single structural parent.
          ...[...model.groups.values()]
            .map((entry) => entry.group)
            .filter((group) => group.parent_group_id === null),
        ]
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
  const position = (id: string) => {
    const values = positions.get(id)!;
    return values.reduce((a, b) => a + b, 0) / values.length;
  };
  const nodes = groups.map((group) => {
    const papers = [...new Set(group.members.map((m) => m.paper))];
    if (papers.some((id) => !model.papers.some((p) => p.paper_id === id)))
      throw new Error("Unknown explorer source unit");
    if (!positions.has(group.group_id)) throw new Error("Unknown explorer source unit");
    return { group, papers, x: 0, y: 0, row: 0 };
  });
  const rows = patternRows(
    nodes.map((node) => node.group.group_id),
    edges,
    position,
  );
  const byRow = new Map<number, ExplorerNode[]>();
  for (const node of nodes) {
    node.row = rows.get(node.group.group_id)!;
    const row = byRow.get(node.row) ?? [];
    row.push(node);
    byRow.set(node.row, row);
  }
  for (const row of byRow.values()) {
    row.sort(
      (a, b) =>
        b.papers.length - a.papers.length ||
        position(a.group.group_id) - position(b.group.group_id) ||
        a.group.group_id.localeCompare(b.group.group_id),
    );
    row.forEach((node, index) => {
      // Rank options center-out. A lone optional role moves off the centerline
      // in proportion to missing documents, rather than looking universal.
      let lane: number;
      if (row.length === 1) {
        lane =
          ((model.papers.length - node.papers.length) / Math.max(1, model.papers.length - 1)) *
          (node.row % 2 ? -1 : 1);
      } else if (row.length % 2) {
        lane = Math.ceil(index / 2) * (index % 2 ? -1 : 1);
      } else {
        lane = (Math.floor(index / 2) + 0.5) * (index % 2 ? 1 : -1);
      }
      node.x = -NODE_WIDTH / 2 + lane * (NODE_WIDTH + COLUMN_GAP);
      node.y = BOARD_TOP + node.row * (NODE_HEIGHT + ROW_GAP);
    });
  }
  const left = Math.min(-NODE_WIDTH / 2, ...nodes.map((node) => node.x));
  const right = Math.max(NODE_WIDTH / 2, ...nodes.map((node) => node.x + NODE_WIDTH));
  const centerX = BOARD_PADDING - left;
  for (const node of nodes) node.x += centerX;
  nodes.sort((a, b) => a.row - b.row || a.x - b.x);
  return {
    nodes,
    edges,
    width: right - left + BOARD_PADDING * 2,
    height: Math.max(240, ...nodes.map((node) => node.y + NODE_HEIGHT + 48)),
    centerX,
  };
}
