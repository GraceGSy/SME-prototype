import { expect, test } from "@playwright/test";

test("groups, paper map, explorer, and tutorial work on canonical exports", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/single/public/");
  await expect(page.locator("#tutorialLoading")).toHaveText("Ready");
  await page.getByRole("button", { name: "Use Tool", exact: true }).click();
  await page.locator(".group-question").first().click();
  await page.getByRole("button", { name: "Expand all", exact: true }).first().click();
  await expect(page.locator(".section-text-full").first()).toBeVisible();
  await page.getByRole("button", { name: "Paper Map", exact: true }).click();
  await expect(page.locator(".paper-map-paragraph")).toHaveCount(3);
  await page.locator(".paper-map-shared-legend button").first().click();
  await page.getByLabel("Hide unselected", { exact: true }).check();
  await expect(page.locator(".paper-map-paragraph:visible")).toHaveCount(2);
  await page.getByRole("button", { name: "Clear selection" }).click();
  await expect(page.locator(".paper-map-paragraph:visible")).toHaveCount(3);
  await page.getByRole("button", { name: "Show singleton questions" }).click();
  await expect(page.locator(".paper-map-singleton-legend button")).toBeVisible();
  await page.screenshot({ path: "output/playwright/desktop-map.png" });
  await page.getByRole("button", { name: "Graphical Explorer", exact: true }).click();
  await expect(page.locator(".gx-node")).toHaveCount(1);
  await page.getByRole("button", { name: "Tutorial", exact: true }).click();
  for (let i = 0; i < 7; i++)
    await page.getByRole("button", { name: "Next Step", exact: true }).click();
  await page.getByRole("button", { name: "Finish", exact: true }).click();
  await expect(page.locator("#tutorialLayer")).toBeHidden();
  expect(errors).toEqual([]);
});

test("participant gate rejects lowercase instead of normalizing", async ({ page }) => {
  await page.goto("/study/public/");
  await page.getByLabel("Participant ID", { exact: true }).fill("sh001");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.locator("#participantGateError")).toContainText("exact");
  await page.getByLabel("Participant ID", { exact: true }).fill("SH001");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.locator("#tutorialLoading")).toHaveText("Ready");
});

test("malformed present replay is an error, not a hidden tab", async ({ page }) => {
  await page.route("**/graph-replay.json", (route) =>
    route.fulfill({ json: { schema_version: 999 } }),
  );
  await page.goto("/single/public/");
  await expect(page.getByRole("alert")).toContainText("Could not load viewer data");
});

test("mobile layout stays within the viewport while paper columns scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/single/public/");
  await expect(page.locator("#tutorialLoading")).toHaveText("Ready");
  await page.getByRole("button", { name: "Use Tool", exact: true }).click();
  await page.getByRole("button", { name: "Paper Map", exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "output/playwright/mobile-map.png" });
});
