import { expect, test } from "@playwright/test";
import { participantRoute } from "../../pipeline/viewer/src/data";
import { buildModel } from "../../pipeline/viewer/src/model";
import { paperSchema, snapshotSchema } from "../../pipeline/viewer/src/contracts";

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
