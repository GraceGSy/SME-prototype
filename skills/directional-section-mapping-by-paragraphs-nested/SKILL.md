---
name: "directional-section-mapping-by-paragraphs-nested"
description: "Given two sections-with-subsections-and-paragraph-content(-no-appendices).json files that ALREADY have question_this_text_answers added per entry, maps paper1's sections/subsections onto their closest counterpart in paper2 using paragraph text AND each candidate's own question together as joint evidence -- same discipline as \"directional-section-mapping-by-paragraphs-and-questions\" -- but never composes a new question for the output. Refuses to run (Step 0 precondition check) if either file's questions don't appear to have been added yet. A \"whole section\" candidate = lead-in + all subsections' paragraphs combined, using the top-level entry's own question; each subsection is ALSO offered independently with its own question. Matches can be section-to-section, subsection-to-section, section-to-subsection, or subsection-to-subsection. Outputs p1-p2-section-mapping-by-paragraphs-nested.json, no question field in output."
---

# Directional Section Mapping (By Paragraphs, Nested / Cross-Level)

## What this is (and isn't)

This is the nested-schema sibling of `directional-section-mapping-by-paragraphs-and-questions`, built for input files that have a `subsections` array per top-level entry (from `extract-section-and-subsection-paragraphs`) rather than the flat, top-level-only schema that skill expects. It uses the **same joint-evidence discipline** as that skill — paragraphs and a per-candidate question read together, question weighed as reliable primary evidence, paragraphs overriding only on a genuine conflict, watch for a type-narrow question — extended across two deliberate departures, both explicit design decisions:

1. **It reads an existing question field per candidate, but never writes a new one.** If a candidate (a whole section or a subsection) carries its own `question_this_text_answers`, use it jointly with the paragraphs exactly as `directional-section-mapping-by-paragraphs-and-questions` does. But this skill's output never composes a fresh shared question for a match, and never pulls one forward for a no-match entry either — there is no question-shaped field in the output at all (see Output schema below). New questions for this corpus are being computed by a separate process (decided 2026-08-27); this skill's only job is to use that question signal at match time, not to produce more of it.
2. **The question field is a required precondition, not optional — this skill will not run without it.** Unlike the "leave it graceful" idea floated earlier in this skill's design (rejected 2026-08-27), a missing question is not something to quietly route around by falling back to paragraphs alone. **Step 0 below is a hard precondition check: if either input file's entries don't appear to have `question_this_text_answers` added yet, stop before building any candidates or doing any matching, and tell the user which file(s) need question-annotation first.** This mirrors the base skill's own hard precondition (guaranteed by `annotate-section-questions-given-paragraphs`'s completeness gate) — the nested schema doesn't yet have an equivalent gating skill, so this skill enforces the same requirement itself, up front, rather than silently proceeding on incomplete evidence.
3. **A matching "candidate" is not the same thing as a JSON entry.** Every top-level section contributes potentially *multiple* independent candidates: itself as a **whole section** (its own lead-in paragraphs plus every one of its subsections' paragraphs, combined — using the *top-level entry's own* `question_this_text_answers`, which represents the section's overall role, not a synthesis of its subsections' questions), *and* each of its subsections individually, on its own (using *that subsection's own* question field). Both kinds of candidate are real, valid, and simultaneously offered — a section's whole-unit view being matched does not remove its own subsections from separately being offered as candidates too. This overlap is intentional (decided 2026-08-27): it's what makes a section-to-section match, a subsection-to-section match, a section-to-subsection match, and a subsection-to-subsection match all findable in the same pass, and it means the output can legitimately contain what look like "nested" or overlapping correspondences at different granularities for the same underlying content — that's expected, not a bug.

Like every skill in the `directional-section-mapping` family, this is a **single-direction** pass: it finds, for every paper1 candidate, its closest paper2 candidate — it does not check the reverse direction and does not do bidirectional confirmation. Run it twice (swapping which paper is `paper1`) if both directions are wanted.

## Inputs

Two files, each the output of `extract-section-and-subsection-paragraphs` (or `orchestrator-extract-sections-subsecs-paragraphs-no-appendices`, or its as-yet-unbuilt appendices-included orchestrator) — e.g. `examplore_chi18-sections-with-subsections-and-paragraph-content-no-appendices.json` and `corpusstudio-sections-with-subsections-and-paragraph-content-no-appendices.json` — **with `question_this_text_answers` already added to their entries by a separate process.** `extract-section-and-subsection-paragraphs` does not itself produce this field, so it will not be present on a freshly-extracted file — see Step 0 for the check this skill performs before doing anything else.

Each file is a JSON array where every top-level entry has `section_name`, `section_number`, `paragraphs` (its own lead-in array, `[]` if none or if the section has no subsections and this is its whole content), `subsections` (an array of `{section_name, section_number, paragraphs}` objects, `[]` if none), and — once the separate question-adding process has run — `question_this_text_answers` on the top-level entry itself and on each of its subsection objects. Note the field name: `question_this_text_answers`, not `question_this_section_answers` (the name used by the flat-schema skills in this family, e.g. `annotate-section-questions-given-paragraphs`) — the nested-schema corpus this skill was built against uses the `_text_` naming, confirmed present on both top-level entries and subsection entries alike (2026-08-28).

The order the user gives the two files matters: the first is `paper1`, and the correspondence is found *from* paper1's candidates *to* paper2's candidates. If it's ambiguous which should anchor the mapping, ask.

No PDF is needed or should be opened for this skill. If a section or subsection is missing its `paragraphs` field entirely, that's an upstream extraction gap to flag, not a reason to go find the PDF.

**A known caveat inherited from the input's own extraction process:** `extract-section-and-subsection-paragraphs`'s own Step 5 (order-integrity check) can, in rare cases, leave a section flagged rather than silently placing trailing post-subsection content anywhere. If either input file has such an unresolved flag for a section you're about to build a "whole section" candidate from, that candidate's combined paragraphs may not represent the section's full or correctly-ordered content — note this explicitly in your summary rather than treating the combined text as complete.

## Workflow

### Step 0: Precondition check — do not proceed without questions

Before building any candidate or doing any matching, check both input files for `question_this_text_answers`: sample across top-level entries and subsection entries in both files (not just the first entry — a file could have it on some entries and not others). If either file shows no sign of having been through question-annotation — the field is absent everywhere, or `null` everywhere, on entries that have real paragraph content — **stop here.** Do not build candidates, do not attempt paragraph-only matching as a fallback, and do not produce any output file. Tell the user plainly which file(s) appear to be missing questions and that they need to be added first before this skill can run.

If both files show the field present (even if a handful of individual entries are still missing it — see Step 2 for how to handle an isolated gap once the file has clearly been through annotation), proceed to Step 1.

### Step 1: Build each paper's full candidate list

For each of the two input files, build a flat list of candidates. For every top-level entry:

- Add **one "whole section" candidate**: `section_name`/`section_number` from the entry itself, `subsection_name`/`subsection_number` both `null`, `paragraphs` = that entry's own `paragraphs` array followed by every one of its `subsections[].paragraphs` arrays concatenated in order (lead-in first, then each subsection in the order it appears), and `question` = that top-level entry's own `question_this_text_answers`. If the entry has `subsections: []`, this candidate's `paragraphs` is just its own array — identical in effect to how the flat, non-nested skill would have treated it.
- **If `subsections` is non-empty, also add one candidate per subsection**: `section_name`/`section_number` from the *parent* top-level entry (for context — this is not itself a candidate identifier, see Step 3), `subsection_name`/`subsection_number` from the subsection itself, `paragraphs` = that subsection's own `paragraphs` array only (not combined with anything else), and `question` = that subsection's own `question_this_text_answers`.

A top-level entry with N subsections therefore contributes N+1 total candidates to the list: one whole-section candidate and N individual-subsection candidates. This is deliberate, not a bug — see "What this is" above. **Don't try to synthesize a whole-section candidate's question by combining its subsections' questions** — use the top-level entry's own field.

### Step 2: Read every candidate's full evidence — paragraphs and question together

For every candidate in both lists, read every paragraph in its `paragraphs` array in full — not just the first one or two — and read its `question`. Treat both as one joint body of evidence about the candidate's role, exactly as `directional-section-mapping-by-paragraphs-and-questions` does: don't let the question pre-filter which candidates get their paragraphs read, and don't skim the paragraphs while treating the question as a mere afterthought.

For narrative documents, inherit that skill's narrative-role rule: compare what each section or scene does in the progression of its story, not whether the events, characters, setting, or crime vocabulary are similar. Whole divisions and scenes remain independent candidates, and cross-level matches are valid.

**A candidate with real paragraph content but a missing/null question, in a file that otherwise passed Step 0's check, is an input-integrity gap on that one entry — flag it explicitly rather than silently treating it as normal.** This is different from Step 0's file-wide check: Step 0 asks "has this file been through question-annotation at all," this asks "did annotation miss one specific entry." Judge that specific candidate on its paragraphs alone if you must, but say so plainly in `basis` and in your summary to the user — don't let it pass as an unremarkable, expected state.

**If a candidate's `paragraphs` array is empty AND it has no question**, there's no content to reason with. In this specific case only, fall back to matching by name: does the candidate's own identifying name (its `subsection_name` if it's a subsection candidate, otherwise its `section_name`) **exactly** match another equally-empty candidate's own identifying name on the other side? An exact match on an otherwise content-less candidate (e.g. two "References" whole-section candidates, both with no real body prose and no question) is a reasonable enough signal when there's nothing else to go on. If the names are close but not identical, or if there's no exact match, output `null` for that candidate rather than guessing.

This exact-name exception applies only when a candidate has neither paragraphs nor a question. The moment a candidate has real paragraph content or a real question, match by role (Step 3), regardless of what its name happens to share or not share with any candidate on the other side.

### Step 3: Map each paper1 candidate to its closest paper2 candidate

For every paper1 candidate, compare it against **every** paper2 candidate — whole-section and subsection candidates alike, with no level-based pre-filtering. A paper1 whole-section candidate should be compared just as readily against a paper2 subsection candidate as against a paper2 whole-section candidate, and vice versa for a paper1 subsection candidate. The level a match happens to land at is an output, not an input constraint.

- **Judge role correspondence from the paragraphs and the question together** — the same role-based test used throughout this family: are these two candidates doing the same job in their paper's arc (problem → contribution → evidence → reflection), not do they share topic or vocabulary. Weigh the question as reliable, primary evidence of role — not a hint the paragraphs merely confirm — and let the paragraphs override it only on a genuine conflict (the type-narrow-question pitfall is the usual cause: a question that names every sub-topic can still lock onto one connecting verb-frame that leaves out a different kind of content actually present in the paragraphs).
- **A whole-section candidate matching well against a paper2 subsection is a completely normal, expected outcome** — it means paper1 covers, as an undivided block, something paper2 chose to break out as just one part of a larger section. Don't discount this pairing or feel obligated to also find a matching whole-section-to-whole-section pairing for the same content.
- **If a paper1 candidate legitimately corresponds to more than one paper2 candidate**, create a **separate entry for each** correspondence — same splitting rule as every sibling skill in this family. Use the actual paragraph text and question to verify the split entries collectively still cover the full scope of the paper1 candidate's own paragraphs — don't let a sub-role quietly fall out of the split.
  - **A role doesn't need its own subsection to be worth splitting out.** If a paper1 whole-section candidate's paragraphs cover two or more distinct jobs that paper2 happens to keep apart (in separate subsections, or even separate top-level sections), find and split each correspondence at the paragraph level, exactly as if paper1 had also broken it into its own subsection.
- **Many candidates — especially individual subsection candidates — will have no match at all. This is common and expected, not a sign something went wrong.** A narrow subsection (e.g. one describing a specific pilot study detail) may have no counterpart anywhere in the other paper, at any level. Output `null` rather than forcing the least-bad pick.
- **Use `null` only after having actually read the candidate paragraphs and question on both sides for every real candidate pair.** Don't skip a paper2 candidate just because its section-level name — or its question, if narrowly worded — looks unrelated to paper1's; the correspondence can live at a different level, under a differently-named container, or be broader than a type-narrow question suggests.

Each entry needs these fields:

| Field | Description |
|---|---|
| `paper1_section_name` | The paper1 candidate's containing top-level section name (always present) |
| `paper1_section_number` | The paper1 candidate's containing top-level section number, or `null` |
| `paper1_subsection_name` | The paper1 candidate's own subsection name, or `null` if this candidate is a whole-section candidate |
| `paper1_subsection_number` | The paper1 candidate's own subsection number, or `null` if this candidate is a whole-section candidate |
| `paper2_section_name` | The matched paper2 candidate's containing top-level section name, or `null` if no match |
| `paper2_section_number` | The matched paper2 candidate's containing top-level section number, or `null` |
| `paper2_subsection_name` | The matched paper2 candidate's own subsection name, or `null` if the match is a whole-section candidate or there's no match |
| `paper2_subsection_number` | The matched paper2 candidate's own subsection number, or `null` |
| `basis` | Why these two candidates correspond, grounded in what their paragraphs and question actually say — or why nothing corresponds. Note any isolated missing-question gap here too (see Step 2). Never empty. |

Null-consistency: `paper2_section_name`/`paper2_section_number` are both non-null together, or both `null` together (no match). `paper2_subsection_name`/`paper2_subsection_number` are both non-null together, or both `null` together (a whole-section match, or no match at all). The same rule applies to the paper1 side, which is always fully populated (paper1 candidates are never null — every candidate in Step 1's list gets its own output entry).

### Output

Save as a JSON array of these objects. Default filename: `p1-p2-section-mapping-by-paragraphs-nested.json`. If running this a second time in the reverse direction, use a distinct name like `p2-p1-section-mapping-by-paragraphs-nested.json` — ask if unclear which pass this is.

Briefly tell the user: total candidates built for each paper (whole-section + subsection counts, separately), any isolated missing-question gaps found in Step 2, how many got a confirmed match vs. `null`, how many matches crossed levels (section-to-subsection or subsection-to-section) vs. stayed same-level, and flag anything that stands out — including any order-integrity caveat inherited from the input files (see Inputs above).

### Output schema (strict)

ALWAYS use this exact shape for every entry — exactly these nine keys, no additions, no renaming, no reordering, **and no question-shaped field of any kind**:

```json
{
  "paper1_section_name": "string",
  "paper1_section_number": "string or null",
  "paper1_subsection_name": "string or null",
  "paper1_subsection_number": "string or null",
  "paper2_section_name": "string, or null if no match",
  "paper2_section_number": "string or null",
  "paper2_subsection_name": "string or null",
  "paper2_subsection_number": "string or null",
  "basis": "string, explains the match or why it's null -- never null or empty itself"
}
```

The file itself is a JSON array of these objects, e.g.:

```json
[
  {
    "paper1_section_name": "Related Work",
    "paper1_section_number": "2",
    "paper1_subsection_name": null,
    "paper1_subsection_number": null,
    "paper2_section_name": "Background and Related Work",
    "paper2_section_number": "2",
    "paper2_subsection_name": null,
    "paper2_subsection_number": null,
    "basis": "Both whole sections' questions and paragraphs describe surveying prior systems to situate the paper's contribution -- section-to-section, both undivided."
  },
  {
    "paper1_section_name": "General Methods",
    "paper1_section_number": "4",
    "paper1_subsection_name": "Stimuli",
    "paper1_subsection_number": null,
    "paper2_section_name": "User Study",
    "paper2_section_number": "5",
    "paper2_subsection_name": null,
    "paper2_subsection_number": null,
    "basis": "Paper1's Stimuli subsection describes the materials used in the study; paper2 folds the same materials description into its single undivided User Study section -- subsection-to-section."
  },
  {
    "paper1_section_name": "Ablation Study",
    "paper1_section_number": "5",
    "paper1_subsection_name": "Feature Removal Results",
    "paper1_subsection_number": "5.2",
    "paper2_section_name": null,
    "paper2_section_number": null,
    "paper2_subsection_name": null,
    "paper2_subsection_number": null,
    "basis": "No candidate at any level in paper2 reports an ablation isolating individual feature contributions -- paper2 has no comparable study design."
  }
]
```

Note the first example: the same paper1 top-level section could *also* separately appear via one of its own subsection candidates elsewhere in the output, with its own independent match (or `null`) — that's the expected overlap described in "What this is" above, not a contradiction.

Don't add extra fields — no `confidence`, no `paragraphs`, and critically **no `question_the_sections_answer` or any question-shaped output field**, even though questions are read as input evidence (see "What this is," points 1–2).

## Common mistakes to avoid

- **Looking for `question_this_section_answers` instead of `question_this_text_answers`.** This skill's input schema uses the `_text_` naming, confirmed on both top-level entries and subsections (2026-08-28) — don't assume it matches the flat-schema skills' field name.
- **Running this skill at all when Step 0's precondition check fails.** If either file doesn't appear to have been through question-annotation, stop and tell the user — do not fall back to paragraph-only matching as a workaround. This is a hard precondition, not a nice-to-have.
- **Composing, synthesizing, or pulling forward any new question text into the output.** Reading `question_this_text_answers` as matching *evidence* is expected and correct; writing any question-shaped field into the output is not — this is the one thing this skill exists to NOT do, unlike its flat sibling.
- **Treating an isolated missing question on one entry (in an otherwise-annotated file) as unremarkable and not flagging it.** Say so explicitly in `basis` and in the summary — it's a real gap even though it doesn't block the whole run the way Step 0's file-wide check does.
- **Synthesizing a whole-section candidate's question from its subsections' questions.** Use only the top-level entry's own `question_this_text_answers` for the whole-section candidate.
- **Only building whole-section candidates, or only building subsection candidates, instead of both for every section that has subsections.** Both must be built — that's what makes cross-level matching possible.
- **Treating a section's whole-unit match and its own subsections' independent matches as needing to agree, or discarding one because it seems "redundant" with the other.** They're deliberately independent, overlapping views.
- **Restricting a paper1 candidate's comparison pool to same-level paper2 candidates only** (whole-section vs. whole-section, subsection vs. subsection). Compare every paper1 candidate against every paper2 candidate, regardless of level.
- **Concatenating a whole-section candidate's paragraphs in the wrong order**, or forgetting to include the top-level entry's own lead-in paragraphs before its subsections' paragraphs.
- **Silently trusting a whole-section candidate's combined paragraphs to be complete and correctly ordered without checking for an inherited order-integrity flag from the input file's own extraction.** See "A known caveat" in Inputs above.
- **Matching on shared vocabulary/topic instead of shared role**, or **trusting a section/subsection's own name as evidence of correspondence once real content exists.**
- **Trusting a type-narrow question at face value.** A question that names every sub-topic can still exclude a different kind of content living in the same paragraphs — check the paragraphs for what they actually report.
- **Combining multiple correspondences into one entry instead of splitting**, or **letting a sub-role fall out of scope when splitting.**
- **Forcing a match onto the least-bad candidate when nothing actually plays the same role**, especially for narrow subsection candidates, where `null` is common and expected.
- **Leaving `paper1_subsection_name`/`paper1_subsection_number` or `paper2_subsection_name`/`paper2_subsection_number` inconsistent** (one null, the other not) — both members of each pair must be null together or non-null together. Same for the `paper2_section_name`/`paper2_section_number` pair.
- **Writing an empty `basis`**, including for a `null`-match entry or an exact-name-fallback entry.
- **Treating this skill as doing bidirectional confirmation.** It's single-direction, same as every sibling in this family.
- **Opening a PDF, or asking for one.** Everything needed is in the two input JSON files.
