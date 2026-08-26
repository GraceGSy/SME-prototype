---
name: "orchestrator-five-paper-common-section-structure-no-appendices"
description: "Variant of \"orchestrator-five-paper-common-section-structure-from-pdfs\" that excludes appendices from every paper. Same 8-stage chain, but Stage 0 runs \"orchestrator-extract-sections-paragraphs-questions-no-appendices\" per PDF, which filters existing extraction via \"strip-appendices-from-extracted-sections\" when available, or extracts fresh otherwise. Stage 0's four files per paper now carry a -no-appendices suffix, distinct from a base run -- no collision there. Stages 1-7's own output filenames are still keyed only by literal paper-name strings, so they WILL collide with a base 5-paper run over the same 5 papers in the same directory -- this is a known, not-yet-solved gap; use a separate directory if both versions must coexist. Use for a full 5-paper comparison with appendices excluded. For appendices included, use \"orchestrator-five-paper-common-section-structure-from-pdfs\" instead."
---

# Five-Paper Common Section Structure Excluding Appendices (Orchestrator)

## What this is (and isn't)

This is a thin variant of `orchestrator-five-paper-common-section-structure-from-pdfs`: it runs the exact same 8-stage chain, except Stage 0 processes each of the 5 PDFs with `orchestrator-extract-sections-paragraphs-questions-no-appendices` instead of `orchestrator-extract-sections-paragraphs-and-questions`, so every downstream stage — and therefore the final 5-paper structure — is built entirely from non-appendix content. It does no extraction, matching, splitting, or confirming of its own; every actual rule lives in the 8 skills it sequences, unchanged from the base orchestrator except for that one Stage 0 swap. If any stage's behavior seems to need a decision this orchestrator doesn't cover, consult that stage's own skill rather than improvising here.

**Stages 1–7 are completely unmodified from the base orchestrator.** `orchestrator-common-section-structure-with-differences`, `section-pairings-with-paragraphs-and-questions`, `orchestrator-papernplus1-common-section-structure`, `papernplus1-pairings-with-paragraphs-and-questions`, `orchestrator-papernplus2-common-section-structure`, `papernplus2-pairings-with-paragraphs-and-questions`, and `orchestrator-papernplus3-common-section-structure` don't know or care whether appendices were excluded upstream — they only consume whatever `sections-with-paragraphs-and-questions` files Stage 0 handed them. Swapping Stage 0 is the *entire* difference between this orchestrator and the base one.

**Stage 0's own filenames carry a `-no-appendices` suffix** (`{paper}-sections-no-appendices.json`, etc.), because `orchestrator-extract-sections-paragraphs-questions-no-appendices` itself now uses that suffix — see that skill's own "What this is" section for why (it used to match the base orchestrator's filenames exactly for a drop-in swap, but that caused silent overwrites; it now either filters a paper's existing base-orchestrator output via `strip-appendices-from-extracted-sections`, or extracts fresh with the suffixed name, and never collides with a base extraction run either way).

**This does NOT mean the whole 44-file output of this orchestrator is collision-free relative to a base 5-paper run.** Stages 1 through 7 name their own output files using only the literal paper-name strings (`{paperA-name}-{paperB-name}-...`), with no marker at all for whether appendices were excluded — that naming scheme is inherited unchanged from the base orchestrator and doesn't currently distinguish an appendix-included comparison from an appendix-excluded one. **Running this orchestrator on the same 5 papers, in the same order, in the same directory, as a prior `orchestrator-five-paper-common-section-structure-from-pdfs` run will still overwrite Stages 1–7's files (24 of the 44), even though Stage 0's 20 files no longer collide.** This is a known, not-yet-solved gap in this variant, not an oversight to work around silently — if both an appendix-included and appendix-excluded 5-paper comparison need to coexist for the same paper set, run this orchestrator's entire pipeline in a separate directory rather than assuming Stage 0's fix protects the whole thing.

