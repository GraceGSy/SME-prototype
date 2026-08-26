---
name: "orchestrator-five-paper-common-section-structure-from-pdfs"
description: "Top-level orchestrator: given 5 paper PDFs in an explicit user-supplied order, runs the full pipeline from raw PDFs to the final 5-paper section-structure comparison -- extraction (x5), base 2-paper comparison, pairing merge, papernplus1 fold-in, pairing merge, papernplus2 fold-in, pairing merge, papernplus3 fold-in. Produces the final papernplus3-common-section-structure.json (confirmed matches) and papernplus3-leftover-section-differences.json (alignable/non-alignable diffs), plus every intermediate file. No matching logic of its own -- sequences 8 existing skills. Use for a full 5-paper section-structure comparison starting from scratch, \"compare these 5 papers,\" or \"run the whole 5-paper pipeline.\" Planned cap of the family (5 papers) -- for fewer papers use the shorter orchestrator for that count instead."
---

# Five-Paper Common Section Structure from PDFs (Orchestrator)

## What this is (and isn't)

This is the top-level orchestrator for the whole section-comparison family: given 5 raw paper PDFs, it runs every stage needed to go from nothing but PDFs to the final confirmed common structure and leftover differences across all 5 papers at once. It does no extraction, matching, splitting, or confirming of its own — every actual rule lives in the 8 existing skills it sequences (5 extraction runs plus 7 comparison/merge skills). If any stage's behavior seems to need a decision this orchestrator doesn't cover, consult that stage's own skill rather than improvising here.

**This is the "planned cap" of the bespoke-field-growth family — 5 papers, no more.** The chain ends at `orchestrator-papernplus3-common-section-structure` because that's the last generation of this family Elena planned to need (see that skill's own documentation for why a 6th paper isn't a simple extension of the same pattern). If a 6th paper is ever needed, this orchestrator is not the template to extend — the deferred generalized `sides`-array redesign should be revisited first.

**Paper order is explicit and matters.** The pipeline is inherently asymmetric: the first two papers become `paperA`/`paperB` (the base pairwise comparison), and papers 3, 4, 5 fold in one at a time afterward as `paperNplus1` → `paperNplus2` → `paperNplus3`. This orchestrator does not infer an order from the PDFs — the user must supply the 5 PDFs as an explicit ordered list. **If the user hasn't specified an order, ask before proceeding; don't guess or default to filename/alphabetical order.**

**For fewer than 5 papers, don't use this skill at all.** Use the orchestrator for the paper count actually needed instead:
- 2 papers → `orchestrator-common-section-structure-with-differences`
- 3 papers → `orchestrator-papernplus1-common-section-structure`
- 4 papers → `orchestrator-papernplus2-common-section-structure`

This skill exists specifically for the 5-paper case, chaining all of the above plus the final papernplus3 fold-in and the two pairing-merge steps in between that none of the shorter orchestrators cover on their own.

**Awareness note: this orchestrator can't recover a role that was never split out upstream.** The actual paragraph-level splitting happens inside the directional-mapping skills invoked deep within Stages 1, 3, 5, and 7 (`directional-section-mapping-by-paragraphs-and-questions` and the papernplus1/2/3 forward+reverse pairs). If a source paper folds a narrow role into a much broader section without its own heading, and one of those passes fails to split it out, nothing later in this whole pipeline — including this orchestrator's own final report — can notice or fix it. A thin or all-`non-alignable` final leftover file does not by itself prove the 5 papers have nothing else in common; see those skills' "buried narrow role" guidance (and the real mesotext.pdf example documented there) for the full explanation.

## Inputs

Five PDFs, in an explicit order given by the user: paper1, paper2, paper3, paper4, paper5. `{paper1-name}`...`{paper5-name}` are the literal PDF filenames (minus `.pdf`), used verbatim as prefixes throughout every stage — don't guess, reformat, or derive them from a title. If the order isn't already clear from how the user described the task, ask which PDF should be paper1 through paper5 before starting Stage 0.

## Workflow

### Stage 0: Extract all five papers

