import { expect, test, type Page } from "@playwright/test";
import type { Paper, Snapshot } from "../../pipeline/viewer/src/contracts";
import { patternFixture } from "./pattern-fixture";

async function openExplorer(page: Page) {
  await page.goto("/single/public/");
  await expect(page.locator("#tutorialLoading")).toHaveText("Ready");
  await page.getByRole("button", { name: "Use Tool", exact: true }).click();
  await page.getByRole("button", { name: "Graphical Explorer", exact: true }).click();
}

test("explorer unfolds sections at the top of the board and opens evidence without a sidebar", async ({
  page,
}) => {
  await openExplorer(page);
  await expect(page.getByRole("button", { name: "Graph Replay", exact: true })).toHaveCount(0);
  await expect(page.locator(".gx aside, .gx-heading")).toHaveCount(0);
  await expect(page.locator(".gx-node")).toHaveCount(1);
  await page.locator(".gx-node").press("Enter");
  await expect(page.locator(".gx-anchor")).toHaveCount(1);
  await expect(page.locator(".gx-node:not(.gx-anchor)")).toHaveCount(2);
  const center = await page.locator(".gx-anchor").boundingBox();
  const canvas = await page.locator(".gx-viewport > svg").boundingBox();
  expect(Math.abs(center!.x + center!.width / 2 - canvas!.x - canvas!.width / 2)).toBeLessThan(2);
  expect(Math.abs(center!.y - canvas!.y - 60)).toBeLessThan(2);
  await expect(page.locator(".gx-edge")).toHaveCount(1);
  await expect(page.locator(".gx-edge.visible")).toHaveCount(0);
  await expect(page.locator(".gx-node-meta").first()).toContainText("2/2 DOCUMENTS");
  await page.getByLabel("Show graph roles").selectOption("shared");
  await expect(page.locator(".gx-node:not(.gx-anchor):not(.dimmed)")).toHaveCount(1);
  await page.locator(".gx-node:not(.gx-anchor):not(.dimmed)").press("Enter");
  await expect(page.locator("foreignObject.gx-evidence")).toHaveCount(1);
  await expect(page.locator(".gx-source-text")).toHaveCount(2);
  await expect(page.locator(".gx-source-text").first()).toHaveText("Shared A");
  const before = await page.locator(".gx-viewport > svg > g").getAttribute("transform");
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  expect(await page.locator(".gx-viewport > svg > g").getAttribute("transform")).not.toBe(before);
  await page.getByRole("button", { name: "All sections", exact: true }).click();
  await expect(page.locator(".gx-node")).toHaveCount(1);
  await page.getByLabel("Find graph nodes").fill("no such role xyz");
  await expect(page.locator(".gx-status")).toHaveText("0 of 1 roles highlighted");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const firstBlock = await page.locator(".gx-node").first().boundingBox();
  const controls = await page.locator(".gx-zoom").boundingBox();
  expect(firstBlock!.y).toBeGreaterThan(controls!.y + controls!.height + 40);
});

test("parallel reading paths draw once and remain visible for either contributing paper", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route("**/data/dataset.json", async (route) => {
    const response = await route.fetch();
    const descriptor = await response.json();
    descriptor.paragraph_count = 4;
    await route.fulfill({ json: descriptor });
  });
  await page.route("**/data/paper_b.json", async (route) => {
    const response = await route.fetch();
    const paper: Paper = await response.json();
    paper.paragraphs.push({ ...paper.paragraphs[0], id: "pb2", ordinal: 2, text: "Unique B" });
    await route.fulfill({ json: paper });
  });
  await page.route("**/data/final_snapshot.json", async (route) => {
    const response = await route.fetch();
    const snapshot: Snapshot = await response.json();
    const group = snapshot.singletons.pop()!;
    group.members.push({ ...snapshot.groups[0].members[1], unit_id: "pb2", ordinal: 2 });
    snapshot.groups.push(group);
    await route.fulfill({ json: snapshot });
  });
  await openExplorer(page);
  await page.locator(".gx-node").press("Enter");
  await expect(page.locator(".gx-edge")).toHaveCount(1);
  await expect(page.locator(".gx-edge.shared")).toHaveAttribute(
    "data-papers",
    '["paper_a","paper_b"]',
  );
  for (const title of ["Paper A", "Paper B"]) {
    await page.getByRole("button", { name: title, exact: true }).click();
    await expect(page.locator(".gx-edge.visible")).toHaveCount(1);
  }
});