**Same planned cap as the base orchestrator — 5 papers, no more.** For fewer than 5 papers, use the appendix-excluding building blocks directly at the paper count you need (there is currently no dedicated no-appendices variant of the shorter orchestrators — build the equivalent by substituting `orchestrator-extract-sections-paragraphs-questions-no-appendices` for `orchestrator-extract-sections-paragraphs-and-questions` in whichever shorter orchestrator's own extraction stage, the same substitution this skill makes at Stage 0).

**Paper order is explicit and matters**, for the same reason as the base orchestrator: papers 1–2 become `paperA`/`paperB`, and papers 3, 4, 5 fold in afterward as `paperNplus1` → `paperNplus2` → `paperNplus3`. **If the user hasn't specified an order, ask before proceeding; don't guess or default to filename/alphabetical order.**

**Awareness note (inherited from the base orchestrator): this pipeline can't recover a role that was never split out upstream.** The paragraph-level splitting happens inside the directional-mapping skills invoked deep within Stages 1, 3, 5, and 7, exactly as in the base orchestrator — excluding appendices doesn't change this risk, it only changes which paragraphs are available to split in the first place (appendix content is gone entirely, by design). See those skills' "buried narrow role" guidance for the full explanation, and note that excluding appendices means any narrow role that *only* existed in an appendix (like the mesotext.pdf Appendix C example documented there) will not appear anywhere in this pipeline's output at all — that's expected, not a bug, given the point of this variant.

## Inputs

Same as the base orchestrator: five PDFs, in an explicit order given by the user (paper1 through paper5). `{paper1-name}`...`{paper5-name}` are the literal PDF filenames (minus `.pdf`), used verbatim as prefixes throughout every stage.

## Workflow

### Stage 0: Extract all five papers, excluding appendices

Run `orchestrator-extract-sections-paragraphs-questions-no-appendices` once per PDF — five independent runs, any order, in parallel if convenient. Each run follows that skill's own "Which path to use" logic (filter existing base-orchestrator output via `strip-appendices-from-extracted-sections` if it exists for that paper, otherwise extract fresh from the PDF) and produces 4 files per paper: `{paper}-sections-no-appendices.json`, `{paper}-sections-with-paragraph-content-no-appendices.json`, `{paper}-sections-with-paragraphs-and-questions-no-appendices.json`, `{paper}-sections-with-questions-only-no-appendices.json`. 20 files total after this stage.

### Stages 1–7: Unchanged from the base orchestrator

Run Stages 1 through 7 exactly as `orchestrator-five-paper-common-section-structure-from-pdfs` documents them — base two-paper comparison, pairing merge, papernplus1 fold-in, pairing merge, papernplus2 fold-in, pairing merge, papernplus3 fold-in — pointing each stage's inputs at Stage 0's `-no-appendices`-suffixed files instead of the base orchestrator's plain-named ones. Consult that skill's own SKILL.md for each stage's exact sub-skill and output files; nothing about how those stages work changes here, only which files feed into them. **Their own output filenames are unaffected by the suffix** — see "What this is" above for why this means Stages 1–7 aren't collision-free.

## Output

44 files total, following the same stage-by-stage breakdown as `orchestrator-five-paper-common-section-structure-from-pdfs`'s own "Output" section, except Stage 0's 20 files carry the `-no-appendices` suffix. The two final deliverables:

| File | Contents |
|---|---|
| `{paper1}-{paper2}-{paper3}-{paper4}-{paper5}-papernplus3-common-section-structure.json` | Confirmed 5-way correspondences among non-appendix content only |
| `{paper1}-{paper2}-{paper3}-{paper4}-{paper5}-papernplus3-leftover-section-differences.json` | Every remaining entry among non-appendix content only, tagged `alignable`/`non-alignable` |

Same final-report expectations as the base orchestrator: state confirmed-match and leftover counts, broken down by tag, and flag anything that stands out.

## Common mistakes to avoid

- **Using `orchestrator-extract-sections-paragraphs-and-questions` (appendices included) in Stage 0 instead of `orchestrator-extract-sections-paragraphs-questions-no-appendices`.** That single swap is this orchestrator's entire reason for existing.
- **Modifying Stages 1–7 in any way** beyond pointing their inputs at Stage 0's suffixed files. They are otherwise unchanged from the base orchestrator by design — don't add appendix-awareness logic to them, don't skip a pairing-merge stage, don't reorder anything relative to how the base orchestrator documents them.
- **Assuming the whole 44-file output is collision-safe relative to a base 5-paper run just because Stage 0 is.** It isn't — see "What this is" above. Stages 1–7 will still overwrite a prior base run's same-named files.
- **Guessing or inferring paper order instead of asking.** Same requirement as the base orchestrator.
- **Treating a leftover file that's thin or all-`non-alignable` as proof the 5 papers share nothing else**, without accounting for the fact that this variant has also removed every appendix from consideration entirely — a role that only existed in an appendix cannot appear here no matter how well the matching worked.
- **Discarding intermediate files once the final two exist.** All 44 files are legitimate outputs, same convention as the base orchestrator.
- **Using this skill for fewer than 5 papers, or trying to extend it for a 6th.** Same planned cap as the base orchestrator.
- **Re-deriving any stage's internal logic from memory instead of running that stage's own skill.** This orchestrator has zero matching logic of its own.


