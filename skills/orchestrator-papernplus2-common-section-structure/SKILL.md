---
name: "orchestrator-papernplus2-common-section-structure"
description: "The papernplus2-family analog of \"orchestrator-papernplus1-common-section-structure\". Given a three-paper \"papernplus1-pairings-with-paragraphs-and-questions\" file, the \"orchestrator-extract-sections-paragraphs-and-questions\" output for a fourth paper's PDF, and all four papers' literal PDF filenames, runs the full PDF-free four-paper comparison pipeline: \"papernplus2-both-directions-mapping-by-paragraphs-and-questions\" -> \"papernplus2-common-section-structure-by-paragraphs-questions\". Saves all five files (both directional passes plus combined, confirmed four-way structure, tagged leftover differences). No normalize step -- paperA/paperB/paperNplus1/paperNplus2 are stable identity labels already. No PDF opened, no new matching logic of its own. Use to fold a fourth paper into an existing three-paper comparison end to end, or \"run the whole papernplus2 pipeline.\""
---

# PaperNplus2 Common Section Structure (Orchestrator)

## What this is (and isn't)

Thin orchestrator: runs two existing skills back to back — `papernplus2-both-directions-mapping-by-paragraphs-and-questions`, then `papernplus2-common-section-structure-by-paragraphs-questions` — so the user doesn't have to invoke both separately. It does no matching or confirming of its own, and it composes no question text itself; every actual rule (the exact-title-only exception, the type-narrow-question override, the splitting rule, the four-way join key, the direction-specific null checks, the alignable/non-alignable classification, and — most importantly for this generation — the confirmed-vs-carried-forward `ancestor_questions` logic) lives in the two sub-skills' own SKILL.md files. If any step's behavior seems to need a decision this orchestrator doesn't cover, consult that step's own skill rather than improvising here.

This is the papernplus2-family analog of `orchestrator-papernplus1-common-section-structure`, one generation further. **No normalize step is needed here**, same reason as its predecessor: `paperA`/`paperB`/`paperNplus1`/`paperNplus2` are stable identity labels in both directional passes already.

This pipeline does not build the three-paper pairing file itself — if `{paperA-name}-{paperB-name}-{paperNplus1-name}-sections-with-paragraphs-and-questions.json` doesn't exist yet, run `papernplus1-pairings-with-paragraphs-and-questions` first (which itself needs `papernplus1-common-section-structure-by-paragraphs-questions`'s output). Nor does it extract anything from a PDF — if the fourth paper doesn't yet have a `sections-with-paragraphs-and-questions.json` file, run `orchestrator-extract-sections-paragraphs-and-questions` on that paper's PDF first, then come back here.

**Awareness note: this pipeline can't recover a role that was never split out upstream.** Step 1 (`papernplus2-both-directions-mapping-by-paragraphs-and-questions`, which runs `directional-section-mapping-paragraphs-and-questions-papernplus2` and `pairing-to-papernplus2-mapping-by-paragraphs-and-questions`) is where paragraph-level splitting happens — if paperNplus2 (or the existing pairing) folds a narrow role into a much broader section without its own heading, and that step fails to split it out, no later stage here can notice or fix it. See those two skills' "buried narrow role" guidance for the full explanation.

## Inputs

Two files:

1. `{paperA-name}-{paperB-name}-{paperNplus1-name}-sections-with-paragraphs-and-questions.json` — the output of `papernplus1-pairings-with-paragraphs-and-questions`.
2. `{paperNplus2-name}-sections-with-paragraphs-and-questions.json` — the output of `orchestrator-extract-sections-paragraphs-and-questions` on the fourth paper's PDF.

`{paperA-name}`, `{paperB-name}`, `{paperNplus1-name}`, `{paperNplus2-name}` must be the literal PDF filenames (minus `.pdf`) already used as prefixes on the input files — character-for-character, no reformatting, no guessing. If any isn't evident, ask before proceeding.

No PDF is opened at any point in this pipeline. Note both files are needed again directly in Step 2, not just Step 1 — keep them around.

## Workflow

### Step 1: Run the both-directions papernplus2 mapping

