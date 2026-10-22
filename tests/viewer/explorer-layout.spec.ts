import { expect, test } from "@playwright/test";
import {
  collapseEdges,
  explorerGraph,
  NODE_HEIGHT,
  NODE_WIDTH,
  ROW_GAP,
  COLUMN_GAP,
} from "../../pipeline/viewer/src/explorer-layout";
import { buildModel } from "../../pipeline/viewer/src/model";
import type { Group, Paper, Snapshot } from "../../pipeline/viewer/src/contracts";
import { patternFixture } from "./pattern-fixture";

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
  expect(graph.nodes).toHaveLength(4);
  expect(graph.edges).toEqual([
    { source: "shared", target: "a-only", paper: "a" },
    { source: "a-only", target: "sub", paper: "a" },
    { source: "shared", target: "b-only", paper: "b" },
    { source: "b-only", target: "sub", paper: "b" },
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

test("collapsed arrows preserve direction and exact contributing paper paths", () => {
  const edges = [
    { source: "intro", target: "method", paper: "a" },
    { source: "intro", target: "method", paper: "b" },
    { source: "method", target: "intro", paper: "c" },
  ];
  const before = JSON.stringify(edges);
  expect(collapseEdges(edges)).toEqual([
    { source: "intro", target: "method", papers: ["a", "b"] },
    { source: "method", target: "intro", papers: ["c"] },
  ]);
  expect(JSON.stringify(edges)).toBe(before);
});

test("pattern rows align alternatives and place frequent options nearest the center", () => {
  const { papers, snapshot } = patternFixture({
    a: ["intro", "common", "end"],
    b: ["intro", "common", "end"],
    c: ["intro", "common", "end"],
    d: ["intro", "other", "end"],
    e: ["intro", "rare", "end"],
  });
  const before = JSON.stringify({ papers, snapshot });
  const graph = explorerGraph(buildModel(papers, snapshot), null);
  expect(new Set(graph.nodes.map((node) => node.row)).size).toBe(3);
  const options = graph.nodes.filter((node) => node.row === 1);
  expect(options).toHaveLength(3);
  expect(new Set(options.map((node) => node.y)).size).toBe(1);
  const common = options.find((node) => node.group.group_id === "common")!;
  expect(common.x + NODE_WIDTH / 2).toBe(graph.centerX);
  expect(common.papers).toHaveLength(3);
  expect(options[1].x - options[0].x).toBe(NODE_WIDTH + COLUMN_GAP);
  expect(options[2].x - options[1].x).toBe(NODE_WIDTH + COLUMN_GAP);
  expect(graph.nodes.find((node) => node.row === 2)!.y - common.y).toBe(NODE_HEIGHT + ROW_GAP);
  expect(JSON.stringify({ papers, snapshot })).toBe(before);
});

test("an omitted role leaves a real document edge that skips a board row", () => {
  const { papers, snapshot } = patternFixture({
    a: ["intro", "optional", "end"],
    b: ["intro", "end"],
  });
  const graph = explorerGraph(buildModel(papers, snapshot), null);
  const intro = graph.nodes.find((node) => node.group.group_id === "intro")!;
  const end = graph.nodes.find((node) => node.group.group_id === "end")!;
  const optional = graph.nodes.find((node) => node.group.group_id === "optional")!;
  expect(end.row - intro.row).toBe(2);
  expect(intro.x + NODE_WIDTH / 2).toBe(graph.centerX);
  expect(optional.x).not.toBe(intro.x);
  expect(graph.edges).toContainEqual({ source: "intro", target: "end", paper: "b" });
});

test("even rows remain tightly packed and order options center-out by coverage", () => {
  const { papers, snapshot } = patternFixture({
    a: ["intro", "common", "end"],
    b: ["intro", "common", "end"],
    c: ["intro", "common", "end"],
    d: ["intro", "other", "end"],
    e: ["intro", "other", "end"],
    f: ["intro", "rare", "end"],
    g: ["intro", "unique", "end"],
  });
  const graph = explorerGraph(buildModel(papers, snapshot), null);
  const options = graph.nodes.filter((node) => node.row === 1);
  expect(options).toHaveLength(4);
  for (let i = 1; i < options.length; i++)
    expect(options[i].x - options[i - 1].x).toBe(NODE_WIDTH + COLUMN_GAP);
  const distance = (node: (typeof options)[number]) =>
    Math.abs(node.x + NODE_WIDTH / 2 - graph.centerX);
  const ranked = options
    .slice()
    .sort((a, b) => distance(a) - distance(b) || b.papers.length - a.papers.length);
  expect(ranked.map((node) => node.papers.length)).toEqual([3, 2, 1, 1]);
});

test("majority order defines rows without rewriting a reversing document's path", () => {
  const { papers, snapshot } = patternFixture({
    reverse: ["end", "middle", "intro"],
    a: ["intro", "middle", "end"],
    b: ["intro", "middle", "end"],
  });
  const graph = explorerGraph(buildModel(papers, snapshot), null);
  expect(graph.nodes.map((node) => [node.group.group_id, node.row])).toEqual([
    ["intro", 0],
    ["middle", 1],
    ["end", 2],
  ]);
  expect(graph.edges.filter((edge) => edge.paper === "reverse")).toEqual([
    { source: "end", target: "middle", paper: "reverse" },
    { source: "middle", target: "intro", paper: "reverse" },
  ]);
});

test("coverage counts distinct documents, not repeated members of the same role", () => {
  const { papers, snapshot } = patternFixture({
    a: ["intro", "intro", "end"],
    b: ["intro", "end"],
  });
  const graph = explorerGraph(buildModel(papers, snapshot), null);
  const intro = graph.nodes.find((node) => node.group.group_id === "intro")!;
  expect(intro.group.members).toHaveLength(3);
  expect(intro.papers).toEqual(["a", "b"]);
  expect(graph.edges).toHaveLength(2);
});
