import { z } from "zod";

const id = z.string().min(1);
const ordinal = z.number().int().positive();
const level = z.enum(["section", "paragraph"]);
const kind = z.enum(["section", "subsection", "paragraph"]);
const direction = z.enum(["new_to_group", "group_to_new", "singleton_to_group"]);
const textUnit = { id, title: z.string(), text: z.string(), tag: z.string() };
export const paperSchema = z.strictObject({
  paper_id: id, title: id,
  sections: z.array(z.strictObject({
    ...textUnit, unit_type: z.enum(["section", "subsection"]),
    parent_id: id.nullable(), ordinal,
  })),
  paragraphs: z.array(z.strictObject({
    ...textUnit, section_id: id, family_id: id, ordinal,
  })),
});
export const groupSchema = z.strictObject({
  group_id: id, overarching_question: id, parent_group_id: id.nullable(),
  members: z.array(z.strictObject({
    paper: id, unit_id: id, section_id: id, tag: z.string(), unit_type: kind, ordinal,
  })).min(1),
});
export const snapshotSchema = z.strictObject({
  schema_version: z.literal(1), mode: z.literal("final_snapshot"),
  groups: z.array(groupSchema), singletons: z.array(groupSchema),
  section_groups: z.array(groupSchema),
  stats: z.strictObject({ section_nodes: z.number().int().nonnegative(), paragraph_nodes: z.number().int().nonnegative() }),
});
const fileName = z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9_.-]*\.json$/);
export const manifestSchema = z.array(z.strictObject({ paper_id: id, title: id, file: fileName })).min(1);
export const descriptorSchema = z.strictObject({
  schema_version: z.literal(1), mode: z.literal("final_snapshot"),
  dataset_id: id, label: id, paper_count: ordinal, paragraph_count: z.number().int().nonnegative(),
  snapshot_file: z.literal("final_snapshot.json"),
  stats: snapshotSchema.shape.stats,
  graph_replay_file: z.literal("graph-replay.json").optional(),
});
export const routeSchema = z.strictObject({
  dataset_id: z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/), label: id,
});
export const studySchema = z.strictObject({
  schema_version: z.literal(1), mode: z.literal("participant_routing"),
  participant_number_digits: z.literal(3),
  datasets: z.record(z.string().regex(/^[A-Z]{2}$/), routeSchema),
});
const member = z.strictObject({
  paper_id: id, unit_id: id, ordinal, unit_kind: kind,
  parent_unit_id: id.nullable(), family_id: id.nullable(), owner_group_id: id.nullable(),
  membership_role: z.enum(["core", "fan_in"]).optional(),
});
const event = { sequence: ordinal, event_id: id, paper_index: ordinal };
export const eventSchema = z.discriminatedUnion("action", [
  z.strictObject({ ...event, action: z.literal("paper_added"), paper_id: id, title: id }),
  z.strictObject({ ...event, action: z.literal("node_created"), node_id: id, level, parent_id: id.nullable(), member }),
  z.strictObject({ ...event, action: z.literal("member_added"), node_id: id, member }),
  z.strictObject({ ...event, action: z.literal("node_merged"), source_node_id: id, target_node_id: id,
    members: z.array(member).min(1), reason: z.enum(["structural_rerepresentation", "adjacent_paragraph_fan_in"]), attempt_id: id.optional() }),
  z.strictObject({ ...event, action: z.literal("edge_created"), edge_id: id, source: id, target: id,
    kind: z.literal("contains"), paper_id: id }),
  z.strictObject({ ...event, action: z.literal("question_generated"), node_id: id, previous: z.string(),
    question: id, attempt_id: id.nullable(), source: id }),
  z.strictObject({ ...event, action: z.literal("match_recorded"), level, parent_id: id.nullable(),
    direction, source_id: id, target_id: id.nullable(), candidate_ids: z.array(id), attempt_id: id }),
  z.strictObject({ ...event, action: z.literal("projected_edge_ignored"), level, parent_id: id.nullable(),
    source_group_id: id, selected_unit_id: id, absorbed_group_id: id, attempt_id: id }),
  z.strictObject({ ...event, action: z.literal("rerepresentation_merge_ignored"),
    source_group_id: id, target_group_id: id, paper_id: id, reason: z.literal("target_already_contains_paper"), attempt_id: id }),
  z.strictObject({ ...event, action: z.literal("paragraph_fan_in_added"), inserted_paper_id: id,
    paper_id: id, node_id: id, parent_id: id.nullable(), unit_id: id, reciprocal_unit_id: id,
    direction, attempt_id: id, selected_unit_id: id.optional(), source_group_id: id.optional() }),
]);
const point = z.strictObject({ x: z.number().finite(), y: z.number().finite() });
export const replaySchema = z.strictObject({
  schema_version: z.literal(1), mode: z.literal("incremental_graph_replay"),
  paper_order: z.array(id), final_graph_hash: z.string().regex(/^[a-f0-9]{64}$/),
  layouts: z.record(level, z.record(id, point)),
  hierarchy_layouts: z.strictObject({ section: z.record(id, point) }),
  events: z.array(eventSchema),
});
export type Paper = z.infer<typeof paperSchema>;
export type Paragraph = Paper["paragraphs"][number];
export type Group = z.infer<typeof groupSchema>;
export type Snapshot = z.infer<typeof snapshotSchema>;
export type Replay = z.infer<typeof replaySchema>;
export type ReplayEvent = z.infer<typeof eventSchema>;
export type Member = z.infer<typeof member>;
export type Routes = z.infer<typeof studySchema>["datasets"];