Follow `papernplus2-both-directions-mapping-by-paragraphs-and-questions`'s full workflow with the two input files and the four paper-name strings. This produces three files: the `papernplus2-onto-{paperA-name}-{paperB-name}-{paperNplus1-name}` intermediate, the `{paperA-name}-{paperB-name}-{paperNplus1-name}-onto-papernplus2` intermediate, and the combined file keyed `papernplus2-to-pairing`/`pairing-to-papernplus2`.

### Step 2: Split into confirmed four-way structure and leftovers

Follow `papernplus2-common-section-structure-by-paragraphs-questions`'s full workflow. It takes three inputs: Step 1's combined file (no normalize step in between), plus the same two files already used as this orchestrator's own Inputs — that sub-skill needs those two directly, both for its mechanical `ancestor_questions` lookup/carry-forward and for composing fresh questions on confirmed and genuinely-new entries.

If you need either step's exact rules refreshed, consult that step's own SKILL.md directly — in particular, **Step 2's own Step 3 does NOT recompose every leftover entry** the way the papernplus1-family original does; only confirmed entries and leftover entries with no real pairing at all get a fresh question. Getting this backwards (recomposing everything, or nothing) is the most likely mistake at this stage — re-read that sub-skill's "What this is and isn't" section rather than assuming it mirrors its predecessor exactly.

## Output

Five files total, saved in the same directory as the inputs unless the user specifies otherwise, all sharing the `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}` prefix:

| File | Produced by |
|---|---|
| `{paperNplus2-name}-onto-{paperA-name}-{paperB-name}-{paperNplus1-name}-section-mapping-by-paragraphs-and-questions.json` | Step 1 |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-onto-{paperNplus2-name}-section-mapping-by-paragraphs-and-questions.json` | Step 1 |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-both-directions-section-mapping-by-paragraphs-and-questions.json` | Step 1 (combined) |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-papernplus2-common-section-structure.json` | Step 2 |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-papernplus2-leftover-section-differences.json` | Step 2 |

All five are kept — every intermediate is a legitimate input to some other skill in this family, and discarding any of them defeats the "everything is ready for inspection or reuse" design this whole family follows.

Output schemas for each file are defined by their producing skill, not repeated here.

Briefly tell the user the final counts — how many confirmed four-way matches, how many leftovers and of which `diff_type`/`direction`, and how many leftovers were genuinely new fourth-paper content (fresh question) vs. carried forward unchanged (no new information) — and flag anything that stands out, same as each sub-skill would on its own.

## Common mistakes to avoid

- **Inserting a normalize step before Step 2 "to be safe."** None exists and none is needed — `paperA`/`paperB`/`paperNplus1`/`paperNplus2` never swap identity between the two directional passes here.
- **Running Step 2 with only Step 1's combined file and forgetting to also pass along the three-paper pairing file and paperNplus2's own sections file.** `papernplus2-common-section-structure-by-paragraphs-questions` needs all three.
- **Assuming Step 2's own Step 3 recomposes every entry the way the papernplus1-family original does.** It deliberately does not — only confirmed entries and genuinely-new (no-real-pairing-at-all) leftover entries get a fresh question; everything else is carried forward unchanged. This is the single most important behavioral difference to get right at this generation.
- **Re-deriving either step's matching/join-key/classification/ancestor-questions logic from memory instead of running that step's own workflow (and its bundled script, for Step 2's structural join).** The four-way join key, its direction-specific null checks, and the confirmed-vs-carried-forward branch are easy to get subtly wrong by hand.
- **Discarding intermediate files once the final common-structure/leftover-differences files exist.** All five files are required outputs.
- **Guessing or reformatting any of the four paper-name strings instead of using the literal PDF filenames.**
- **Opening a PDF at any point in this pipeline.**
- **Assuming a confirmed four-way match always has all three of paperA/paperB/paperNplus1 non-null.** Deliberately not guaranteed — a paperNplus2 section can legitimately, bidirectionally confirm against a pairing that was already an `alignable-diff`/`non-alignable-diff` at the three-paper stage.
- **Running this pipeline before the three-paper pairing file exists, or before the fourth paper has been through `orchestrator-extract-sections-paragraphs-and-questions`.** Both are hard prerequisites.
- **Assuming a thin leftover file proves nothing was buried.** Step 1 is the only place paragraph-level splitting happens in this pipeline — see the "buried narrow role" awareness note above.


