---
name: "extract-top-and-second-level-section-names-excluding-appendices"
description: "Variant of \"extract-top-and-second-level-section-names\" that excludes appendix sections from the output. Runs that skill's full extraction (top-level + subsections, nested), then removes any top-level entry that functions as an appendix -- judged by role and position, never by label shape alone, same rule as \"extract-top-level-section-names-excluding-appendices\". A removed appendix's subsections go with it. Keeps Abstract/Preface/Acknowledgments/References and all main sections, subsections intact. Use when the user wants a paper's outline down to subsections, without appendices -- e.g. before a subsection-level structural comparison focused on the main argument. Outputs sections-with-subsections-excluding-appendices.json with the same three-key/two-key nested schema. For the full outline including appendices, use \"extract-top-and-second-level-section-names\" instead."
---

---
name: "extract-top-and-second-level-section-names-excluding-appendices"
description: "Variant of \"extract-top-and-second-level-section-names\" that excludes appendix sections from the output. Runs that skill's full extraction (top-level + subsections, nested), then removes any top-level entry that functions as an appendix -- judged by role and position, never by label shape alone, same rule as \"extract-top-level-section-names-excluding-appendices\". A removed appendix's subsections go with it. Keeps Abstract/Preface/Acknowledgments/References and all main sections, subsections intact. Use when the user wants a paper's outline down to subsections, without appendices -- e.g. before a subsection-level structural comparison focused on the main argument. Outputs sections-with-subsections-excluding-appendices.json with the same three-key/two-key nested schema. For the full outline including appendices, use \"extract-top-and-second-level-section-names\" instead."
---

# Extract Top- and Second-Level Section Names (Excluding Appendices)

## What this is (and isn't)

This is a thin variant of `extract-top-and-second-level-section-names`, mirroring exactly how `extract-top-level-section-names-excluding-appendices` relates to `extract-top-level-section-names`. It produces the exact same nested top-level + subsections extraction, then removes any top-level entry that functions as an appendix before saving. It does not duplicate the underlying PDF-text-extraction, header-identification, or subsection-detection technique — that's `extract-top-and-second-level-section-names`'s own job; consult that skill's SKILL.md directly for the top-level rules, the two subsection-detection signals (3a numbered / 3b unnumbered standalone-line test), and the two-level cap. This skill adds exactly one new piece of logic on top: identifying and filtering out appendix top-level entries, subsections and all.

Use this when the user explicitly wants a paper's outline *down to subsections*, but *without* its appendices. For the full nested outline including appendices, use `extract-top-and-second-level-section-names` itself. For a top-level-only (no subsections) appendix-excluding extraction, use `extract-top-level-section-names-excluding-appendices` instead — this skill is specifically for when both "no appendices" and "with subsections" are wanted together.

**Appendix status is judged at the top level only, same scope as the base variant.** A top-level entry is removed as a whole — including every subsection nested inside it — based on that top-level entry's own role and position, never by inspecting its subsections individually. This skill does not judge whether an individual *subsection* under a kept, non-appendix top-level section is itself appendix-like (e.g. a "Survey Instrument" subsection tucked under a kept "Method" section) — that's out of scope here, same as it's out of scope for the top-level-only variant. If the user wants that finer-grained judgment, flag it explicitly rather than improvising a new rule.

## Input

Same as `extract-top-and-second-level-section-names`: one PDF path. Same rule about not silently running this once per file if the user actually wants multiple papers compared — point to `directional-section-mapping`/`paper-section-alignment` instead.

## Workflow

### Step 1: Extract the full nested top-level + subsections list

Follow `extract-top-and-second-level-section-names`'s full workflow exactly, through its own Step 4 — don't skip or improvise any part of it (the `pdftotext -layout` vs. plain fallback, the top-level identification rules, the 3a/3b subsection-detection signals checked on every section, the two-level cap, the cross-check-against-page-count discipline). This produces the complete, unfiltered nested list of every top-level section and its immediate subsections, appendices included, in the same three-key/two-key shape.

