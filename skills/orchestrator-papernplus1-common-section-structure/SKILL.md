---
name: "orchestrator-papernplus1-common-section-structure"
description: "The papernplus1-family analog of \"orchestrator-common-section-structure-with-differences\". Given a two-paper \"section-pairings-with-paragraphs-and-questions\" file, the \"orchestrator-extract-sections-paragraphs-and-questions\" output for a third paper's PDF, and all three papers' literal PDF filenames, runs the full PDF-free three-paper comparison pipeline: \"papernplus1-both-directions-mapping-by-paragraphs-and-questions\" -> \"papernplus1-common-section-structure-by-paragraphs-questions\". Saves all five files (both directional passes plus combined, confirmed three-way structure, tagged leftover differences). No normalize step -- paperA/paperB/paperNplus1 are stable identity labels already. No PDF opened, no new matching logic of its own. Use to fold a third paper into an existing two-paper comparison end to end, or \"run the whole papernplus1 pipeline.\""
---

# PaperNplus1 Common Section Structure (Orchestrator)

## What this is (and isn't)

Thin orchestrator: runs two existing skills back to back — `papernplus1-both-directions-mapping-by-paragraphs-and-questions`, then `papernplus1-common-section-structure-by-paragraphs-questions` — so the user doesn't have to invoke both separately. It does no matching or confirming of its own, and it composes no question text itself; every actual rule (the exact-title-only exception, the type-narrow-question override, the splitting rule, the three-way join key, the direction-specific null checks, the alignable/non-alignable classification, the fresh-question-composition step) lives in the two sub-skills' own SKILL.md files. If any step's behavior seems to need a decision this orchestrator doesn't cover, consult that step's own skill rather than improvising here.

This is the papernplus1-family analog of `orchestrator-common-section-structure-with-differences`, but with one fewer stage: unlike the base two-paper pipeline, **no normalize step is needed here**. In the base pipeline, `paper1_*`/`paper2_*` field identity flips between the two directional passes, so `normalize-section-mapping-both-directions` has to fix that before comparison can run. Here, `paperA`/`paperB`/`paperNplus1` are stable identity labels in both directional passes already — `papernplus1-common-section-structure-by-paragraphs-questions` reads the raw both-directions combined file directly, no rename step first.

This pipeline does not build the two-paper pairing file itself — if that doesn't exist yet, run `section-pairings-with-paragraphs-and-questions` first (which itself needs `common-section-structure-by-paragraphs-and-questions`'s output, i.e. the base two-paper pipeline, run first). Nor does it extract anything from a PDF — if the third paper doesn't yet have a `sections-with-paragraphs-and-questions.json` file, run `orchestrator-extract-sections-paragraphs-and-questions` on that paper's PDF first, then come back here.

**Awareness note: this pipeline can't recover a role that was never split out upstream.** Step 1 (`papernplus1-both-directions-mapping-by-paragraphs-and-questions`, which runs `directional-section-mapping-paragraphs-and-questions-papernplus1` and `pairing-to-papernplus1-mapping-by-paragraphs-and-questions`) is where paragraph-level splitting happens — if paperNplus1 (or the existing pairing) folds a narrow role into a much broader section without its own heading, and that step fails to split it out, no later stage here can notice or fix it. See those two skills' "buried narrow role" guidance for the full explanation.

## Inputs

Two files:

1. `{paperA-name}-{paperB-name}-sections-with-paragraphs-and-questions.json` — the output of `section-pairings-with-paragraphs-and-questions`.
2. `{paperNplus1-name}-sections-with-paragraphs-and-questions.json` — the output of `orchestrator-extract-sections-paragraphs-and-questions` on the third paper's PDF.

`{paperA-name}`, `{paperB-name}`, `{paperNplus1-name}` must be the literal PDF filenames (minus `.pdf`) already used as prefixes on the input files — character-for-character, no reformatting, no lowercasing, no shortening, no paraphrasing from a section or publication title. If any isn't evident, ask before proceeding — don't guess.

No PDF is opened at any point in this pipeline — everything downstream of the two input JSON files works from JSON alone. Note both of these same two files are needed again directly in Step 2, not just Step 1 — keep them around.

## Workflow

### Step 1: Run the both-directions papernplus1 mapping

Follow `papernplus1-both-directions-mapping-by-paragraphs-and-questions`'s full workflow with the two input files and the three paper-name strings. This produces three files: the `papernplus1-onto-{paperA-name}-{paperB-name}` intermediate, the `{paperA-name}-{paperB-name}-onto-papernplus1` intermediate, and the combined file keyed `papernplus1-to-pairing`/`pairing-to-papernplus1`.

### Step 2: Split into confirmed three-way structure and leftovers

