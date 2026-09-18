import { expect, test } from "@playwright/test";
import type { Group, Paper, Snapshot } from "../../pipeline/viewer/src/contracts";

test("paragraph selection aligns first occurrences, disables sync, and reveals its question", async ({
  page,
}) => {
  // Different reading orders and repeated members expose proportional-scroll mistakes.
  const papers: Paper[] = ["alpha", "beta", "unmatched"].map((paper_id) => ({
    paper_id,
    title: paper_id,
    sections: [
      {
        id: "s",
        title: "Content",
        text: "Content",
        tag: "Role?",
        unit_type: "section",
        parent_id: null,
        ordinal: 1,
      },
    ],
    paragraphs: Array.from({ length: 48 }, (_, index) => ({
      id: `p${index}`,
      title: "",
      text: "Evidence for the paragraph role. ".repeat(8),
      tag: `Paragraph ${index}?`,
      section_id: "s",
      family_id: "s",
      ordinal: index + 1,
    })),
  }));
  const member = (paper: Paper, index: number) => ({
    paper: paper.paper_id,
    unit_id: `p${index}`,
    section_id: "s",
    tag: `Paragraph ${index}?`,
    unit_type: "paragraph" as const,
    ordinal: index + 1,
  });
  const groups: Group[] = Array.from({ length: 24 }, (_, index) => ({
    group_id: `role-${index}`,
    overarching_question: `What purpose does shared role ${index} serve?`,
    parent_group_id: null,
    members: [
      member(papers[0], index * 2),
      member(papers[0], index * 2 + 1),
      member(papers[1], (23 - index) * 2),
      member(papers[1], (23 - index) * 2 + 1),
    ],
  }));
  const snapshot: Snapshot = {
    schema_version: 1,
    mode: "final_snapshot",
    groups,
    section_groups: [],
    singletons: papers[2].paragraphs.map((p, i) => ({
      group_id: `unique-${i}`,
      overarching_question: p.tag,
      parent_group_id: null,
      members: [member(papers[2], i)],
    })),
    stats: { section_nodes: 0, paragraph_nodes: 72 },
  };
  const files: Record<string, unknown> = {
    "dataset.json": {
      schema_version: 1,
      mode: "final_snapshot",
      dataset_id: "navigation",
      label: "Navigation",
      paper_count: 3,
      paragraph_count: 144,
      snapshot_file: "final_snapshot.json",
      stats: snapshot.stats,
    },
    "manifest.json": papers.map((p) => ({
      paper_id: p.paper_id,
      title: p.title,
      file: `${p.paper_id}.json`,
    })),
    "final_snapshot.json": snapshot,
    ...Object.fromEntries(papers.map((p) => [`${p.paper_id}.json`, p])),
  };
  await page.route("**/data/*.json", (route) => {
    const data = files[new URL(route.request().url()).pathname.split("/").pop()!];
    return data ? route.fulfill({ json: data }) : route.fulfill({ status: 404 });
  });
  await page.goto("/single/public/");
  await expect(page.locator("#tutorialLoading")).toHaveText("Ready");
  await page.getByRole("button", { name: "Use Tool", exact: true }).click();
  await page.getByRole("button", { name: "Paper Map", exact: true }).click();
  const sync = page.getByLabel("Sync paper scrolling", { exact: true });
  const matches = page.locator('.paper-map-paragraph[data-group="role-20"]');
  const question = page.locator('.paper-map-legend-item[data-group="role-20"]');
  await sync.check();
  await matches.nth(1).click();
  await expect(sync).not.toBeChecked();
  await expect(question).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".paper-map-column.has-selection")).toHaveCount(2);
  await expect(page.locator('[data-paper="unmatched"]')).not.toHaveClass(/has-selection/);
  for (const paper of ["alpha", "beta"]) {
    const column = page.locator(`.paper-map-column[data-paper="${paper}"]`);
    await expect
      .poll(() =>
        column.evaluate((el) => {
          const target = el.querySelector<HTMLElement>('[data-group="role-20"]')!;
          const top = target.getBoundingClientRect().top - el.getBoundingClientRect().top;
          return top >= 30 && top < 100;
        }),
      )
      .toBe(true);
    expect(await column.evaluate((el) => getComputedStyle(el).outlineColor)).toBe(
      await matches.first().evaluate((el) => getComputedStyle(el).borderLeftColor),
    );
  }
  expect(
    await question.evaluate((el) => {
      const bounds = el.getBoundingClientRect();
      const container = el.parentElement!.getBoundingClientRect();
      return bounds.top >= container.top && bounds.bottom <= container.bottom;
    }),
  ).toBe(true);
  // Selecting the same paragraph again navigates; clearing is an explicit action.
  await matches.first().press("Enter");
  await expect(question).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Question Groups", exact: true }).click();
  await page.getByRole("button", { name: "Paper Map", exact: true }).click();
  await expect(sync).not.toBeChecked();
  await expect(page.locator(".paper-map-column.has-selection")).toHaveCount(2);
  await page.getByRole("button", { name: "Clear selection", exact: true }).click();
  await expect(page.locator(".paper-map-column.has-selection")).toHaveCount(0);
});
