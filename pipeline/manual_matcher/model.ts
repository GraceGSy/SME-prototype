import { z } from "zod";
import {
  descriptorSchema,
  manifestSchema,
  paperSchema,
  snapshotSchema,
} from "../viewer/src/contracts";
import type { Group, Paper } from "../viewer/src/contracts";
import { buildModel, unitKey } from "../viewer/src/model";

const nonblank = z.string().refine((text) => text.trim().length > 0, "Must not be blank");
const question = nonblank.optional();
const paragraph = z.strictObject({
  paragraph_number: z.number().int().nonnegative(),
  text: nonblank,
  question_this_text_answers: question,
});
const paragraphs = z
  .array(paragraph)
  .refine(
    (items) => items.every((item, index) => item.paragraph_number === index),
    "Paragraph numbers must start at zero and be contiguous within each section",
  );
const structural = {
  section_name: nonblank,
  section_number: z.string().nullable().optional(),
  question_this_text_answers: nonblank.nullable().optional(),
  paragraphs,
};
export const documentSchema = z
  .array(
    z.strictObject({
      ...structural,
      subsections: z.array(z.strictObject(structural)),
    }),
  )
  .min(1);
export type SourceDocument = z.infer<typeof documentSchema>;
export const sourceSchema = z.strictObject({
  paper_id: z.string().regex(/^[a-zA-Z0-9_-]+$/),
  title: nonblank,
  filename: nonblank,
  content: documentSchema,
});
export type Source = z.infer<typeof sourceSchema>;
export type Mode = "section" | "subsection";
export type Level = "sections" | "paragraphs";
const annotationGroupSchema = z.strictObject({
  id: nonblank,
  members: z.array(nonblank).min(1),
  question: z.string(),
});
export type AnnotationGroup = z.infer<typeof annotationGroupSchema>;
const workspaceSchema = z.strictObject({
  sections: z.array(annotationGroupSchema),
  paragraphs: z.array(annotationGroupSchema),
  questions: z.record(z.string(), z.string()),
  outside: z.array(z.strictObject({ source: nonblank, target: nonblank })),
});
export type Workspace = z.infer<typeof workspaceSchema>;
export const sessionSchema = z.strictObject({
  schema_version: z.literal(1),
  kind: z.literal("manual_matching"),
  id: z.string().uuid(),
  title: nonblank,
  sources: z.tuple([sourceSchema, sourceSchema]),
  mode: z.enum(["section", "subsection"]),
  workspaces: z.strictObject({ section: workspaceSchema, subsection: workspaceSchema }),
});
export type Session = z.infer<typeof sessionSchema>;
export interface Unit {
  key: string;
  paper: string;
  id: string;
  title: string;
  text: string;
  section: string;
  kind: "section" | "subsection" | "paragraph";
  ordinal: number;
  question: string;
}

const position = (index: number): string => String(index + 1).padStart(4, "0");

// Match input_data.py: source positions own identity; section mode folds descendants,
// while subsection mode keeps each paragraph with its exact structural owner.
export function sourcePaper(source: Source, mode: Mode): Paper {
  const sections: Paper["sections"] = [];
  const items: Paper["paragraphs"] = [];
  source.content.forEach((section, sectionIndex) => {
    const root = `s${position(sectionIndex)}`;
    const family = [
      { data: section, id: root, parent: null },
      ...section.subsections.map((data, index) => ({
        data,
        id: `${root}.ss${position(index)}`,
        parent: root,
      })),
    ];
    const all = family.flatMap(({ data }) => data.paragraphs);
    let ordinal = 0;
    for (const { data, id, parent } of family) {
      const evidence = parent === null ? all : data.paragraphs;
      if (mode === "subsection" || parent === null) {
        if (evidence.length)
          sections.push({
            id,
            title: data.section_name,
            text: evidence.map((p) => p.text).join("\n\n"),
            tag: data.question_this_text_answers?.trim() ?? "",
            unit_type: parent === null ? "section" : "subsection",
            parent_id: parent,
            ordinal: sections.length + 1,
          });
      }
      data.paragraphs.forEach((p, index) =>
        items.push({
          id: `${id}.p${position(index)}`,
          title: String(p.paragraph_number),
          text: p.text,
          tag: p.question_this_text_answers?.trim() ?? "",
          section_id: mode === "section" ? root : id,
          family_id: root,
          ordinal: ++ordinal,
        }),
      );
    }
  });
  return paperSchema.parse({
    paper_id: source.paper_id,
    title: source.title,
    sections,
    paragraphs: items,
  });
}

