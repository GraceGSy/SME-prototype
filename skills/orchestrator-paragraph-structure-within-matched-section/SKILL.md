---
name: "orchestrator-paragraph-structure-within-matched-section"
description: "Given a common-section-structure.json row (any generation) OR an \"alignable\" leftover-section-differences.json row (2+ non-null papers), a 0-based row index, a role-slug, and the literal paper names + each paper's own sections-with-paragraph-content(-no-appendices).json for every paper the row spans, runs extract-paragraphs-as-pseudo-sections once (which now abbreviates each paper's name for filenames only, keeping full names in the data) and then dispatches to whichever existing N-paper section-structure chain matches the paper count, unmodified. Use to drill from a completed section-level comparison into paragraph-level correspondence within one specific matched section, including a role only some of the papers share."
---

---
name: "orchestrator-paragraph-structure-within-matched-section"
description: "Given a common-section-structure.json row (any generation) OR an \"alignable\" leftover-section-differences.json row (2+ non-null papers), a 0-based row index, a role-slug, and the literal paper names + each paper's own sections-with-paragraph-content(-no-appendices).json for every paper the row spans, runs extract-paragraphs-as-pseudo-sections once (which now abbreviates each paper's name for filenames only, keeping full names in the data) and then dispatches to whichever existing N-paper section-structure chain matches the paper count, unmodified. Use to drill from a completed section-level comparison into paragraph-level correspondence within one specific matched section, including a role only some of the papers share."
---

# Paragraph Structure Within a Matched Section (Orchestrator)

## What this is (and isn't)

This is the paragraph-level sibling of `orchestrator-five-paper-common-section-structure-from-pdfs` and its shorter-N relatives — but instead of starting from raw PDFs and discovering section structure from scratch, it starts from a comparison that's *already done*: one row of an existing `common-section-structure.json` (or, as of the fix below, an *alignable* row of a `leftover-section-differences.json`), i.e. one section-role already established to correspond across a specific set of papers. It drills into that one role and finds which *paragraphs*, within that already-matched section in each paper, play the same narrower role as each other.

It has no matching logic of its own. Stage 0 is `extract-paragraphs-as-pseudo-sections`, which converts each paper's paragraphs (from the target section only) into pseudo-section files. Every stage after that is a literal, unmodified re-use of the existing section-level skills — `orchestrator-common-section-structure-with-differences`, `section-pairings-with-paragraphs-and-questions`, and the `orchestrator-papernplus1/2/3-common-section-structure` family — pointed at the pseudo-section files instead of real per-paper section files. Those skills can't tell the difference, by design; see `extract-paragraphs-as-pseudo-sections` for why.

**This is generic across paper count (2 to 5) and across which section-role.** The row you supply determines both: how many papers it spans (read off which `paperX_section_name` fields are non-null) decides which existing chain to dispatch to, and the row's content decides which section gets drilled into. Nothing about this skill is hardcoded to a specific role like "Introduction" — that's just whatever row the caller points it at.

**If the section-level comparison hasn't been run yet**, this skill is the wrong starting point — run `orchestrator-common-section-structure-with-differences` / `orchestrator-papernplus1/2/3-common-section-structure` / `orchestrator-five-paper-common-section-structure-from-pdfs` (or its no-appendices variant) first, then come back here with a row from its output.

## Leftover rows are now supported for alignable entries (fixed 2026-08-16)

This orchestrator used to blanket-forbid any row sourced from a `leftover-section-differences.json` file (see the old "Common mistakes" bullet this replaced). That was too broad. Stage 0's own gating is now precise: a row is usable if it has **2 or more non-null papers**, regardless of which file it came from.

- A `common-section-structure.json` row always qualifies (every paper in that generation is non-null by construction).
- An **`"alignable"`** `leftover-section-differences.json` row also qualifies — it means 2 or more (but not all) papers share this role, just not confirmed all the way up to the full paper count. Drilling into it is exactly as meaningful as drilling into a `common-section-structure.json` row that happens to span fewer than the full paper count (e.g. a 3-paper `papernplus1-common-section-structure.json` row) — N is just smaller.
- A **`"non-alignable"`** `leftover-section-differences.json` row does *not* qualify — only one paper has real content, so there's nothing to compare. Stage 0 rejects these explicitly with a clear error rather than silently doing something meaningless.

See `extract-paragraphs-as-pseudo-sections`'s own "Leftover rows are supported for alignable entries" section for the full reasoning and the exact mechanics (both file types use the same `paperA_section_name`/`paperB_section_name`/etc. field names, so the same non-null-count check works on either).

## Filenames use a short paper-name abbreviation, not the literal PDF name (fixed 2026-08-16)

At N=4 or 5 papers, concatenating every paper's full literal name plus a role-slug (once per stage, several stages deep) can exceed the operating system's ~255-character filename limit — this happened on a real run (a role-slug as short as `graphical-perception` on a 5-paper row produced an over-length filename that had to be rescued with an ad hoc, undocumented abbreviation invented on the spot, which is exactly the kind of inconsistency this fix removes).

