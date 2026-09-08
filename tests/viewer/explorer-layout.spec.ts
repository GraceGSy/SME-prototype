import { expect, test } from "@playwright/test";
import { explorerGraph, NODE_HEIGHT, NODE_WIDTH } from "../../pipeline/viewer/src/explorer-layout";
import { buildModel } from "../../pipeline/viewer/src/model";
import type { Group, Paper, Snapshot } from "../../pipeline/viewer/src/contracts";

function fixture() {
  const papers: Paper[] = ["a", "b"].map((paper_id) => ({
    paper_id,
    title: paper_id,
    sections: [
      {
        id: "s",
        title: "Intro",
        text: "Intro",
        tag: "",
        unit_type: "section",
        parent_id: null,
        ordinal: 1,
      },
      {
        id: "ss",
        title: "Detail",
        text: "Detail",
        tag: "",
        unit_type: "subsection",
        parent_id: "s",
        ordinal: 2,
      },
    ],
    paragraphs: [1, 2].map((ordinal) => ({
      id: `p${ordinal}`,
      title: "",
      text: "Evidence",
      tag: "",
      ordinal,
      section_id: "s",
      family_id: "s",
    })),
  }));
  const group = (
    id: string,
    units: [string, string][],
    type: "section" | "subsection" | "paragraph",
    parent: string | null,
  ): Group => ({
    group_id: id,
    overarching_question: "What role?",
    parent_group_id: parent,
    members: units.map(([paper, unit_id], i) => ({
      paper,
      unit_id,
      section_id: type === "paragraph" ? "s" : unit_id,
      tag: "",
      ordinal: i + 1,
      unit_type: type,
    })),
  });
  const snapshot: Snapshot = {
    schema_version: 1,
    mode: "final_snapshot",
    section_groups: [
      group(
        "section",
        [
          ["a", "s"],
          ["b", "s"],
        ],
        "section",
        null,
      ),
      group(
        "sub",
        [
          ["a", "ss"],
          ["b", "ss"],
        ],
        "subsection",
        null,
      ),
    ],
    groups: [
      group(
        "shared",
        [
          ["a", "p1"],
          ["b", "p1"],
        ],
        "paragraph",
        "section",
      ),
    ],
    singletons: [
      group("a-only", [["a", "p2"]], "paragraph", "section"),
      group("b-only", [["b", "p2"]], "paragraph", "section"),
    ],
    stats: { section_nodes: 2, paragraph_nodes: 3 },
  };
  return buildModel(papers, snapshot);
}

test("explorer retains exact membership, differences, and per-paper reading order", () => {
  const model = fixture();
  const before = JSON.stringify(model.papers);
  expect(explorerGraph(model, null).nodes).toHaveLength(1);
  expect(explorerGraph(model, null, true).nodes).toHaveLength(2);
  const graph = explorerGraph(model, "section");
  expect(graph.nodes).toHaveLength(3);
  expect(graph.edges).toEqual([
    { source: "shared", target: "a-only", paper: "a" },
    { source: "shared", target: "b-only", paper: "b" },
  ]);
  expect(explorerGraph(model, "sub").nodes).toHaveLength(0);
  expect(() => explorerGraph(model, "invented")).toThrow("Unknown explorer section");
  expect(JSON.stringify(model.papers)).toBe(before);
  for (let i = 0; i < graph.nodes.length; i++)
    for (let j = i + 1; j < graph.nodes.length; j++) {
      const a = graph.nodes[i],
        b = graph.nodes[j];
      expect(Math.abs(a.x - b.x) >= NODE_WIDTH || Math.abs(a.y - b.y) >= NODE_HEIGHT).toBe(true);
    }
});

test("explorer rejects a missing structural member instead of silently drawing a partial node", () => {
  const model = fixture();
  model.sections[0].members[0].unit_id = "missing";
  expect(() => explorerGraph(model, null)).toThrow("Unknown explorer source unit");
});
