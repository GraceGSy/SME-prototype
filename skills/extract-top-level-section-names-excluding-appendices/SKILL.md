---
name: "extract-top-level-section-names-excluding-appendices"
description: "Variant of \"extract-top-level-section-names\" that excludes appendix sections from the output. Runs that skill's full extraction, then removes any section that functions as an appendix (literally titled Appendix/Appendices/Supplementary Material, or a lettered/separately-numbered back-matter chapter after References/Acknowledgments) -- judged by role and position, never by label shape alone, so a Roman-numeral main section labeled \"I\" or \"V\" is never mistaken for a lettered appendix. Keeps Abstract/Preface/Acknowledgments/References and all main sections. Use when the user wants a paper's outline without its appendices, e.g. before a structural comparison focused on the main argument. Outputs sections-excluding-appendices.json with the same two-field schema. For the full outline including appendices, use \"extract-top-level-section-names\" instead."
---

# Extract Top-Level Section Names (Excluding Appendices)

## What this is (and isn't)

This is a thin variant of `extract-top-level-section-names`: it produces the exact same names-only extraction, then removes any top-level section that functions as an appendix before saving. It does not duplicate the underlying PDF-text-extraction or header-identification technique — that's `extract-top-level-section-names`'s own job; consult that skill's SKILL.md directly for the `pdftotext` fallback rules, the numbering-convention checklist, and the cross-check-against-page-count discipline. This skill adds exactly one new piece of logic on top: identifying and filtering out appendix sections.

Use this when the user explicitly wants a paper's outline *without* its appendices — appendices are typically supplementary material (survey instruments, interview guides, extra tables, additional implementation detail) that would otherwise inflate or distract from an outline focused on the paper's main argument. For the full outline including appendices, use `extract-top-level-section-names` itself.

## Input

Same as `extract-top-level-section-names`: one PDF path. Same rule about not silently running this once per file if the user actually wants multiple papers compared — point to `directional-section-mapping`/`paper-section-alignment` instead.

## Workflow

### Step 1: Extract the full top-level section list

Follow `extract-top-level-section-names`'s full workflow exactly, through its own Step 3 — don't skip or improvise any part of it (the `pdftotext -layout` vs. plain fallback, the numbering-convention checklist covering Arabic/Roman/lettered schemes, the cross-check-against-page-count pass). This produces the complete, unfiltered list of every top-level section, appendices included, in the same two-field `section_name`/`section_number` shape.

### Step 2: Identify and remove appendix sections

From that full list, remove every entry that functions as an appendix. **This is a judgment about the section's role and position in the paper, not a mechanical pattern match on the label.** A section is an appendix if it is:

- Headed literally "Appendix," "Appendices," or "Supplementary Material" (with or without a number), or
- A lettered or separately-numbered chapter appearing *after* the paper's main numbered sections and after References/Acknowledgments, that supplements the main argument (survey instruments, interview guides, additional implementation detail, extra tables) rather than continuing it — e.g. "A Formative Interview Guideline," "B Features Implemented," "C User Study," "D Interview Guideline for Case Study."

**Never mistake a main section's own numbering convention for a lettered appendix.** Some papers number their main sections with Roman numerals (`I. INTRODUCTION`, `II. RELATED WORK`), and a low Roman numeral like `I` or `V` can superficially resemble a single letter — that's still a main section, not an appendix, and must stay in the output. Judge by the section's position (does it come after References/Acknowledgments?) and its role (does it supplement rather than continue the argument?), never by whether its label happens to be one character long.

**Keep everything else exactly as the base skill produced it** — Abstract, Preface, Acknowledgments, References, and every main numbered section stay in, unchanged, in their original order. This step only removes appendix entries; it doesn't re-derive, re-order, or re-format anything else.

### Output

Save the filtered array with the same two-field schema as `extract-top-level-section-names` (`section_name`, `section_number`) — same strict schema, same rule against adding extra fields. Default filename `sections-excluding-appendices.json`, deliberately different from the base skill's default `sections.json` so the two can coexist for the same paper without one silently overwriting the other. Save in the working directory or wherever the user specifies.

Tell the user how many top-level sections were found in total, how many were removed as appendices (and their names), and how many remain in the output. If there's any genuine ambiguity about whether a given section counts as an appendix (e.g. a "Supplementary Analysis" section that isn't clearly back matter), flag it rather than silently deciding.

### Output schema (strict)

Identical to `extract-top-level-section-names`'s own schema:

```json
{
  "section_name": "string, as written in the paper",
  "section_number": "string, or null for unnumbered sections"
}
```

No `is_appendix` flag, no `removed_appendices` list bundled into the same file — if the user wants to know what was excluded, say so in your response text, not in the JSON.

## Common mistakes to avoid

- **Re-deriving the header-extraction logic from memory instead of running `extract-top-level-section-names`'s own full workflow.** The `pdftotext` fallback rules and cross-check discipline are easy to get subtly wrong by improvising — always run the base skill's actual Step 1–3, don't approximate them.
- **Filtering by label pattern (e.g. "single letter" or a regex like `^[A-Z]$`) instead of by role and position.** This will wrongly strip a Roman-numeral-numbered main section (one literally labeled `I` or `V`) and/or wrongly keep a multi-character-labeled appendix. Appendix status is about where a section sits and what job it does, not the shape of its label.
- **Excluding References, Acknowledgments, Abstract, or Preface along with the appendices.** These are unnumbered back/front matter too, but they are not appendices — they stay in the output, same as the base skill's own rule.
- **Adding a field to mark what was removed, or to flag entries that were "kept despite looking like an appendix."** Keep the output schema exactly as strict as the base skill's — communicate any of that in your response text instead.
- **Running this skill when the user actually wants appendices included.** If it's unclear which the user wants, ask, or default to `extract-top-level-section-names` (the full extraction) and only use this variant when appendix-exclusion was explicitly requested.
- **Silently resolving genuine ambiguity** (e.g. a section that reads as a hybrid — extended results presented under an appendix-style label but still continuing the main argument) instead of flagging it in the summary to the user.
- **Reusing the base skill's default filename `sections.json`.** Use `sections-excluding-appendices.json` (or another name the user specifies) so a full and a filtered extraction of the same paper can coexist without collision — see the filename-collision incident documented for the extraction orchestrator, which this same risk mirrors.


