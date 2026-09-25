import { z } from "zod";

const id = z.string().min(1);
const ordinal = z.number().int().positive();
const kind = z.enum(["section", "subsection", "paragraph"]);
const textUnit = { id, title: z.string(), text: z.string(), tag: z.string() };
export const paperSchema = z.strictObject({
  paper_id: id,
  title: id,
  sections: z.array(
    z.strictObject({
      ...textUnit,
      unit_type: z.enum(["section", "subsection"]),
      parent_id: id.nullable(),
      ordinal,
    }),
  ),
  paragraphs: z.array(
    z.strictObject({
      ...textUnit,
      section_id: id,
      family_id: id,
      ordinal,
    }),
  ),
});
export const groupSchema = z.strictObject({
  group_id: id,
  overarching_question: id,
  parent_group_id: id.nullable(),
  members: z
    .array(
      z.strictObject({
        paper: id,
        unit_id: id,
        section_id: id,
        tag: z.string(),
        unit_type: kind,
        ordinal,
      }),
    )
    .min(1),
});
export const snapshotSchema = z.strictObject({
  schema_version: z.literal(1),
  mode: z.literal("final_snapshot"),
  groups: z.array(groupSchema),
  singletons: z.array(groupSchema),
  section_groups: z.array(groupSchema),
  stats: z.strictObject({
    section_nodes: z.number().int().nonnegative(),
    paragraph_nodes: z.number().int().nonnegative(),
  }),
});
const fileName = z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9_.-]*\.json$/);
export const manifestSchema = z
  .array(z.strictObject({ paper_id: id, title: id, file: fileName }))
  .min(1);
export const descriptorSchema = z.strictObject({
  schema_version: z.literal(1),
  mode: z.literal("final_snapshot"),
  dataset_id: id,
  label: id,
  paper_count: ordinal,
  paragraph_count: z.number().int().nonnegative(),
  snapshot_file: z.literal("final_snapshot.json"),
  stats: snapshotSchema.shape.stats,
});
export const routeSchema = z.strictObject({
  dataset_id: z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/),
  label: id,
});
export const studySchema = z.strictObject({
  schema_version: z.literal(1),
  mode: z.literal("participant_routing"),
  participant_number_digits: z.literal(3),
  datasets: z.record(z.string().regex(/^[A-Z]{2}$/), routeSchema),
});
export type Paper = z.infer<typeof paperSchema>;
export type Paragraph = Paper["paragraphs"][number];
export type Group = z.infer<typeof groupSchema>;
export type Snapshot = z.infer<typeof snapshotSchema>;
export type Routes = z.infer<typeof studySchema>["datasets"];
