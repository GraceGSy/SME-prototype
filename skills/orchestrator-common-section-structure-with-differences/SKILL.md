---
name: "orchestrator-common-section-structure-with-differences"
description: "Given two sections-with-paragraphs-and-questions.json files (from \"orchestrator-extract-sections-paragraphs-and-questions\" or \"annotate-section-questions-given-paragraphs\") plus each papers PDF filename, runs the full PDF-free bidirectional comparison pipeline: \"section-mapping-by-paragraphs-and-questions-both-directions\" -> \"normalize-section-mapping-both-directions\" -> \"common-section-structure-by-paragraphs-and-questions\". Saves all six intermediate/final files across the three stages (both directional passes plus combined, the normalized combined file, the confirmed common structure, and the tagged leftover differences). No PDF opened at any point, no new matching or normalization logic of its own -- purely sequences the three sub-skills. Use whenever the user wants to compare two papers sections end to end from their paragraphs-and-questions files without invoking each stage separately, or says run the whole comparison pipeline, map normalize and find the common structure, or similar."
---

# Common Section Structure with Differences (Orchestrator)

## What this is (and isn't)

Thin orchestrator: runs three existing skills back to back on two papers' already-extracted section data -- `section-mapping-by-paragraphs-and-questions-both-directions`, then `normalize-section-mapping-both-directions`, then `common-section-structure-by-paragraphs-and-questions` -- so the user doesn't have to invoke all three separately. It does no matching, normalizing, or confirming of its own; every actual rule (splitting, the exact-title-only exception, the type-narrow-question override, the paperA/paperB identity-swap fix, the bidirectional matching logic, the alignable/non-alignable classification) lives in the three sub-skills' own SKILL.md files. If any step's behavior seems to need a decision this orchestrator doesn't cover, consult that step's own skill rather than improvising here.

This is the two-paper comparison pipeline -- it does not extract anything from a PDF itself. If either paper doesn't yet have a `sections-with-paragraphs-and-questions.json` file, run `orchestrator-extract-sections-paragraphs-and-questions` on that paper's PDF first (once per paper), then come back here.

**Awareness note: this pipeline can't recover a role that was never split out upstream.** Step 1 (`section-mapping-by-paragraphs-and-questions-both-directions`, which in turn runs `directional-section-mapping-by-paragraphs-and-questions` twice) is where paragraph-level splitting happens — if a source paper folds a narrow role into a much broader, denser section without giving it its own heading, and that step fails to split it out, nothing later in this pipeline (normalizing, confirming, classifying) can notice or fix it. See `directional-section-mapping-by-paragraphs-and-questions`'s "A role doesn't need its own container to be worth splitting out" guidance for the full explanation.

## Inputs

Two files, each a `sections-with-paragraphs-and-questions.json` (from `orchestrator-extract-sections-paragraphs-and-questions` or `annotate-section-questions-given-paragraphs`). Call them `fileA` and `fileB` in the order the user gives them.

Each paper's source PDF filename, with `.pdf` removed -- required, used verbatim (no reformatting) as `{paperA-name}`/`{paperB-name}` throughout. If not evident, ask before proceeding; don't guess or derive it from a section/publication title. This is the same requirement `section-mapping-by-paragraphs-and-questions-both-directions` has on its own -- see that skill's Inputs section for the full literal-string rule if it needs restating.

No PDF is opened at any point in this pipeline -- everything downstream of the two input JSON files works from JSON alone.

## Workflow

### Step 1: Run the both-directions mapping

Follow `section-mapping-by-paragraphs-and-questions-both-directions`'s full workflow with `fileA`, `fileB`, `{paperA-name}`, `{paperB-name}`. This produces three files: the `p1-p2` intermediate, the `p2-p1` intermediate, and the combined file keyed `p1-p2`/`p2-p1`.

### Step 2: Normalize the combined output

Follow `normalize-section-mapping-both-directions`'s full workflow, using Step 1's combined file (`{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions.json`) as input. This produces the `-normalized.json` file where every entry in both arrays uses consistent `paperA_*`/`paperB_*` fields.

### Step 3: Split into confirmed structure and leftovers

Follow `common-section-structure-by-paragraphs-and-questions`'s full workflow, using Step 2's normalized file as input. This produces the confirmed `common-section-structure.json` and the tagged `leftover-section-differences.json`.

If you need any step's exact rules refreshed, consult that step's own SKILL.md directly rather than working from a vague memory of it -- several of these rules (the identity-swap fix, the exact-title-only exception, the `diff_type`/`reason` distinction) were added after specific corrections and are easy to get subtly wrong from recall alone.

## Output

Six files total, saved in the same directory as the inputs unless the user specifies otherwise, all sharing the `{paperA-name}-{paperB-name}` prefix:

| File | Produced by |
|---|---|
| `{paperA-name}-{paperB-name}-p1-p2-section-mapping-by-paragraphs-and-questions.json` | Step 1 |
| `{paperA-name}-{paperB-name}-p2-p1-section-mapping-by-paragraphs-and-questions.json` | Step 1 |
| `{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions.json` | Step 1 (combined) |
| `{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions-normalized.json` | Step 2 |
| `{paperA-name}-{paperB-name}-common-section-structure.json` | Step 3 |
| `{paperA-name}-{paperB-name}-leftover-section-differences.json` | Step 3 |

All six are kept -- every intermediate is a legitimate input to some other skill in this family (e.g. the raw combined file from Step 1 is still what `normalize-section-mapping-both-directions` expects if the user wants to re-run just that step), and discarding any of them defeats the "everything is ready for inspection or reuse" design this whole family follows.

Output schemas for each file are defined by their producing skill, not repeated here -- see `section-mapping-by-paragraphs-and-questions-both-directions`, `normalize-section-mapping-both-directions`, and `common-section-structure-by-paragraphs-and-questions` for the strict schema of each.

## Common mistakes to avoid

- **Skipping Step 2 and feeding Step 1's raw combined file straight to Step 3.** `common-section-structure-by-paragraphs-and-questions` requires the normalized file specifically and will fail loudly (not silently) if given the raw one -- but don't rely on that check as the plan; always run Step 2.
- **Re-deriving any step's matching/normalization/classification logic from memory instead of running that step's own workflow (and its bundled script, where it has one).** Steps 2 and 3 each have a bundled script specifically because their logic is easy to get subtly wrong by hand (the paperA/paperB identity swap, the null-vs-unconfirmed distinction) -- always run the actual sub-skill, don't approximate it.
- **Discarding intermediate files once the final `common-section-structure.json`/`leftover-section-differences.json` exist.** All six files are required outputs -- see "Output" above.
- **Guessing or reformatting `{paperA-name}`/`{paperB-name}` instead of using the literal PDF filename.** Same rule as `section-mapping-by-paragraphs-and-questions-both-directions` -- ask if it isn't evident.
- **Opening a PDF at any point in this pipeline.** Nothing here needs one; if a section is missing content, that's an upstream extraction gap to flag, not a reason to go find the source PDF.
- **Also computing which of the leftover differences are more "important" or doing further comparison work beyond what Step 3 already produces.** This orchestrator's job ends at the six files above -- anything past that (e.g. summarizing which structural differences matter most) is a separate downstream task, not part of this pipeline.
- **Assuming a thin leftover file proves nothing was buried.** Step 1's directional-mapping pass is the only place paragraph-level splitting happens in this whole pipeline -- see the "buried narrow role" awareness note above.


