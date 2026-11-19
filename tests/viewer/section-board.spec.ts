import { expect, test, type Page } from "@playwright/test";

// A section checkpoint: Alpha reads Intro, Notes, Method; Beta reads Intro, Method,
// so Beta's path jumps over the row holding Alpha's unmatched Notes.
const section = (paper: string, n: number, title: string) => ({
  id: `s${n}`,
  title,
  text: `${paper} ${title} text`,
  tag: title,
  unit_type: "section",
  parent_id: null,
  ordinal: n,
});
const member = (paper: string, n: number, title: string) => ({
  paper,
  unit_id: `s${n}`,
  section_id: `s${n}`,
  tag: title,
  unit_type: "section",
  ordinal: n,
});
const sectionMap = {
  papers: [
    {
      paper_id: "alpha",
      title: "Alpha",
      sections: [
        section("Alpha", 1, "Intro"),
        section("Alpha", 2, "Notes"),
        section("Alpha", 3, "Method"),
      ],
      paragraphs: [],
    },
    {
      paper_id: "beta",
      title: "Beta",
      sections: [section("Beta", 1, "Intro"), section("Beta", 2, "Method")],
      paragraphs: [],
    },
  ],
  groups: [
    {
      group_id: "g-intro",
      role_statement: "Introduces the problem.",
      parent_group_id: null,
      members: [member("alpha", 1, "Intro"), member("beta", 1, "Intro")],
    },
    {
      group_id: "g-method",
      role_statement: "Describes the method.",
      parent_group_id: null,
      members: [member("alpha", 3, "Method"), member("beta", 2, "Method")],
    },
    {
      group_id: "g-notes",
      role_statement: "Adds side notes.",
      parent_group_id: null,
      members: [member("alpha", 2, "Notes")],
    },
  ],
};

async function openCheckpoint(page: Page) {
  await page.route("**/single/public/local.json", (route) =>
    route.fulfill({
      json: [
        {
          id: "checkpoint",
          label: "HCI | Section checkpoint",
          revisions: ["revision-0001"],
          sectionRevisions: ["revision-0001"],
          sourceTextRevisions: ["revision-0001"],
        },
      ],
    }),
  );
  await page.route("**/runs/checkpoint/revision-0001/section-map.json", (route) =>
    route.fulfill({ json: sectionMap }),
  );
  await page.goto("/single/public/?run=checkpoint&revision=latest");
}

test("a section checkpoint opens on the pattern board and shows section text", async ({ page }) => {
  await openCheckpoint(page);
  await expect(page.locator("#viewerTitle")).toHaveText("Section matches");
  await expect(
    page.getByRole("button", { name: "Graphical Explorer", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".gx-node")).toHaveCount(3);
  // Shared roles stay on the centerline; the one-paper role is off-center.
  await expect(page.locator('.gx-node[data-support="2"]')).toHaveCount(2);
  await expect(page.locator('.gx-node[data-id="g-notes"]')).toHaveClass(/unmatched/);
  // Beta goes straight from Intro to Method, skipping Alpha's Notes row.
  await expect(page.locator('.gx-edge.jump[data-source="g-intro"]')).toHaveCount(1);
  await page.locator('.gx-node[data-id="g-method"]').press("Enter");
  await expect(page.locator("foreignObject.gx-evidence")).toHaveCount(1);
  await expect(page.locator(".gx-anchor")).toHaveCount(0); // No drill-down without paragraphs.
  await expect(page.locator(".gx-source-text")).toHaveText([
    "Alpha Method text",
    "Beta Method text",
  ]);
  await page.getByRole("button", { name: "Paper Map", exact: true }).click();
  await expect(page.locator(".gx")).toHaveCount(0);
  await expect(page.locator(".paper-map-section-head").first()).toBeVisible();
  await page.getByRole("button", { name: "Graphical Explorer", exact: true }).click();
  await expect(page.locator(".gx-node")).toHaveCount(3);
});
