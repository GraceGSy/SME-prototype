import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { buildModel } from "../pipeline/viewer/src/model";
import { explorerGraph } from "../pipeline/viewer/src/explorer-layout";
import {
  OUTSIDE_SOURCE,
  OUTSIDE_TARGET,
  PRACTICE_SOURCES,
  TUTORIAL_STEPS,
  practiceState,
} from "../pipeline/manual_matcher/tutorial";
import {
  createSession,
  datasetFiles,
  documentSchema,
  exportDataset,
  groupUnits,
  matchOutside,
  membership,
  parseSession,
  sourcePaper,
  ungroupUnits,
  units,
  workspace,
  type Source,
} from "../pipeline/manual_matcher/model";

const source = (id: string): Source => ({
  paper_id: id,
  title: id.toUpperCase(),
  filename: `${id}.json`,
  content: [
    {
      section_name: "Introduction",
      section_number: "1",
      paragraphs: [{ paragraph_number: 0, text: `Introduction ${id}.` }],
      subsections: [
        {
          section_name: "Background",
          section_number: "1.1",
          paragraphs: [
            { paragraph_number: 0, text: `Background ${id}.` },
            { paragraph_number: 1, text: `More background ${id}.` },
          ],
        },
      ],
    },
    {
      section_name: "Results",
      section_number: "2",
      paragraphs: [{ paragraph_number: 0, text: `Results ${id}.` }],
      subsections: [],
    },
  ],
});
const session = () => createSession([source("a"), source("b")]);

test("source IDs, exact ownership, and paragraph order agree with pipeline loading", () => {
  const sections = sourcePaper(source("a"), "section");
  const subsections = sourcePaper(source("a"), "subsection");
  assert.deepEqual(
    sections.sections.map((s) => s.id),
    ["s0001", "s0002"],
  );
  assert.deepEqual(
    subsections.sections.map((s) => s.id),
    ["s0001", "s0001.ss0001", "s0002"],
  );
  assert.equal(sections.paragraphs[1].id, "s0001.ss0001.p0001");
  assert.equal(sections.paragraphs[1].section_id, "s0001");
  assert.equal(subsections.paragraphs[1].section_id, "s0001.ss0001");
  assert.deepEqual(
    subsections.paragraphs.map((p) => p.ordinal),
    [1, 2, 3, 1],
  );
});