Follow `papernplus1-common-section-structure-by-paragraphs-questions`'s full workflow. It takes three inputs: Step 1's combined file (no normalize step in between — see "What this is and isn't" above), plus the same two files already used as this orchestrator's own Inputs (the pairing file and the paperNplus1 sections file) — that sub-skill needs those two directly to compose each confirmed match's question from real paragraph content, not just Step 1's output. This produces the confirmed `papernplus1-common-section-structure.json` (each entry carrying one freshly-composed question) and the tagged `papernplus1-leftover-section-differences.json`.

If you need either step's exact rules refreshed, consult that step's own SKILL.md directly rather than working from a vague memory of it — the three-way join key, the direction-specific null checks, the question-composition rules, and the deliberate schema relaxation (a confirmed match can have only one of paperA/paperB non-null) are easy to get subtly wrong from recall alone.

## Output

Five files total, saved in the same directory as the inputs unless the user specifies otherwise, all sharing the `{paperA-name}-{paperB-name}-{paperNplus1-name}` prefix:

| File | Produced by |
|---|---|
| `{paperNplus1-name}-onto-{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions.json` | Step 1 |
| `{paperA-name}-{paperB-name}-onto-{paperNplus1-name}-section-mapping-by-paragraphs-and-questions.json` | Step 1 |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-both-directions-section-mapping-by-paragraphs-and-questions.json` | Step 1 (combined) |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-papernplus1-common-section-structure.json` | Step 2 |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-papernplus1-leftover-section-differences.json` | Step 2 |

All five are kept — every intermediate is a legitimate input to some other skill in this family (e.g. the raw combined file from Step 1 is still what `papernplus1-common-section-structure-by-paragraphs-questions` expects if the user wants to re-run just that step), and discarding any of them defeats the "everything is ready for inspection or reuse" design this whole family follows.

Output schemas for each file are defined by their producing skill, not repeated here — see `papernplus1-both-directions-mapping-by-paragraphs-and-questions` and `papernplus1-common-section-structure-by-paragraphs-questions` for the strict schema of each.

Briefly tell the user the final counts — how many confirmed three-way matches, how many leftovers and of which `diff_type`/`direction` — and flag anything that stands out, same as each sub-skill would on its own.

## Common mistakes to avoid

- **Inserting a normalize step before Step 2 "to be safe," or looking for a papernplus1 analog of `normalize-section-mapping-both-directions`.** None exists and none is needed — `paperA`/`paperB`/`paperNplus1` never swap identity between the two directional passes here, unlike the base pipeline's `paper1`/`paper2`. Feed Step 1's combined file straight into Step 2.
- **Running Step 2 with only Step 1's combined file and forgetting to also pass along the pairing file and paperNplus1 sections file.** `papernplus1-common-section-structure-by-paragraphs-questions` needs all three now — the combined file alone doesn't carry paragraph text, so its question-composition step would have nothing real to read from.
- **Re-deriving either step's matching/join-key/classification/question-composition logic from memory instead of running that step's own workflow (and its bundled script, for Step 2's structural join).** The three-way join key and its direction-specific null checks are easy to get subtly wrong by hand — always run the actual sub-skill, don't approximate it.
- **Discarding intermediate files once the final common-structure/leftover-differences files exist.** All five files are required outputs — see "Output" above.
- **Guessing or reformatting `{paperA-name}`/`{paperB-name}`/`{paperNplus1-name}` instead of using the literal PDF filenames.** Same rule as every skill in this family — ask if any isn't evident.
- **Opening a PDF at any point in this pipeline.** Nothing here needs one; if a section is missing content, that's an upstream extraction gap to flag, not a reason to go find the source PDF.
- **Assuming a confirmed three-way match always has both `paperA_section_name` and `paperB_section_name` non-null.** Deliberately not guaranteed here (unlike the base pipeline) — a paperNplus1 section can legitimately, bidirectionally confirm against an `alignable-diff`/`non-alignable-diff` pairing. Don't "fix" this when reporting or post-processing results.
- **Also computing which leftover differences are more "important," or doing further comparison work beyond what Step 2 already produces.** This orchestrator's job ends at the five files above — anything past that is a separate downstream task, not part of this pipeline.
- **Running this pipeline before the two-paper pairing file exists, or before the third paper has been through `orchestrator-extract-sections-paragraphs-and-questions`.** Both are hard prerequisites — check for them first and run the earlier pipeline stage(s) if missing, rather than starting Step 1 on incomplete inputs.
- **Assuming a thin leftover file proves nothing was buried.** Step 1 is the only place paragraph-level splitting happens in this pipeline — see the "buried narrow role" awareness note above.


