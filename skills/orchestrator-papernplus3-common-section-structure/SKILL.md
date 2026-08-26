---
name: "orchestrator-papernplus3-common-section-structure"
description: "The papernplus3-family analog of \"orchestrator-papernplus2-common-section-structure\" -- the planned cap of the bespoke-field-growth plan (5 papers total). Given a four-paper \"papernplus2-pairings-with-paragraphs-and-questions\" file, the \"orchestrator-extract-sections-paragraphs-and-questions\" output for a fifth paper's PDF, and all five papers' literal PDF filenames, runs the full PDF-free five-paper comparison pipeline: \"papernplus3-both-directions-mapping-by-paragraphs-and-questions\" -> \"papernplus3-common-section-structure-by-paragraphs-questions\". Saves all five files (both directional passes plus combined, confirmed five-way structure, tagged leftover differences). No normalize step -- paperA/paperB/paperNplus1/paperNplus2/paperNplus3 are stable identity labels already. No PDF opened, no new matching logic of its own. Use to fold a fifth paper into an existing four-paper comparison end to end, or \"run the whole papernplus3 pipeline.\""
---

# PaperNplus3 Common Section Structure (Orchestrator)

## What this is (and isn't)

Thin orchestrator: runs two existing skills back to back — `papernplus3-both-directions-mapping-by-paragraphs-and-questions`, then `papernplus3-common-section-structure-by-paragraphs-questions` — so the user doesn't have to invoke both separately. It does no matching or confirming of its own, and it composes no question text itself; every actual rule (the exact-title-only exception, the type-narrow-question override, the splitting rule, the five-way join key, the direction-specific null checks, the alignable/non-alignable classification, and the confirmed-vs-carried-forward `ancestor_questions` logic) lives in the two sub-skills' own SKILL.md files. If any step's behavior seems to need a decision this orchestrator doesn't cover, consult that step's own skill rather than improvising here.

This is the papernplus3-family analog of `orchestrator-papernplus2-common-section-structure`, one generation further — and, per Elena's original staged plan (bespoke-field growth capped at 5 papers total), this is the last generation of this family expected to be needed. If a sixth paper is ever required, don't extend this orchestrator's pattern with a sixth bespoke paper slot; the generalized `sides`-array redesign that was considered and deferred should be revisited instead.

**No normalize step is needed here**, same reason as every earlier generation: `paperA`/`paperB`/`paperNplus1`/`paperNplus2`/`paperNplus3` are stable identity labels in both directional passes already.

This pipeline does not build the four-paper pairing file itself — if `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-sections-with-paragraphs-and-questions.json` doesn't exist yet, run `papernplus2-pairings-with-paragraphs-and-questions` first (which itself needs `papernplus2-common-section-structure-by-paragraphs-questions`'s output). Nor does it extract anything from a PDF — if the fifth paper doesn't yet have a `sections-with-paragraphs-and-questions.json` file, run `orchestrator-extract-sections-paragraphs-and-questions` on that paper's PDF first, then come back here.

**Awareness note: this pipeline can't recover a role that was never split out upstream.** Step 1 (`papernplus3-both-directions-mapping-by-paragraphs-and-questions`, which runs `directional-section-mapping-paragraphs-and-questions-papernplus3` and `pairing-to-papernplus3-mapping-by-paragraphs-and-questions`) is where paragraph-level splitting happens — if paperNplus3 (or the existing pairing) folds a narrow role into a much broader section without its own heading, and that step fails to split it out, no later stage here can notice or fix it. This is not hypothetical: the real end-to-end test that first exercised this generation folded mesotext.pdf in as paper 5, and mesotext's own single "User Study" section only ended up correctly represented as six separate output entries (including three narrow roles sourced from its own Appendix C — a qualitative-coding methodology, verbatim task prompts, and verbatim survey questions) because Step 1's directional-mapping passes read every paragraph range and split accordingly. See those two skills' "buried narrow role" guidance for the full explanation.

## Inputs

Two files:

1. `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-sections-with-paragraphs-and-questions.json` — the output of `papernplus2-pairings-with-paragraphs-and-questions`.
2. `{paperNplus3-name}-sections-with-paragraphs-and-questions.json` — the output of `orchestrator-extract-sections-paragraphs-and-questions` on the fifth paper's PDF.

`{paperA-name}`, `{paperB-name}`, `{paperNplus1-name}`, `{paperNplus2-name}`, `{paperNplus3-name}` must be the literal PDF filenames (minus `.pdf`) already used as prefixes on the input files — character-for-character, no reformatting, no guessing. If any isn't evident, ask before proceeding.

