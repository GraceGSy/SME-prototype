import { expect, test } from "@playwright/test";

test("explorer supports drilldown, evidence comparison, filters and zoom", async ({ page }) => {
  await page.goto("/single/public/");
  await expect(page.locator("#tutorialLoading")).toHaveText("Ready");
  await page.getByRole("button", { name: "Use Tool", exact: true }).click();
  await page.getByRole("button", { name: "Graphical Explorer", exact: true }).click();
  await expect(page.getByRole("button", { name: "Graph Replay", exact: true })).toHaveCount(0);
  await expect(page.locator(".gx-node")).toHaveCount(1);
  await page.locator(".gx-node").press("Enter");
  await page.getByRole("button", { name: /Explore paragraphs/ }).click();
  await expect(page.locator(".gx-node")).toHaveCount(2);
  await page.getByLabel("Show graph roles").selectOption("shared");
  await expect(page.locator(".gx-node:not(.dimmed)")).toHaveCount(1);
  await page.locator(".gx-node:not(.dimmed)").click();
  await page.getByRole("button", { name: "Compare side by side" }).click();
  await expect(page.locator(".gx-body.comparing")).toBeVisible();
  await expect(page.locator(".gx-source-text")).toHaveCount(2);
  await page.getByRole("button", { name: "Return to graph" }).click();
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
