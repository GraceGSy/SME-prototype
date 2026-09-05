import type { Member, ReplayEvent } from "./contracts";

export interface ReplayNode {
  nodeId: string;
  level: "section" | "paragraph";
  parentId: string | null;
  members: Member[];
  question: string;
}
export type ReplayEdge = Extract<ReplayEvent, { action: "edge_created" }>;
export interface ReplayState {
  papers: string[];
  nodes: Map<string, ReplayNode>;
  edges: Map<string, ReplayEdge>;
}

export function reduceEvents(events: ReplayEvent[], endIndex = events.length): ReplayState {
  const state: ReplayState = { papers: [], nodes: new Map(), edges: new Map() };
  const node = (id: string): ReplayNode => {
    const value = state.nodes.get(id);
    if (!value) throw new Error(`Replay references unknown node: ${id}`);
    return value;
  };
  for (const event of events.slice(0, endIndex)) {
    switch (event.action) {
      case "paper_added":
        if (state.papers.includes(event.paper_id)) throw new Error("Replay adds a paper twice");
        state.papers.push(event.paper_id);
        break;
      case "node_created":
        if (state.nodes.has(event.node_id)) throw new Error("Replay creates a node twice");
        state.nodes.set(event.node_id, { nodeId: event.node_id, level: event.level,
          parentId: event.parent_id, members: [event.member], question: "" });
        break;
      case "member_added":
        node(event.node_id).members.push(event.member);
        break;
      case "node_merged":
        node(event.source_node_id);
        node(event.target_node_id).members.push(...event.members);
        state.nodes.delete(event.source_node_id);
        for (const [id, edge] of state.edges) {
          if (edge.source === event.source_node_id || edge.target === event.source_node_id) state.edges.delete(id);
        }
        break;
      case "edge_created":
        node(event.source);
        node(event.target);
        if (state.edges.has(event.edge_id)) throw new Error("Replay creates an edge twice");
        state.edges.set(event.edge_id, event);
        break;
      case "question_generated":
        node(event.node_id).question = event.question;
        break;
      // The remaining events are judgment provenance, not graph mutations.
      case "match_recorded":
      case "projected_edge_ignored":
      case "rerepresentation_merge_ignored":
      case "paragraph_fan_in_added":
        break;
    }
  }
  return state;
}
