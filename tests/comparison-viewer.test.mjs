import assert from "node:assert/strict";
import { test } from "node:test";
import {
  escapeHtml,
  filterRows,
  reviewRows,
  sourceLabel,
} from "../pipeline/comparison_viewer/app.mjs";

const sources = Object.fromEntries(
  ["a", "b", "c", "d"].map((key) => [key, { paper: key, text: `${key} passage`, title: key }]),
);
const assignment = (members, scope = [], question = "Question?") => ({ members, scope, question });
const data = {
  sources,
  assignments: {
    left: {
      a: assignment(["a", "b"]),
      b: assignment(["a", "b"]),
      c: assignment(["c"]),
      d: assignment(["d"], ["old"]),
    },
    right: {
      a: assignment(["a"]),
      b: assignment(["b", "c"]),
      c: assignment(["b", "c"]),
      d: assignment(["d"], ["new"]),
    },
  },
};

test("classifies removed, mixed, added, and scope-only changes without counting self", () => {
  const rows = reviewRows(data);
  assert.deepEqual(
    rows.map((row) => row.status),
    ["removed", "mixed", "added", "scope"],
  );
  assert.deepEqual(rows[1].removed, ["a"]);
  assert.deepEqual(rows[1].added, ["c"]);
  assert.deepEqual(rows[0].newPeers, []);
  assert.deepEqual(data.assignments.left.a.members, ["a", "b"]);
});

test("question-only changes do not become membership changes", () => {
  const copy = structuredClone(data);
  copy.assignments.right = structuredClone(copy.assignments.left);
  copy.assignments.right.a.question = "Different wording?";
  assert.ok(reviewRows(copy).every((row) => row.status === "same"));
});

test("filters membership changes separately from scope changes", () => {
  const rows = reviewRows(data);
  const filter = (name) =>
    filterRows(rows, { filter: name, paper: "", search: "" }, sources).map((row) => row.key);
  assert.deepEqual(filter("changes"), ["a", "b", "c"]);
  assert.deepEqual(filter("scope"), ["d"]);
  assert.deepEqual(filter("added"), ["c"]);
  assert.deepEqual(filter("removed"), ["a"]);
  assert.deepEqual(filter("mixed"), ["b"]);
  assert.deepEqual(filter("all"), ["a", "b", "c", "d"]);
});

test("search includes partner passages and combines with paper filter", () => {
  const rows = reviewRows(data);
  assert.deepEqual(
    filterRows(rows, { filter: "changes", paper: "b", search: "C PASSAGE" }, sources).map(
      (row) => row.key,
    ),
    ["b"],
  );
  assert.equal(
    filterRows(rows, { filter: "changes", paper: "a", search: "does not exist" }, sources).length,
    0,
  );
});

test("unchanged matches exclude singletons but allow changed parent scope", () => {
  const copy = structuredClone(data);
  copy.assignments.right = structuredClone(copy.assignments.left);
  copy.assignments.right.a.scope = ["new scope"];
  assert.deepEqual(
    filterRows(reviewRows(copy), { filter: "kept", paper: "", search: "" }, sources).map(
      (row) => row.key,
    ),
    ["a", "b"],
  );
});

test("same-paper co-members are preserved for display", () => {
  const copy = structuredClone(data);
  copy.sources.b.paper = "a";
  assert.deepEqual(reviewRows(copy)[0].oldPeers, ["b"]);
});

test("source content cannot become HTML", () => {
  assert.equal(
    escapeHtml("<img src=\"x\" onerror='bad'>&"),
    "&lt;img src=&quot;x&quot; onerror=&#39;bad&#39;&gt;&amp;",
  );
});

test("paragraph labels show the section and one-based paragraph number, not export titles", () => {
  assert.equal(
    sourceLabel(
      { paper: "a", id: "s1.p0002", section_id: "s1", title: "1" },
      { "a:s1": { title: "Methods" } },
    ),
    "Methods / paragraph 2",
  );
  assert.equal(sourceLabel({ paper: "a", id: "s1", title: "Methods" }, {}), "Methods");
});
