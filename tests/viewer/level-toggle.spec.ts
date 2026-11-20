import { expect, test, type Page } from "@playwright/test";

// A full run: two papers, two section groups, and one paragraph group inside each.
const papers = ["alpha", "beta"].map((paper) => ({
  paper_id: paper,
  title: paper.toUpperCase(),
  sections: ["Intro", "Method"].map((title, i) => ({
    id: `s${i + 1}`,
    title,
    text: `${paper} ${title} text`,
    tag: title,
    unit_type: "section",
    parent_id: null,
    ordinal: i + 1,
  })),
  paragraphs: ["Intro", "Method"].map((title, i) => ({
    id: `p${i + 1}`,
    title: "",
    text: `${paper} ${title} paragraph`,
    tag: `${title} paragraph`,
    section_id: `s${i + 1}`,
    family_id: `p${i + 1}`,
    ordinal: i + 1,
  })),
}));
const group = (id: string, parent: string | null, unit: string, section: string, kind: string) => ({
  group_id: id,
  role_statement: `Role of ${id}.`,
  parent_group_id: parent,
  members: ["alpha", "beta"].map((paper) => ({
    paper,
    unit_id: unit,
    section_id: section,
    tag: id,
    unit_type: kind,
    ordinal: Number(section.slice(1)),
  })),
});
const snapshot = {
  schema_version: 2,
  mode: "final_snapshot",
  section_groups: [
    group("sg-intro", null, "s1", "s1", "section"),
    group("sg-method", null, "s2", "s2", "section"),
  ],
  groups: [
    group("pg-intro", "sg-intro", "p1", "s1", "paragraph"),
    group("pg-method", "sg-method", "p2", "s2", "paragraph"),
  ],
  singletons: [],
  stats: { section_nodes: 2, paragraph_nodes: 2 },
};
const files: Record<string, unknown> = {
  "dataset.json": {
    schema_version: 1,
    mode: "final_snapshot",
    dataset_id: "full",
    label: "Full run",
    paper_count: 2,
    paragraph_count: 4,
    snapshot_file: "final_snapshot.json",
    stats: snapshot.stats,
  },
  "manifest.json": papers.map((p) => ({
    paper_id: p.paper_id,
    title: p.title,
    file: `${p.paper_id}.json`,
  })),
  "alpha.json": papers[0],
  "beta.json": papers[1],
  "final_snapshot.json": snapshot,
};

async function openFullRun(page: Page, query = "") {
  await page.route("**/single/public/local.json", (route) =>
    route.fulfill({ json: [{ id: "full", label: "Full run", revisions: ["revision-0001"] }] }),
  );
  await page.route("**/runs/full/revision-0001/*", (route) =>
    route.fulfill({ json: files[new URL(route.request().url()).pathname.split("/").pop()!] }),
  );
  await page.goto("/single/public/?run=full" + query);
  await expect(page.locator("#tutorialLoading")).toHaveText("Ready");
  await page.getByRole("button", { name: "Use Tool", exact: true }).click();
}

const pressed = (page: Page, name: string) =>
  expect(page.getByRole("button", { name, exact: true })).toHaveAttribute("aria-pressed", "true");

test("a full run switches between section and paragraph matching", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await openFullRun(page);
  await pressed(page, "Paragraphs");
  await pressed(page, "Passage Groups");

  await page.getByRole("button", { name: "Sections", exact: true }).click();
  await pressed(page, "Graphical Explorer");
  await expect(page.getByRole("button", { name: "Passage Groups", exact: true })).toHaveCount(0);
  await expect(page.locator(".gx-node")).toHaveCount(2);
  await expect(page.locator("#legend")).toContainText("Section matching");
  expect(new URL(page.url()).searchParams.get("level")).toBe("sections");

  await page.getByRole("button", { name: "Paper Map", exact: true }).click();
  await expect(page.locator(".paper-map-section-head")).toHaveCount(4);

  // The level survives a reload, so a link can open on sections.
  await page.reload();
  await page.getByRole("button", { name: "Use Tool", exact: true }).click();
  await pressed(page, "Sections");

  await page.getByRole("button", { name: "Paragraphs", exact: true }).click();
  await pressed(page, "Passage Groups");
  await expect(page.locator(".group-card")).toHaveCount(2);
  expect(new URL(page.url()).searchParams.has("level")).toBe(false);
  expect(errors).toEqual([]);
});

test("a run with one section group has no level control", async ({ page }) => {
  await page.goto("/single/public/");
  await expect(page.locator("#tutorialLoading")).toHaveText("Ready");
  await expect(page.locator("#levelControl")).toBeHidden();
});
