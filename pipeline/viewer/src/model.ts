import type { Group, Paper, Paragraph, Snapshot } from "./contracts";

export interface GroupEntry {
  group: Group;
  singleton: boolean;
  color: string;
  fill: string;
}
export interface Model {
  papers: Paper[];
  shared: GroupEntry[];
  singletons: GroupEntry[];
  groups: Map<string, GroupEntry>;
  paragraphs: Map<string, Paragraph>;
  membership: Map<string, GroupEntry>;
}
const HUES = [205, 25, 145, 48, 275, 175, 350, 95, 230, 8, 160, 62];
export const PAPER_COLORS = ["#4c6ef5", "#f76707", "#37b24d", "#e64980", "#ae3ec9", "#f59f00"];
export const unitKey = (paper: string, unit: string): string => `${paper}:${unit}`;

// Canonical graph nodes partition paragraphs; ambiguous or incomplete exports are errors.
export function buildModel(papers: Paper[], snapshot: Snapshot): Model {
  const paragraphs = new Map<string, Paragraph>();
  const paperIds = new Set<string>();
  for (const paper of papers) {
    if (paperIds.has(paper.paper_id)) throw new Error("Duplicate paper ID");
    paperIds.add(paper.paper_id);
    const sectionIds = new Set(paper.sections.map(section => section.id));
    if (sectionIds.size !== paper.sections.length) throw new Error("Duplicate section ID");
    for (const paragraph of paper.paragraphs) {
      const key = unitKey(paper.paper_id, paragraph.id);
      if (!sectionIds.has(paragraph.section_id)) throw new Error("Unknown paragraph section");
      if (paragraphs.has(key)) throw new Error("Duplicate paragraph ID");
      paragraphs.set(key, paragraph);
    }
  }
  const groups = new Map<string, GroupEntry>();
  const membership = new Map<string, GroupEntry>();
  const entries = (items: Group[], singleton: boolean): GroupEntry[] => items.map((group, index) => {
    if (groups.has(group.group_id)) throw new Error("Duplicate group ID");
    const hue = HUES[index % HUES.length] + Math.floor(index / HUES.length) * 11;
    const entry = { group, singleton, color: singleton ? "#868e96" : `hsl(${hue % 360} 58% 38%)`,
      fill: singleton ? "#f8f9fa" : `hsl(${hue % 360} 72% 95%)` };
    const represented = new Set(group.members.map(member => member.paper));
    if (singleton ? represented.size !== 1 : represented.size < 2) throw new Error("Incorrect shared/singleton classification");
    groups.set(group.group_id, entry);
    for (const member of group.members) {
      const key = unitKey(member.paper, member.unit_id);
      if (!paragraphs.has(key)) throw new Error("Unknown group member");
      if (membership.has(key)) throw new Error("Paragraph appears in multiple groups");
      membership.set(key, entry);
    }
    return entry;
  });
  const shared = entries(snapshot.groups, false);
  const singletons = entries(snapshot.singletons, true);
  if (membership.size !== paragraphs.size) throw new Error("Snapshot does not account for every paragraph");
  return { papers, shared, singletons, groups, paragraphs, membership };
}