No PDF is opened at any point in this pipeline. Note both files are needed again directly in Step 2, not just Step 1 — keep them around.

## Workflow

### Step 1: Run the both-directions papernplus3 mapping

Follow `papernplus3-both-directions-mapping-by-paragraphs-and-questions`'s full workflow with the two input files and the five paper-name strings. This produces three files: the `papernplus3-onto-{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}` intermediate, the `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-onto-papernplus3` intermediate, and the combined file keyed `papernplus3-to-pairing`/`pairing-to-papernplus3`.

### Step 2: Split into confirmed five-way structure and leftovers

Follow `papernplus3-common-section-structure-by-paragraphs-questions`'s full workflow. It takes three inputs: Step 1's combined file (no normalize step in between), plus the same two files already used as this orchestrator's own Inputs — that sub-skill needs those two directly, both for its mechanical `ancestor_questions` lookup/carry-forward and for composing fresh questions on confirmed and genuinely-new entries.

If you need either step's exact rules refreshed, consult that step's own SKILL.md directly — in particular, **Step 2's own Step 3 does NOT recompose every leftover entry**; only confirmed entries and leftover entries with no real pairing at all get a fresh question. Getting this backwards (recomposing everything, or nothing) is the most likely mistake at this stage — re-read that sub-skill's "What this is and isn't" section rather than assuming it mirrors its predecessor exactly.

## Output

Five files total, saved in the same directory as the inputs unless the user specifies otherwise, all sharing the `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-{paperNplus3-name}` prefix:

| File | Produced by |
|---|---|
| `{paperNplus3-name}-onto-{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-section-mapping-by-paragraphs-and-questions.json` | Step 1 |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-onto-{paperNplus3-name}-section-mapping-by-paragraphs-and-questions.json` | Step 1 |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-{paperNplus3-name}-both-directions-section-mapping-by-paragraphs-and-questions.json` | Step 1 (combined) |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-{paperNplus3-name}-papernplus3-common-section-structure.json` | Step 2 |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-{paperNplus3-name}-papernplus3-leftover-section-differences.json` | Step 2 |

All five are kept — every intermediate is a legitimate input to some other skill in this family, and discarding any of them defeats the "everything is ready for inspection or reuse" design this whole family follows.

Output schemas for each file are defined by their producing skill, not repeated here.

Briefly tell the user the final counts — how many confirmed five-way matches, how many leftovers and of which `diff_type`/`direction`, and how many leftovers were genuinely new fifth-paper content (fresh question) vs. carried forward unchanged (no new information) — and flag anything that stands out, same as each sub-skill would on its own.

## Common mistakes to avoid

- **Inserting a normalize step before Step 2 "to be safe."** None exists and none is needed — `paperA`/`paperB`/`paperNplus1`/`paperNplus2`/`paperNplus3` never swap identity between the two directional passes here.
- **Running Step 2 with only Step 1's combined file and forgetting to also pass along the four-paper pairing file and paperNplus3's own sections file.** `papernplus3-common-section-structure-by-paragraphs-questions` needs all three.
- **Assuming Step 2's own Step 3 recomposes every entry.** It deliberately does not — only confirmed entries and genuinely-new (no-real-pairing-at-all) leftover entries get a fresh question; everything else is carried forward unchanged.
- **Re-deriving either step's matching/join-key/classification/ancestor-questions logic from memory instead of running that step's own workflow (and its bundled script, for Step 2's structural join).** The five-way join key, its direction-specific null checks, and the confirmed-vs-carried-forward branch are easy to get subtly wrong by hand.
- **Discarding intermediate files once the final common-structure/leftover-differences files exist.** All five files are required outputs.
- **Guessing or reformatting any of the five paper-name strings instead of using the literal PDF filenames.**
- **Opening a PDF at any point in this pipeline.**
- **Assuming a confirmed five-way match always has all four of paperA/paperB/paperNplus1/paperNplus2 non-null.** Deliberately not guaranteed — a paperNplus3 section can legitimately, bidirectionally confirm against a pairing that was already an `alignable-diff`/`non-alignable-diff` at the four-paper stage.
- **Running this pipeline before the four-paper pairing file exists, or before the fifth paper has been through `orchestrator-extract-sections-paragraphs-and-questions`.** Both are hard prerequisites.
- **Treating this generation as a template to blindly extend for a sixth paper.** This is the planned cap on bespoke-field growth — revisit the deferred generalized-schema design instead of adding a sixth hardcoded field set.
- **Assuming a thin leftover file proves nothing was buried.** Step 1 is the only place paragraph-level splitting happens in this pipeline — see the mesotext example in the "buried narrow role" awareness note above.


