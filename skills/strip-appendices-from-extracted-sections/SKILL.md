---
name: "strip-appendices-from-extracted-sections"
description: "Given the four files \"orchestrator-extract-sections-paragraphs-and-questions\" already produced for one paper ({paper-name}-sections.json, -sections-with-paragraph-content.json, -sections-with-paragraphs-and-questions.json, -sections-with-questions-only.json, all appendices included), removes the appendix entries from all four and saves them under a -no-appendices suffix -- no PDF opened, no re-extraction, no re-splitting of paragraphs, no re-composing of questions, just a filter. Reuses \"extract-top-level-section-names-excluding-appendices\"'s own role-and-position appendix rule rather than reinventing it. Use when a paper already has full (appendix-included) extraction output and the user wants an appendix-excluded version derived from it without re-reading the PDF or risking a filename collision. If no prior extraction exists yet for this paper, use \"orchestrator-extract-sections-paragraphs-questions-no-appendices\" instead, which extracts directly from the PDF."
---

# Strip Appendices from Already-Extracted Sections

## What this is (and isn't)

This is a pure filtering skill: given the four files already produced by `orchestrator-extract-sections-paragraphs-and-questions` for one paper (sections, paragraphs, paragraphs-and-questions, questions-only — all appendices included), it removes the appendix entries from all four and saves them under new, non-colliding filenames. It does no PDF reading, no re-extraction, no re-splitting of paragraphs, and no re-composition of questions — every paragraph, every question, and every non-appendix section's content is carried over verbatim from the input files. Its only job is identifying which top-level entries are appendices and removing exactly those entries (and nothing else) from all four files consistently.

This exists specifically so that excluding appendices from an already-processed paper doesn't require re-running the entire extraction pipeline — which would mean re-reading the PDF, re-splitting paragraphs, and re-composing questions a second time, expensive and, since it's an independent LLM pass, not guaranteed to reproduce byte-identical non-appendix content to the first run. It also avoids the filename collision that would occur if a fresh appendix-excluded extraction were written directly over the base orchestrator's own files for the same paper — that's the specific problem this skill was built to solve, in place of overwriting on collision.

If no base-orchestrator output exists yet for this paper, this skill doesn't apply — there's nothing to filter. Run `orchestrator-extract-sections-paragraphs-questions-no-appendices` instead, which extracts directly from the PDF, excluding appendices from the start. That orchestrator now checks for existing base-orchestrator output automatically and calls this skill when it's available — see that skill's own "Which path to use" section.

For the appendix-identification rule itself, this skill reuses — does not reinvent — the same role-and-position judgment `extract-top-level-section-names-excluding-appendices` already documents: identified by role and position (appears after References/Acknowledgments; supplements rather than continues the argument; literally titled Appendix/Appendices/Supplementary Material), never by label shape, so a Roman-numeral main section labeled "I" or "V" is never mistaken for a lettered appendix.

## Inputs

Four files, all produced by `orchestrator-extract-sections-paragraphs-and-questions` (or otherwise sharing its exact schema) for one paper:

1. `{paper-name}-sections.json`
2. `{paper-name}-sections-with-paragraph-content.json`
3. `{paper-name}-sections-with-paragraphs-and-questions.json`
4. `{paper-name}-sections-with-questions-only.json`

`{paper-name}` is the literal PDF filename (minus `.pdf`) already used as the prefix on these four files. If any of the four is missing, stop and flag it — don't proceed with a partial set (see "Common mistakes to avoid").

## Workflow

### Step 1: Identify which entries are appendices

Working from `{paper-name}-sections.json` (the simplest of the four to reason over), apply `extract-top-level-section-names-excluding-appendices`'s own appendix-identification rule — consult that skill's current SKILL.md rather than approximating it from memory, since the rule was deliberately written to avoid label-shape shortcuts like "exclude anything with a single-letter section number." Produce the list of `(section_name, section_number)` pairs that are appendices; every other entry is kept.

### Step 2: Remove those entries from all four files

For each of the four input files, remove every entry whose `(section_name, section_number)` matches an appendix identified in Step 1. Do not alter, re-split, re-summarize, or re-derive anything about the entries that remain — their `paragraphs` arrays, `question_this_section_answers` fields, and all other fields must be carried over byte-for-byte from the input. This is a filter, not a re-extraction: even if a kept entry's content looks like it could be improved (a better-composed question, a cleaner paragraph split), leave it as-is anyway — that's out of scope here and would silently diverge this filtered output from what a fresh extraction would have produced.

### Step 3: Save under non-colliding filenames

Save the four filtered files with a `-no-appendices` suffix added to each of the four base filenames, so they never collide with the four input files they were derived from:

| Output file | Derived from |
|---|---|
| `{paper-name}-sections-no-appendices.json` | `{paper-name}-sections.json` |
| `{paper-name}-sections-with-paragraph-content-no-appendices.json` | `{paper-name}-sections-with-paragraph-content.json` |
| `{paper-name}-sections-with-paragraphs-and-questions-no-appendices.json` | `{paper-name}-sections-with-paragraphs-and-questions.json` |
| `{paper-name}-sections-with-questions-only-no-appendices.json` | `{paper-name}-sections-with-questions-only.json` |

## Output

Same four-file set as above. Output schemas for each file are unchanged from their originals (`extract-top-level-section-names`, `extract-section-paragraphs`, `annotate-section-questions-given-paragraphs`) — filtering removes entries, it never adds, renames, or reshapes fields.

Briefly tell the user how many appendix entries were removed (name and number of each) and how many non-appendix entries remain in the final files.

## Common mistakes to avoid

- **Re-deriving the appendix rule from memory instead of consulting `extract-top-level-section-names-excluding-appendices`'s current SKILL.md.** Don't approximate it as "single-letter section numbers" — see that skill's own documented Roman-numeral caveat.
- **Re-splitting paragraphs, re-composing questions, or otherwise "improving" the kept entries.** This is a pure filter; the whole point is that non-appendix content is carried over unchanged from a prior extraction, not regenerated.
- **Reusing the base orchestrator's own filenames for the output.** That's the exact collision this skill exists to avoid — always use the `-no-appendices` suffix.
- **Running this on a paper that hasn't been through `orchestrator-extract-sections-paragraphs-and-questions` yet.** There's nothing to filter in that case — run `orchestrator-extract-sections-paragraphs-questions-no-appendices` instead, which extracts from the PDF directly.
- **Filtering only some of the four files.** All four use the same `(section_name, section_number)` identity for their entries — an appendix removed from `sections.json` must be removed from all three of the others too, or the four files fall out of sync with each other.
- **Proceeding with only some of the four input files present.** Stop and flag it instead of guessing what the missing file would have contained.
- **Silently dropping a section that only looks appendix-like by position (e.g. it's simply the paper's last main section) without confirming it actually functions as an appendix by role.** Same caution as the skill this rule is borrowed from.