Stage 0 (`extract-paragraphs-as-pseudo-sections`) now computes a short, deterministic, unique-within-this-row abbreviation for each paper (see that skill's "Why output filenames use a short paper-name abbreviation" section for the exact algorithm) and names its own output files `{paper-abbreviation}--{role-slug}-sections-with-paragraphs-and-questions.json` instead of `{full-paper-name}--{role-slug}-...`. **From here on, use exactly this abbreviated identifier — `{paper-abbreviation}--{role-slug}`, not the paper's full literal name — as that paper's `{paperX-name}` in every downstream skill call below.** This is what keeps every output collision-free *and* under the filename-length limit against the real section-level files already in the same directory. Never substitute the paper's real literal name in these downstream calls, and never invent your own abbreviation — always the one Stage 0's `unique_abbreviations()` algorithm actually produced (check Stage 0's printed report).

This is a filename-only change. Every paper's identity inside the JSON *content* itself (the compound `section_number` IDs Stage 0 produces, and any other data field) still uses the full literal name — only the filenames get shortened. If you ever need to explain a result back to a human, always cross-reference Stage 0's printed paper-name → abbreviation mapping so the shortened filenames stay traceable.

## Inputs

1. **A row from a `common-section-structure.json` file (any generation) or a `leftover-section-differences.json` file with `diff_type: "alignable"`** — either way, a section-role with 2 or more non-null papers.
2. **A 0-based row index** into it, selecting the target section-role. Ask if not supplied.
3. **A role-slug** — short, human-readable label for the role (e.g. `introduction`). Ask if not supplied. It no longer needs to be aggressively short by itself now that paper names are abbreviated at Stage 0 — but an unusually long slug (over ~25 characters) on a 4-5 paper row can still threaten the OS filename limit; keep it reasonably concise.
4. **The literal paper names and each paper's own `sections-with-paragraph-content(-no-appendices).json`**, for every paper the row spans (i.e. every non-null `paperX_section_name`), in `paperA`/`paperB`/`paperNplus1`/`paperNplus2`/`paperNplus3` order (only the slots the row actually has). Same literal-filename discipline as everywhere else in this family — Stage 0 handles abbreviating them for filenames; you always supply the real, full names here.

## Workflow

### Stage 0: Convert the target role's paragraphs into pseudo-sections

Run `extract-paragraphs-as-pseudo-sections`'s full workflow with the inputs above. This produces one `{paper-abbreviation}--{role-slug}-sections-with-paragraphs-and-questions.json` file per paper the row spans — call these the **pseudo-section files** for the rest of this workflow. If the row has fewer than 2 non-null papers, Stage 0 rejects it outright (see "Leftover rows are now supported for alignable entries" above) — pick a different row rather than working around the rejection.

Determine **N** — the number of papers the row spans (2 through 5) — from how many pseudo-section files Stage 0 produced. Everything downstream dispatches on N.

Read Stage 0's printed paper-name → abbreviation mapping and keep it on hand — every downstream filename uses the abbreviation, and a human reading the final output will need this mapping to know which paper is which.

From here on, use `{paper-abbreviation}--{role-slug}` (exactly the identifier Stage 0 used to name that paper's pseudo-section file — check its printed report, never re-derive it yourself) as that paper's `{paperX-name}` in every downstream skill call below.

### Stage 1+: Dispatch on N

**If N = 2** (row has only `paperA_section_name`/`paperB_section_name` populated): run `orchestrator-common-section-structure-with-differences`'s full workflow with `fileA`/`fileB` = the two pseudo-section files, `{paperA-name}` = `{paperA-abbreviation}--{role-slug}`, `{paperB-name}` = `{paperB-abbreviation}--{role-slug}`. Its own `{paperA-name}-{paperB-name}-common-section-structure.json` and `...-leftover-section-differences.json` outputs are this skill's final deliverables. **Stop here.**

**If N = 3, 4, or 5:** run the same Stage 1 as above for papers A and B, then continue:

- **Stage 2:** run `section-pairings-with-paragraphs-and-questions`'s full workflow on Stage 1's common-structure/leftover files plus the paperA/paperB pseudo-section files, producing the 2-paper pairing file.
- **Stage 3:** run `orchestrator-papernplus1-common-section-structure`'s full workflow using Stage 2's pairing file, the paperNplus1 pseudo-section file, and the three `{paper-abbreviation}--{role-slug}` name strings. If **N = 3**, its `papernplus1-common-section-structure.json`/`...-leftover-section-differences.json` are this skill's final deliverables — **stop here.**
- **Stage 4:** (N = 4 or 5) run `papernplus1-pairings-with-paragraphs-and-questions`'s full workflow using Stage 3's output plus Stage 2's pairing file and the paperNplus1 pseudo-section file, producing the 3-paper pairing file.
- **Stage 5:** (N = 4 or 5) run `orchestrator-papernplus2-common-section-structure`'s full workflow using Stage 4's pairing file, the paperNplus2 pseudo-section file, and the four name strings. If **N = 4**, its output files are the final deliverables — **stop here.**
- **Stage 6:** (N = 5) run `papernplus2-pairings-with-paragraphs-and-questions`'s full workflow, producing the 4-paper pairing file.
- **Stage 7:** (N = 5) run `orchestrator-papernplus3-common-section-structure`'s full workflow using Stage 6's pairing file, the paperNplus3 pseudo-section file, and all five name strings. Its output files are the final deliverables.

This mirrors `orchestrator-five-paper-common-section-structure-from-pdfs`'s Stages 1–7 exactly (or the corresponding prefix of them for smaller N), substituting only which files get passed in — every rule inside each stage (splitting, null-handling, the exact-title-only exception, ancestor-question carry-forward) is whatever that stage's own SKILL.md already documents. Consult that stage's own file if any rule needs refreshing rather than working from memory.

## Output

Depending on N, the same two-file deliverable pattern every skill in this family ends on — a confirmed common-structure file and a tagged leftover-differences file — except scoped to paragraphs of the one target role instead of a paper's whole top-level outline, and named using the `{paper-abbreviation}--{role-slug}` identifiers throughout (so, for N=5: `{paperA-abbrev}--{role-slug}-{paperB-abbrev}--{role-slug}-{paperNplus1-abbrev}--{role-slug}-{paperNplus2-abbrev}--{role-slug}-{paperNplus3-abbrev}--{role-slug}-papernplus3-common-section-structure.json`, and the matching leftover file — e.g. with this family's real corpus, `crow--introduction-illu--introduction-meas--introduction-seei--introduction-visu--introduction-papernplus3-common-section-structure.json`, comfortably under the OS filename limit even with a moderately long role-slug).