Run `orchestrator-extract-sections-paragraphs-and-questions` once per PDF — five independent runs, any order, in parallel if convenient. Each run follows that skill's own full workflow (`extract-top-level-section-names` → `extract-section-paragraphs` → `annotate-section-questions-given-paragraphs`) and produces 4 files per paper: `{paper}-sections.json`, `{paper}-sections-with-paragraph-content.json`, `{paper}-sections-with-paragraphs-and-questions.json`, `{paper}-sections-with-questions-only.json`. 20 files total after this stage.

### Stage 1: Base two-paper comparison (paper1 + paper2)

Run `orchestrator-common-section-structure-with-differences`'s full workflow with `fileA` = paper1's `sections-with-paragraphs-and-questions.json`, `fileB` = paper2's, `{paperA-name}` = `{paper1-name}`, `{paperB-name}` = `{paper2-name}`. Produces 6 files: the `p1-p2`/`p2-p1` intermediates, the combined file, the normalized file, `{paper1}-{paper2}-common-section-structure.json`, and `{paper1}-{paper2}-leftover-section-differences.json`.

### Stage 2: Build the 2-paper pairing file

Run `section-pairings-with-paragraphs-and-questions`'s full workflow using Stage 1's `common-section-structure.json` and `leftover-section-differences.json`, plus paper1's and paper2's own `sections-with-paragraphs-and-questions.json` files. Produces 1 file: `{paper1}-{paper2}-sections-with-paragraphs-and-questions.json` — the "pairing file" with real paragraph content reattached, required by Stage 3.

### Stage 3: Fold in paper3 (papernplus1)

Run `orchestrator-papernplus1-common-section-structure`'s full workflow using Stage 2's pairing file, paper3's `sections-with-paragraphs-and-questions.json`, and the three name strings (`{paperA-name}` = `{paper1-name}`, `{paperB-name}` = `{paper2-name}`, `{paperNplus1-name}` = `{paper3-name}`). Produces 5 files: the two directional intermediates, the combined file, `{paper1}-{paper2}-{paper3}-papernplus1-common-section-structure.json`, and `{paper1}-{paper2}-{paper3}-papernplus1-leftover-section-differences.json`.

### Stage 4: Build the 3-paper pairing file

Run `papernplus1-pairings-with-paragraphs-and-questions`'s full workflow using Stage 3's `papernplus1-common-section-structure.json` and `papernplus1-leftover-section-differences.json`, plus Stage 2's pairing file and paper3's own sections file. Produces 1 file: `{paper1}-{paper2}-{paper3}-sections-with-paragraphs-and-questions.json`, required by Stage 5.

### Stage 5: Fold in paper4 (papernplus2)

Run `orchestrator-papernplus2-common-section-structure`'s full workflow using Stage 4's pairing file, paper4's sections file, and the four name strings. Produces 5 files, ending in `{paper1}-{paper2}-{paper3}-{paper4}-papernplus2-common-section-structure.json` and `{paper1}-{paper2}-{paper3}-{paper4}-papernplus2-leftover-section-differences.json`.

### Stage 6: Build the 4-paper pairing file

Run `papernplus2-pairings-with-paragraphs-and-questions`'s full workflow using Stage 5's two output files, Stage 4's pairing file, and paper4's own sections file. Produces 1 file: `{paper1}-{paper2}-{paper3}-{paper4}-sections-with-paragraphs-and-questions.json`, required by Stage 7.

### Stage 7: Fold in paper5 (papernplus3) — final stage

Run `orchestrator-papernplus3-common-section-structure`'s full workflow using Stage 6's pairing file, paper5's sections file, and all five name strings. Produces 5 files — the last two are this whole orchestrator's deliverables:

- `{paper1}-{paper2}-{paper3}-{paper4}-{paper5}-papernplus3-common-section-structure.json`
- `{paper1}-{paper2}-{paper3}-{paper4}-{paper5}-papernplus3-leftover-section-differences.json`