export function units(session: Session, level: Level): Unit[] {
  return session.sources.flatMap<Unit>((source) => {
    const paper = sourcePaper(source, session.mode);
    return level === "sections"
      ? paper.sections.map((s) => ({
          key: unitKey(paper.paper_id, s.id),
          paper: paper.paper_id,
          id: s.id,
          title: s.title,
          text: s.text,
          section: s.id,
          kind: s.unit_type,
          ordinal: s.ordinal,
          question: s.tag,
        }))
      : paper.paragraphs.map((p) => ({
          key: unitKey(paper.paper_id, p.id),
          paper: paper.paper_id,
          id: p.id,
          title: `Paragraph ${p.ordinal}`,
          text: p.text,
          section: p.section_id,
          kind: "paragraph" as const,
          ordinal: p.ordinal,
          question: p.tag,
        }));
  });
}

export function workspace(session: Session): Workspace {
  return session.workspaces[session.mode];
}

export function createSession(sources: [Source, Source]): Session {
  const session: Session = {
    schema_version: 1,
    kind: "manual_matching",
    id: crypto.randomUUID(),
    title: `${sources[0].title} / ${sources[1].title}`,
    sources,
    mode: "section",
    workspaces: {} as Session["workspaces"],
  };
  for (const mode of ["section", "subsection"] as const) {
    session.mode = mode;
    const groups = (level: Level): AnnotationGroup[] =>
      units(session, level).map((unit, index) => ({
        id: `human-${mode}-${level}-${index + 1}`,
        members: [unit.key],
        question: "",
      }));
    session.workspaces[mode] = {
      sections: groups("sections"),
      paragraphs: groups("paragraphs"),
      questions: {},
      outside: [],
    };
  }
  session.mode = "section";
  return parseSession(session);
}

export function parseSession(payload: unknown): Session {
  const session = sessionSchema.parse(payload);
  if (session.sources[0].paper_id === session.sources[1].paper_id)
    throw new Error("Choose two different paper IDs");
  for (const mode of ["section", "subsection"] as const) {
    const scoped = { ...session, mode };
    const ws = workspace(scoped);
    const ids = new Set<string>();
    for (const level of ["sections", "paragraphs"] as const) {
      const valid = new Set(units(scoped, level).map((unit) => unit.key));
      const seen = new Set<string>();
      for (const group of ws[level]) {
        if (ids.has(group.id)) throw new Error("Duplicate group ID");
        ids.add(group.id);
        for (const key of group.members) {
          if (!valid.has(key) || seen.has(key))
            throw new Error("Every unit must belong to exactly one group");
          seen.add(key);
        }
      }
      if (seen.size !== valid.size) throw new Error("Labels omit source units");
    }
    const all = new Set(
      [...units(scoped, "sections"), ...units(scoped, "paragraphs")].map((unit) => unit.key),
    );
    if (Object.keys(ws.questions).some((key) => !all.has(key)))
      throw new Error("Question refers to an unknown unit");
    const ps = new Map(units(scoped, "paragraphs").map((unit) => [unit.key, unit]));
    for (const flag of ws.outside) {
      if (
        !ps.has(flag.source) ||
        !ps.has(flag.target) ||
        ps.get(flag.source)!.paper === ps.get(flag.target)!.paper
      )
        throw new Error("Invalid outside-group selection");
      if (
        !ws.paragraphs.some(
          (g) => g.members.includes(flag.source) && g.members.includes(flag.target),
        )
      )
        throw new Error("Outside-group selection disagrees with membership");
    }
  }
  return session;
}

export function membership(groups: AnnotationGroup[]): Map<string, AnnotationGroup> {
  return new Map(
    groups.flatMap((group) => group.members.map((member) => [member, group] as const)),
  );
}

export function groupUnits(
  session: Session,
  level: Level,
  selected: string[],
  questionText: string,
): void {
  if (!selected.length || new Set(selected).size !== selected.length)
    throw new Error("Select one or more distinct passages");
  const ws = workspace(session);
  const valid = new Set(units(session, level).map((unit) => unit.key));
  if (selected.some((key) => !valid.has(key))) throw new Error("Unknown selected passage");
  const chosen = new Set(selected);
  const existing = ws[level].find(
    (group) =>
      group.members.length === chosen.size && group.members.every((key) => chosen.has(key)),
  );
  if (existing) existing.question = questionText.trim();
  else {
    ws[level] = ws[level]
      .map((group) => ({ ...group, members: group.members.filter((key) => !chosen.has(key)) }))
      .filter((group) => group.members.length);
    ws[level].push({
      id: `human-${crypto.randomUUID()}`,
      members: selected,
      question: questionText.trim(),
    });
  }
  pruneFlags(ws);
}

