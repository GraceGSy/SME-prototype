import { expect, test } from "@playwright/test";
import { participantRoute } from "../../pipeline/viewer/src/data";
import { buildModel } from "../../pipeline/viewer/src/model";
import { eventSchema, paperSchema, snapshotSchema } from "../../pipeline/viewer/src/contracts";
import { reduceEvents } from "../../pipeline/viewer/src/replay-state";

test("realignment replay preserves paragraph identity and immutable event history", () => {
  const member = {
    paper_id: "a",
    unit_id: "p",
    ordinal: 1,
    unit_kind: "paragraph",
    parent_unit_id: "s",
    family_id: "s",
    owner_group_id: "old",
    membership_role: "core",
  };
  const raw = [
    {
      action: "node_created",
      node_id: "old",
      level: "section",
      parent_id: null,
      member: { ...member, unit_id: "s", unit_kind: "section", owner_group_id: null },
    },
    {
      action: "node_created",
      node_id: "new",
      level: "section",
      parent_id: null,
      member: {
        ...member,
        paper_id: "b",
        unit_id: "s",
        unit_kind: "section",
        owner_group_id: null,
      },
    },
    { action: "node_created", node_id: "paragraph", level: "paragraph", parent_id: "old", member },
    {
      action: "node_merged",
      source_node_id: "old",
      target_node_id: "new",
      members: [{ ...member, unit_id: "s", unit_kind: "section", owner_group_id: null }],
      reason: "structural_rerepresentation",
      attempt_id: "forward",
      reverse_attempt_id: "reverse",
    },
    {
      action: "node_reparented",
      node_id: "paragraph",
      previous_parent_id: "old",
      parent_id: "new",
    },
  ];
  const events = raw.map((e, index) =>
    eventSchema.parse({ ...e, sequence: index + 1, event_id: `e${index}`, paper_index: 3 }),
  );
  const before = JSON.stringify(events);
  expect(reduceEvents(events, 3).nodes.get("paragraph")?.parentId).toBe("old");
  const final = reduceEvents(events);
  expect(final.nodes.has("old")).toBe(false);
  expect(final.nodes.get("paragraph")?.parentId).toBe("new");
  expect(final.nodes.get("paragraph")?.members[0].owner_group_id).toBe("new");
  expect(JSON.stringify(events)).toBe(before);
  const { reverse_attempt_id: _removed, ...oneWay } = raw[3];
  expect(() =>
    eventSchema.parse({ ...oneWay, sequence: 4, event_id: "e4", paper_index: 3 }),
  ).toThrow();
});

test("participant IDs are exact, not repaired", () => {
  const routes = { SH: { dataset_id: "sherlock", label: "Sherlock" } };
  expect(participantRoute("SH001", routes)).toBe("sherlock");
  for (const id of ["sh001", " SH001", "SH001 ", "SH1", "ZZ001"]) {
    expect(() => participantRoute(id, routes)).toThrow();
  }
});

test("contracts reject extra fields and wrong types", () => {
  expect(() =>
    paperSchema.parse({ paper_id: "a", title: "A", sections: [], paragraphs: [], old: true }),
  ).toThrow();
  expect(() => snapshotSchema.parse({ schema_version: "1", mode: "final_snapshot" })).toThrow();
});

test("membership cannot invent a paragraph or silently drop one", () => {
  const papers = [
    paperSchema.parse({
      paper_id: "a",
      title: "A",
      sections: [
        {
          id: "s",
          title: "S",
          text: "",
          tag: "",
          unit_type: "section",
          parent_id: null,
          ordinal: 1,
        },
      ],
      paragraphs: [
        {
          id: "p",
          title: "",
          text: "Original\n  text",
          tag: "Question?",
          section_id: "s",
          family_id: "s",
          ordinal: 1,
        },
      ],
    }),
  ];
  const snapshot = snapshotSchema.parse({
    schema_version: 1,
    mode: "final_snapshot",
    groups: [],
    singletons: [],
    section_groups: [],
    stats: { section_nodes: 0, paragraph_nodes: 0 },
  });
  expect(() => buildModel(papers, snapshot)).toThrow("every paragraph");
  const member = {
    paper: "a",
    unit_id: "p",
    section_id: "s",
    tag: "Question?",
    unit_type: "paragraph" as const,
    ordinal: 1,
  };
  const group = {
    group_id: "g",
    parent_group_id: null,
    overarching_question: "Question?",
    members: [member],
  };
  snapshot.singletons = [group];
  const model = buildModel(papers, snapshot);
  expect(model.paragraphs.get("a:p")?.text).toBe(papers[0].paragraphs[0].text);
  snapshot.singletons = [group, { ...group, group_id: "other" }];
  expect(() => buildModel(papers, snapshot)).toThrow("multiple groups");
  snapshot.singletons = [{ ...group, members: [{ ...member, unit_id: "invented" }] }];
  expect(() => buildModel(papers, snapshot)).toThrow("Unknown group member");
});