If you need any individual stage's exact rules refreshed — a splitting rule, a null-check convention, the confirmed-vs-carried-forward question logic, the exact-title-only exception — consult that stage's own SKILL.md directly rather than working from a vague memory of it. Several of these rules were added after specific corrections and are easy to get subtly wrong from recall alone.

## Output

44 files total across Stages 0–7, saved in the same directory as the input PDFs unless the user specifies otherwise, all following the naming conventions each producing skill already documents. Every intermediate is kept, not just the final two — each is a legitimate input to some other skill in this family, or useful for inspecting where a given correspondence entered the structure.

The two deliverables, produced at the end of Stage 7:

| File | Contents |
|---|---|
| `{paper1}-{paper2}-{paper3}-{paper4}-{paper5}-papernplus3-common-section-structure.json` | Confirmed 5-way correspondences, each tagged `pairing_status`: `common-structure` (confirmed at every generation) or `alignable-diff` (confirmed now, but broken alignment somewhere in its ancestry) |
| `{paper1}-{paper2}-{paper3}-{paper4}-{paper5}-papernplus3-leftover-section-differences.json` | Every remaining entry, each tagged `diff_type`: `alignable` (some real correspondence exists but wasn't bidirectionally confirmed at this generation) or `non-alignable` (no counterpart found, and none in its ancestry either) |

Together these two files are the complete 5-paper structural comparison: common structure, alignable diffs, and non-alignable diffs, covering every section of every one of the 5 papers exactly once.

### Final report to the user

Don't just say "done" — state, at minimum: how many confirmed 5-way matches (broken down by `common-structure` vs `alignable-diff`), how many leftover entries (broken down by `alignable` vs `non-alignable`), and flag anything that stands out (an unusually high leftover rate, a `null` question from the empty-content fallback, a `question_the_sections_answer` that looks notably narrower than its `ancestor_questions`). This mirrors what `orchestrator-papernplus3-common-section-structure`'s own Step 4 already asks for — just don't stop there; also summarize the whole arc (how many papers' worth of structure got progressively folded in, and roughly how much survived to the end vs. peeled off as leftovers at each stage) if the user seems to want the fuller picture.

## Common mistakes to avoid

- **Guessing or inferring paper order instead of asking.** The base pairing (papers 1–2) and the fold-in order (3, 4, 5) are not interchangeable — a different order produces a structurally different (though not necessarily worse) intermediate history. Confirm the order explicitly before Stage 0.
- **Skipping a pairing-merge stage (2, 4, or 6) and feeding a fold-in stage's raw `common-section-structure.json`/`leftover-section-differences.json` pair directly into the next fold-in stage.** Every fold-in orchestrator (Stages 3, 5, 7) needs the *merged pairing file* — the one with real paragraphs reattached via `section-pairings-with-paragraphs-and-questions` / `papernplus1-pairings-with-paragraphs-and-questions` / `papernplus2-pairings-with-paragraphs-and-questions` — not the bare common-structure/leftover pair those merge skills consume as input.
- **Running Stage 0's five extractions into a shared directory with generic (non-prefixed) filenames.** `orchestrator-extract-sections-paragraphs-and-questions` already prefixes every output with `{paper-name}` by default specifically to prevent this — don't override that.
- **Re-deriving any stage's internal matching/splitting/classification logic from memory instead of running that stage's own skill (and its bundled script, where it has one).** This orchestrator has zero matching logic of its own; every rule that matters lives one level down.
- **Discarding intermediate files once the final two exist.** All 44 files are legitimate outputs — keep them, same convention as every orchestrator in this family.
- **Using this skill for fewer than 5 papers.** Use the shorter orchestrator for the actual paper count instead (see "What this is and isn't" above) — this wrapper's extra stages (the 4th and 5th fold-ins, the corresponding pairing merges) aren't optional shortcuts, they're structurally required for exactly 5 papers.
- **Treating a sparse final leftover file as proof the 5 papers genuinely share nothing else.** The buried-narrow-role risk lives entirely inside the directional-mapping skills several layers down — see the awareness note above.
- **Trying to extend this skill's pattern for a 6th paper.** This is the planned cap on bespoke-field growth for the whole family, not just this orchestrator.


