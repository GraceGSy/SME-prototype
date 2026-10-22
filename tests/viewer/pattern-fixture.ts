import type { Group, Paper, Snapshot } from "../../pipeline/viewer/src/contracts";

export function patternFixture(paths: Record<string, string[]>) {
  const groups = new Map<string, Group>();
  const papers: Paper[] = Object.entries(paths).map(([paper_id, roles]) => ({
    paper_id,
    title: paper_id,
    paragraphs: [],
    sections: roles.map((role, index) => {
      const id = `s${index + 1}`;
      const group = groups.get(role) ?? {
        group_id: role,
        overarching_question: `What is the ${role} role?`,
        parent_group_id: null,
        members: [],
      };
      group.members.push({
        paper: paper_id,
        unit_id: id,
        section_id: id,
        ordinal: index + 1,
        unit_type: "section",
        tag: "",
      });
      groups.set(role, group);
      return {
        id,
        title: role,
        text: `Source passage for ${role} in ${paper_id}.`,
        tag: "",
        ordinal: index + 1,
        unit_type: "section",
        parent_id: null,
      };
    }),
  }));
  const snapshot: Snapshot = {
    schema_version: 1,
    mode: "final_snapshot",
    section_groups: [...groups.values()],
    groups: [],
    singletons: [],
    stats: { section_nodes: groups.size, paragraph_nodes: 0 },
  };
  return { papers, snapshot };
}