### Step 2: Identify and remove appendix top-level entries

From that full list, remove every top-level entry that functions as an appendix, using the **identical role-and-position judgment** `extract-top-level-section-names-excluding-appendices` already applies — reproduced here so this skill is self-contained:

- Headed literally "Appendix," "Appendices," or "Supplementary Material" (with or without a number), or
- A lettered or separately-numbered chapter appearing *after* the paper's main numbered sections and after References/Acknowledgments, that supplements the main argument (survey instruments, interview guides, additional implementation detail, extra tables) rather than continuing it.

**Never mistake a main section's own numbering convention for a lettered appendix.** A low Roman numeral like `I` or `V` under an IEEE-style paper is still a main section, not an appendix — judge by position (after References/Acknowledgments?) and role (supplements rather than continues the argument?), never by label length alone.

**When a top-level entry is removed, its entire `subsections` array goes with it** — there is no scenario in this skill where a subsection survives the removal of its own parent. Don't try to "rescue" an individual subsection of a removed appendix by promoting it to top-level; it isn't a top-level section, and this skill doesn't invent one.

**Keep everything else exactly as the base skill produced it** — every kept top-level entry's own `subsections` array stays completely untouched, same order, same content, same numbered/unnumbered mix. This step only removes whole appendix entries; it doesn't re-derive, re-order, or re-judge any subsection.

### Output

Save the filtered array with the same three-key/two-key nested schema as `extract-top-and-second-level-section-names` (`section_name`, `section_number`, `subsections: [{section_name, section_number}]`) — same strict schema, same rule against adding extra fields at either level. Default filename `sections-with-subsections-excluding-appendices.json`, deliberately different from both the base skill's own default `sections-with-subsections.json` (this file has appendices removed) and from `extract-top-level-section-names-excluding-appendices`'s own `sections-excluding-appendices.json` (this file is nested, that one is flat) — so all three can coexist for the same paper without collision. Save in the working directory or wherever the user specifies.

Tell the user how many top-level sections were found in total, how many were removed as appendices (and their names, plus how many subsections went with each), and how many top-level sections (and total subsections) remain. Flag genuine ambiguity about appendix status rather than silently deciding.

### Output schema (strict)

Identical to `extract-top-and-second-level-section-names`'s own schema:

```json
{
  "section_name": "string, as written in the paper",
  "section_number": "string, or null for unnumbered sections",
  "subsections": [
    {"section_name": "string, as written in the paper", "section_number": "string, or null for unnumbered subsections"}
  ]
}
```

No `is_appendix` flag, no `removed_appendices` list bundled into the same file — if the user wants to know what was excluded, say so in your response text, not in the JSON.

## Common mistakes to avoid

- **Re-deriving the header-extraction or subsection-detection logic from memory instead of running `extract-top-and-second-level-section-names`'s own full workflow.** The 3a/3b subsection signals and the two-level cap are easy to get subtly wrong by improvising — always run the base skill's actual Steps 1–4, don't approximate them.
- **Filtering by label pattern instead of by role and position.** Same risk as the top-level-only variant: this will wrongly strip a Roman-numeral-numbered main section and/or wrongly keep a genuine lettered appendix.
- **Judging an individual subsection's appendix-like content and removing just that subsection while keeping its parent.** Out of scope — this skill only removes whole top-level entries, never a single subsection out of an otherwise-kept parent.
- **"Rescuing" a subsection of a removed appendix by promoting it into the top-level list.** It was never a top-level section; don't invent one.
- **Excluding References, Acknowledgments, Abstract, or Preface along with the appendices.** These stay in, same as the base skill's own rule, subsections (if any) intact.
- **Adding a field to mark what was removed or why.** Keep the output schema exactly as strict as the base skill's.
- **Reusing `sections-with-subsections.json` or `sections-excluding-appendices.json` as the output filename.** Use `sections-with-subsections-excluding-appendices.json` so all three related files can coexist for the same paper.
- **Silently resolving genuine ambiguity** instead of flagging it in the summary to the user.