test("the board aligns options and reveals only the selected document's skip or return path", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const { papers, snapshot } = patternFixture({
    a: ["intro", "common", "end"],
    b: ["intro", "common", "end"],
    c: ["intro", "other", "end"],
    d: ["intro", "rare", "end"],
    skip: ["intro", "end"],
    reverse: ["end", "intro"],
  });
  const files: Record<string, unknown> = {
    "dataset.json": {
      schema_version: 1,
      mode: "final_snapshot",
      dataset_id: "patterns",
      label: "Pattern board",
      paper_count: papers.length,
      paragraph_count: 0,
      snapshot_file: "final_snapshot.json",
      stats: snapshot.stats,
    },
    "manifest.json": papers.map((paper) => ({
      paper_id: paper.paper_id,
      title: paper.title,
      file: `${paper.paper_id}.json`,
    })),
    "final_snapshot.json": snapshot,
    ...Object.fromEntries(papers.map((paper) => [`${paper.paper_id}.json`, paper])),
  };
  await page.route("**/data/*.json", (route) => {
    const file = new URL(route.request().url()).pathname.split("/").at(-1)!;
    return file in files ? route.fulfill({ json: files[file] }) : route.continue();
  });
  await openExplorer(page);
  await expect(page.locator(".gx-row")).toHaveCount(3);
  await expect(page.locator(".gx-node")).toHaveCount(5);
  await expect(page.locator(".gx-edge.visible")).toHaveCount(0);
  const common = page.locator('.gx-node[data-id="common"]');
  await expect(common).toHaveAttribute("data-row", "1");
  await expect(common.locator(".gx-node-meta")).toContainText("2/6 DOCUMENTS");
  const center = await page.locator('.gx-node[data-id="intro"]').boundingBox();
  const middle = await common.boundingBox();
  expect(Math.abs(center!.x - middle!.x)).toBeLessThan(1);
  for (const id of ["other", "rare"]) {
    const alternative = await page.locator(`.gx-node[data-id="${id}"]`).boundingBox();
    expect(Math.abs(alternative!.y - middle!.y)).toBeLessThan(1);
    expect(Math.abs(alternative!.x - middle!.x)).toBeGreaterThan(middle!.width);
  }
  await page.getByRole("button", { name: "skip", exact: true }).click();
  await expect(page.locator(".gx-edge.visible")).toHaveCount(1);
  await expect(page.locator(".gx-edge.visible.jump")).toHaveAttribute("data-skipped-rows", "1");
  await page.getByRole("button", { name: "reverse", exact: true }).click();
  await expect(page.locator(".gx-edge.visible")).toHaveCount(1);
  await expect(page.locator(".gx-edge.visible.order-exception")).toHaveAttribute(
    "data-source",
    "end",
  );
  await page.getByRole("button", { name: "All papers", exact: true }).click();
  await expect(page.locator(".gx-edge.visible")).toHaveCount(0);
  await expect(common.locator(".gx-node-meta")).toContainText("2/6 DOCUMENTS");
  const world = page.locator(".gx-viewport > svg > g");
  const before = await world.getAttribute("transform");
  const scale = (value: string) => /scale\(([^)]+)\)/.exec(value)![1];
  await page.locator(".gx-viewport > svg").hover();
  await page.mouse.wheel(0, 180);
  await expect.poll(() => world.getAttribute("transform")).not.toBe(before);
  expect(scale((await world.getAttribute("transform"))!)).toBe(scale(before!));
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -100);
  await page.keyboard.up("Control");
  await expect
    .poll(async () => scale((await world.getAttribute("transform"))!))
    .not.toBe(scale(before!));
});

test("leaving the explorer cancels an unfinished camera animation", async ({ page }) => {
  await openExplorer(page);
  await page.locator(".gx-node").press("Enter");
  await page.getByRole("button", { name: "Question Groups", exact: true }).click();
  await expect(page.locator(".group-card").first()).toBeVisible();
  // Wait beyond the camera duration to catch a stale callback replacing the view.
  await page.waitForTimeout(600);
  await expect(page.locator(".gx")).toHaveCount(0);
  await expect(page.locator(".group-card").first()).toBeVisible();
});