test("browser loading agrees exactly with Python on both real HCI papers and granularities", () => {
  const cases = ["abstractexplorer", "corpusstudio"].flatMap((id) => {
    const content = documentSchema.parse(
      JSON.parse(readFileSync(`datasets/hci-five-paper/content/${id}.content.json`, "utf8")),
    );
    return (["section", "subsection"] as const).map((mode) => ({
      source: { paper_id: id, title: id, filename: `${id}.json`, content },
      mode,
    }));
  });
  const python = spawnSync(
    "python",
    [
      "-c",
      "import json,sys; from pipeline.incremental_graph.input_data import _from_canonical_document; from pipeline.incremental_graph.export import _viewer_paper; cases=json.load(sys.stdin); json.dump([_viewer_paper(_from_canonical_document(c['source']['content'],c['source']['paper_id'],c['source']['title'],c['mode'])) for c in cases],sys.stdout,ensure_ascii=True)",
    ],
    { input: JSON.stringify(cases), encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1" } },
  );
  assert.equal(python.status, 0, python.stderr);
  assert.deepEqual(
    cases.map((c) => sourcePaper(c.source, c.mode)),
    JSON.parse(python.stdout),
  );
});

test("strict canonical import rejects unknown fields, blank text, and broken numbering", () => {
  const invalid = source("a").content;
  assert.throws(() => documentSchema.parse({ sections: invalid }));
  assert.throws(() => documentSchema.parse([{ ...invalid[0], extra: true }]));
  assert.throws(() =>
    documentSchema.parse([{ ...invalid[0], paragraphs: [{ paragraph_number: 1, text: "x" }] }]),
  );
  assert.throws(() =>
    documentSchema.parse([{ ...invalid[0], paragraphs: [{ paragraph_number: 0, text: " " }] }]),
  );
});

test("many-to-many grouping moves only selected units and partitions every level", () => {
  const s = session();
  const keys = units(s, "sections").map((u) => u.key);
  groupUnits(s, "sections", keys, "What is the contribution?");
  assert.equal(workspace(s).sections.length, 1);
  assert.equal(workspace(s).sections[0].members.length, 4);
  groupUnits(s, "sections", [keys[0], keys[2]], "Introductory role");
  assert.equal(workspace(s).sections.length, 2);
  assert.equal(membership(workspace(s).sections).size, 4);
  assert.doesNotThrow(() => parseSession(s));
  assert.doesNotThrow(() => exportDataset(s));
});

test("switching granularity preserves independent labels and stable paragraph identity", () => {
  const s = session();
  groupUnits(s, "sections", ["a:s0001", "b:s0001"], "Introduction");
  s.mode = "subsection";
  assert.ok(workspace(s).sections.every((g) => g.members.length === 1));
  groupUnits(s, "sections", ["a:s0001.ss0001", "b:s0001.ss0001"], "Background");
  s.mode = "section";
  assert.equal(workspace(s).sections.find((g) => g.members.length > 1)!.question, "Introduction");
  assert.doesNotThrow(() => parseSession(s));
});

test("outside matching merges existing groups, records flag, and uses no false parent", () => {
  const s = session();
  groupUnits(s, "sections", ["a:s0001", "b:s0001"], "Introduction");
  groupUnits(s, "paragraphs", ["a:s0001.p0001", "b:s0001.p0001"], "Motivation");
  matchOutside(s, "a:s0001.p0001", "b:s0002.p0001");
  const result = exportDataset(s);
  const group = result.snapshot.groups[0];
  assert.equal(group.members.length, 3);
  assert.equal(group.parent_group_id, null);
  assert.equal(workspace(s).outside.length, 1);
  const model = buildModel(result.papers, result.snapshot);
  assert.ok(explorerGraph(model, null).nodes.some((n) => n.group.group_id === group.group_id));
  ungroupUnits(s, "paragraphs", ["b:s0002.p0001"]);
  assert.equal(workspace(s).outside.length, 0);
  assert.doesNotThrow(() => parseSession(s));
});

test("outside matching rejects a paragraph from the same paper", () => {
  const s = session();
  assert.throws(() => matchOutside(s, "a:s0001.p0001", "a:s0002.p0001"));
});

test("source and shared questions are optional and preserve exact original text", () => {
  const s = session();
  s.sources[0].content[0].paragraphs[0].text = "  Original\n text.  ";
  groupUnits(s, "sections", ["a:s0001", "b:s0001"], "");
  groupUnits(s, "paragraphs", ["a:s0001.p0001", "b:s0001.p0001"], "");
  workspace(s).questions["a:s0001.p0001"] = "Why?";
  const result = exportDataset(s);
  assert.equal(result.papers[0].paragraphs[0].text, "  Original\n text.  ");
  assert.equal(result.papers[0].paragraphs[0].tag, "Why?");
  assert.ok(result.snapshot.groups[0].overarching_question);
  assert.equal(
    result.snapshot.groups[0].parent_group_id,
    result.snapshot.section_groups.find((g) => g.members.length > 1)!.group_id,
  );
});

test("saved labels reject duplicate, missing, unknown, and inconsistent members", () => {
  const s = session();
  const duplicate = structuredClone(s);
  workspace(duplicate).sections[1].members.push(workspace(duplicate).sections[0].members[0]);
  assert.throws(() => parseSession(duplicate));
  const missing = structuredClone(s);
  workspace(missing).paragraphs.pop();
  assert.throws(() => parseSession(missing));
  const unknown = structuredClone(s);
  workspace(unknown).paragraphs[0].members[0] = "a:invented";
  assert.throws(() => parseSession(unknown));
  const flag = structuredClone(s);
  workspace(flag).outside.push({ source: "a:s0001.p0001", target: "b:s0001.p0001" });
  assert.throws(() => parseSession(flag));
});

test("save/reopen and viewer files round-trip in both modes on real HCI inputs", () => {
  const sources = ["abstractexplorer", "corpusstudio"].map((id) => ({
    paper_id: id,
    title: id,
    filename: `${id}.content.json`,
    content: documentSchema.parse(
      JSON.parse(readFileSync(`datasets/hci-five-paper/content/${id}.content.json`, "utf8")),
    ),
  })) as [Source, Source];
  const s = createSession(sources);
  for (const mode of ["section", "subsection"] as const) {
    s.mode = mode;
    const first = units(s, "sections").filter((u) => u.paper === sources[0].paper_id)[0];
    const second = units(s, "sections").filter((u) => u.paper === sources[1].paper_id)[0];
    groupUnits(s, "sections", [first.key, second.key], "");
    const restored = parseSession(JSON.parse(JSON.stringify(s)));
    assert.deepEqual(restored, s);
    const files = datasetFiles(restored);
    assert.deepEqual(Object.keys(files).sort(), [
      "abstractexplorer.json",
      "corpusstudio.json",
      "dataset.json",
      "final_snapshot.json",
      "manifest.json",
    ]);
    const result = exportDataset(restored);
    assert.ok(result.descriptor.paragraph_count > 100);
    assert.equal(result.snapshot.groups.length, 0);
    assert.equal(result.snapshot.singletons.length, result.descriptor.paragraph_count);
  }
});

test("repeated regrouping and separating never duplicates or loses paragraphs", () => {
  const s = session();
  const keys = units(s, "paragraphs").map((u) => u.key);
  for (let i = 0; i < 60; i++) {
    const selected = [
      ...new Set([
        keys[i % keys.length],
        keys[(i * 3 + 1) % keys.length],
        keys[(i + 5) % keys.length],
      ]),
    ];
    groupUnits(s, "paragraphs", selected, "");
    if (i % 3 === 0) ungroupUnits(s, "paragraphs", [selected[0]]);
    assert.doesNotThrow(() => parseSession(s));
    assert.equal(exportDataset(s).descriptor.paragraph_count, keys.length);
  }
});

test("every tutorial example is valid and independent of previous practice edits", () => {
  const original = structuredClone(PRACTICE_SOURCES);
  for (const step of TUTORIAL_STEPS) {
    const state = practiceState(step.id);
    assert.doesNotThrow(() => parseSession(state.session));
    assert.equal(exportDataset(state.session).descriptor.paragraph_count, 6);
    groupUnits(
      state.session,
      "sections",
      units(state.session, "sections").map((u) => u.key),
      "Changed during practice",
    );
    assert.equal(practiceState(step.id).session.sources[0].title, "Paper A (practice)");
  }
  assert.deepEqual(PRACTICE_SOURCES, original);
  assert.equal(workspace(practiceState("select").session).sections.length, 4);
  assert.equal(workspace(practiceState("sections").session).sections.length, 3);
});

test("the final tutorial example records the outside match without changing source ownership", () => {
  const { session: s, selected } = practiceState("save");
  assert.deepEqual(workspace(s).outside, [{ source: OUTSIDE_SOURCE, target: OUTSIDE_TARGET }]);
  assert.deepEqual(new Set(selected), new Set([OUTSIDE_SOURCE, OUTSIDE_TARGET]));
  const result = exportDataset(s);
  assert.equal(result.snapshot.groups.length, 2);
  assert.equal(
    result.snapshot.groups.find((g) =>
      g.members.some((m) => m.paper === "practice_b" && m.unit_id === "s0002.p0001"),
    )!.parent_group_id,
    null,
  );
  assert.equal(
    result.papers[1].paragraphs.find((p) => p.id === "s0002.p0001")!.section_id,
    "s0002",
  );
});