Plus every intermediate file each stage produces along the way (the pseudo-section files, both-directions passes, pairing files) — keep all of them, same convention as every orchestrator in this family.

### Final report to the user

State: N (how many papers this row spanned), the paper-name → abbreviation mapping (from Stage 0), how many paragraphs went into each paper's pseudo-section file, and — mirroring every other orchestrator in this family — how many confirmed paragraph-level matches (split `common-structure` vs `alignable-diff`) and how many leftover entries (split `alignable` vs `non-alignable`). If the source row came from a leftover-section-differences.json file rather than a common-section-structure.json file, say so explicitly, and note how many of the corpus's total papers this row spans (e.g. "this drills into a role shared by only 2 of the corpus's 5 papers"). Flag anything that stands out (a paper whose target section had far more/fewer paragraphs than the others, an unusually high leftover rate, any Stage 0 lookup warning).

## Common mistakes to avoid

- **Using each paper's real literal name instead of `{paper-abbreviation}--{role-slug}` in Stage 1 onward.** This is what prevents both filename collisions with the real section-level files in the same directory AND filename-length overruns at N=4/5 — never drop the abbreviation or the role-slug suffix partway through the chain.
- **Inventing your own abbreviation instead of using exactly what Stage 0's `unique_abbreviations()` algorithm printed.** A hand-picked shortening (even a sensible-looking one) breaks any other process trying to predict these filenames ahead of time (e.g. a batch dispatcher precomputing expected output paths for many rows). Always use Stage 0's own reported abbreviation, verbatim.
- **Skipping a pairing-merge stage** (2, 4, or 6) the same way the base 5-paper orchestrator warns against — every fold-in stage needs the *merged pairing file*, not the raw common-structure/leftover pair the merge step consumes.
- **Guessing N instead of reading it off which `paperX_section_name` fields are actually non-null in the target row.** A base 2-paper file, a papernplus1 file, and a papernplus2/3 file all look superficially similar; check the field names present, not just assume 5. This applies identically whether the row came from a common-structure file or an alignable leftover row.
- **Treating this skill as if it re-derives which sections correspond.** It doesn't — the section-level correspondence was already decided by whatever produced the input row (a `common-section-structure.json` entry, or a confirmed-alignable `leftover-section-differences.json` entry). This skill only asks a narrower question within one already-established row.
- **Skipping Stage 0** and trying to feed real per-paper `sections-with-paragraph-content.json` files directly into the section-level chain. Those aren't shaped like `sections-with-paragraphs-and-questions.json` (no `question_this_section_answers`, and they cover the whole paper, not just the target section) — Stage 0 is required, not a shortcut to skip when "the data's already there."
- **Re-deriving any downstream stage's internal rules from memory** instead of consulting that stage's own SKILL.md. This orchestrator has zero matching logic of its own, same as its section-level counterpart.
- **Blanket-refusing every row from a `leftover-section-differences.json` file.** This used to be this skill's own rule and was wrong. Only a row with fewer than 2 non-null papers (`diff_type: "non-alignable"`) is unusable — an `"alignable"` leftover row is a legitimate partial correspondence and Stage 0 now accepts it directly (see "Leftover rows are now supported for alignable entries" above). Don't reject a leftover row on sight; check its non-null paper count (or `diff_type`) instead.
- **Losing track of which abbreviation means which paper when reporting results.** Always carry forward Stage 0's printed paper-name → abbreviation mapping into your own final report — filenames alone are not self-explanatory once shortened.