export function ungroupUnits(session: Session, level: Level, selected: string[]): void {
  for (const key of selected) groupUnits(session, level, [key], "");
}

function pruneFlags(ws: Workspace): void {
  ws.outside = ws.outside.filter((flag) =>
    ws.paragraphs.some((g) => g.members.includes(flag.source) && g.members.includes(flag.target)),
  );
}

export function matchOutside(session: Session, source: string, target: string): void {
  const ws = workspace(session);
  const lookup = new Map(units(session, "paragraphs").map((unit) => [unit.key, unit]));
  if (
    !lookup.has(source) ||
    !lookup.has(target) ||
    lookup.get(source)!.paper === lookup.get(target)!.paper
  )
    throw new Error("Choose a paragraph in the other paper");
  const members = membership(ws.paragraphs);
  const first = members.get(source)!;
  const second = members.get(target)!;
  groupUnits(
    session,
    "paragraphs",
    [...new Set([...first.members, ...second.members])],
    first.question || second.question,
  );
  if (!ws.outside.some((flag) => flag.source === source && flag.target === target))
    ws.outside.push({ source, target });
}

export function exportDataset(session: Session) {
  parseSession(session);
  const ws = workspace(session);
  const papers = session.sources.map((source) => {
    const paper = sourcePaper(source, session.mode);
    for (const unit of [...paper.sections, ...paper.paragraphs])
      unit.tag = ws.questions[unitKey(paper.paper_id, unit.id)] ?? unit.tag;
    return paper;
  });
  const structuralMembership = membership(ws.sections);
  const makeGroups = (level: Level): Group[] => {
    const sourceUnits = units(session, level);
    const lookup = new Map(sourceUnits.map((unit) => [unit.key, unit]));
    const order = new Map(sourceUnits.map((unit, index) => [unit.key, index]));
    return ws[level].map((group, index) => {
      const members = [...group.members]
        .sort((a, b) => order.get(a)! - order.get(b)!)
        .map((key) => {
          const unit = lookup.get(key)!;
          return {
            paper: unit.paper,
            unit_id: unit.id,
            section_id: unit.section,
            tag: ws.questions[key] ?? unit.question,
            unit_type: unit.kind,
            ordinal: unit.ordinal,
          };
        });
      const parents = new Set(
        members.map((m) => structuralMembership.get(unitKey(m.paper, m.section_id))!.id),
      );
      return {
        group_id: group.id,
        overarching_question:
          group.question || `${level === "sections" ? "Section" : "Paragraph"} group ${index + 1}`,
        parent_group_id: level === "paragraphs" && parents.size === 1 ? [...parents][0] : null,
        members,
      };
    });
  };
  const sections = makeGroups("sections");
  const ps = makeGroups("paragraphs");
  const shared = (group: Group): boolean => new Set(group.members.map((m) => m.paper)).size > 1;
  const snapshot = snapshotSchema.parse({
    schema_version: 1,
    mode: "final_snapshot",
    groups: ps.filter(shared),
    singletons: ps.filter((g) => !shared(g)),
    section_groups: sections,
    stats: { section_nodes: sections.length, paragraph_nodes: ps.length },
  });
  buildModel(papers, snapshot);
  const manifest = manifestSchema.parse(
    papers.map((p) => ({ paper_id: p.paper_id, title: p.title, file: `${p.paper_id}.json` })),
  );
  const descriptor = descriptorSchema.parse({
    schema_version: 1,
    mode: "final_snapshot",
    dataset_id: `human-${session.id}`,
    label: session.title,
    paper_count: 2,
    paragraph_count: papers.reduce((sum, p) => sum + p.paragraphs.length, 0),
    snapshot_file: "final_snapshot.json",
    stats: snapshot.stats,
  });
  return { papers, manifest, snapshot, descriptor };
}

export function datasetFiles(session: Session): Record<string, string> {
  const { papers, manifest, snapshot, descriptor } = exportDataset(session);
  const json = (value: unknown): string => JSON.stringify(value, null, 2) + "\n";
  return {
    "manifest.json": json(manifest),
    "final_snapshot.json": json(snapshot),
    "dataset.json": json(descriptor),
    ...Object.fromEntries(papers.map((paper) => [`${paper.paper_id}.json`, json(paper)])),
  };
}
