import { expect, test, type Page } from "@playwright/test";
import type { Paper, Snapshot } from "../../pipeline/viewer/src/contracts";

async function openExplorer(page: Page) {
  await page.goto("/single/public/");
  await expect(page.locator("#tutorialLoading")).toHaveText("Ready");
  await page.getByRole("button", { name: "Use Tool", exact: true }).click();
  await page.getByRole("button", { name: "Graphical Explorer", exact: true }).click();
}

test("explorer centers and unfolds nodes on the canvas without a sidebar", async ({ page }) => {
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
  expect(Math.abs(center!.y + center!.height / 2 - canvas!.y - canvas!.height / 2)).toBeLessThan(2);
  await expect(page.locator(".gx-edge.unmatched")).toHaveCount(1);
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
    await expect(page.locator(".gx-edge:not(.dimmed)")).toHaveCount(1);
  }
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
