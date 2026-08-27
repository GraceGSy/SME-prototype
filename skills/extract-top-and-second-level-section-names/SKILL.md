---
name: "extract-top-and-second-level-section-names"
description: "Extracts a paper's top-level AND second-level section names/numbers from a single PDF, nested under each top-level entry's \"subsections\" array (empty if none). Second-level headers are detected two ways, checked on every section: nested/decimal numbering (\"2.1\"), OR a genuine unnumbered header -- a short standalone line immediately followed by body text, not a bolded phrase fused into a paragraph (section_number null for these) -- the same signal \"extract-top-level-section-names\" already uses to spot a numberless top-level boundary, applied one level down. Caps at exactly two levels -- third-level content, numbered or not, is excluded entirely. Same top-level identification rules as \"extract-top-level-section-names\". Use for a paper's outline down to subsections, or before subsection-level comparison across papers. Names-only. For top-level-only, use \"extract-top-level-section-names\"; for content, use \"extract-section-paragraphs\"."
---

---
name: "extract-top-and-second-level-section-names"
description: "Extracts a paper's top-level AND second-level section names/numbers from a single PDF, nested under each top-level entry's \"subsections\" array (empty if none). Second-level headers are detected two ways, checked on every section: nested/decimal numbering (\"2.1\"), OR a genuine unnumbered header -- a short standalone line immediately followed by body text, not a bolded phrase fused into a paragraph (section_number null for these) -- the same signal \"extract-top-level-section-names\" already uses to spot a numberless top-level boundary, applied one level down. Caps at exactly two levels -- third-level content, numbered or not, is excluded entirely. Same top-level identification rules as \"extract-top-level-section-names\". Use for a paper's outline down to subsections, or before subsection-level comparison across papers. Names-only. For top-level-only, use \"extract-top-level-section-names\"; for content, use \"extract-section-paragraphs\"."
---

# Extract Top- and Second-Level Section Names

## What this is (and isn't)

This extracts one paper's top-level section names AND their immediate subsections (one level down) — names and numbers only, nothing about content. It's a superset of `extract-top-level-section-names`: Step 2 below (top-level identification) is that skill's own Step 2, reproduced here so this skill is self-contained. Step 3 (second-level identification) is new work specific to this skill, but it deliberately reuses the same underlying signal Step 2 already relies on — see Step 3b below.

**Caps at exactly two levels, always.** A numbered header like `2.1.3` (three or more components) is third-level and is excluded entirely — not extracted, not flattened up into its `2.1` parent. The same cap applies to unnumbered third-level content: a bolded run-in phrase fused into a subsection's own paragraph text (e.g. "**Select** refers to picking a data point...") is never extracted as anything, at any level — see Step 3's standalone-line test for exactly what does and doesn't count.

**Second-level headers are detected two ways — checked on every top-level section, every time, not just when the paper looks unnumbered.** A real 5-paper spot-check (2026-08-27) found unnumbered subsections in three different papers, including one (Pirolli & Card 2005) that mixes numbered and unnumbered subsections within the same document — numbered `2.1`/`2.2` early on, then unnumbered standalone headings ("Foraging Loop", "Sense making loop") later. So both checks below run on every section unconditionally, the same "never conditioned on the text looking suspicious" discipline `extract-section-paragraphs` already applies to its own three paragraph-break signals.

1. **Numbered**: nested/decimal numbering exactly one level below the parent's own number (`2.1` under `2`, `A.1` under `A`).
2. **Unnumbered**: a genuine subsection header with no number at all — see Step 3b for the exact test. `section_number` is `null` for these, same convention as an unnumbered top-level section.

This does not compare against another paper, and it does not read section content — same non-goals as `extract-top-level-section-names`. If the user's request involves a second PDF or a "closest match," point them to `directional-section-mapping` or `paper-section-alignment` instead. If the user wants each section's actual text or paragraphs, that's `extract-section-paragraphs` — it accepts a flat `sections.json`-shaped list, so run it on the flattened top-level entries from this skill's output (drop the `subsections` field per entry) unless a subsection-aware variant is what's actually needed.

## Input

One PDF path. If the user gives more than one PDF and wants them compared, stop and point them to `directional-section-mapping` or `paper-section-alignment` instead — don't silently run this skill once per file unless they specifically ask for each paper's section/subsection names extracted independently (not compared).

## Workflow

### Step 1: Extract text

Run `pdftotext -layout` on the PDF first. If the paper uses a two-column layout and headers come out garbled, split mid-word, or interleaved with running headers/footers/page numbers, fall back to plain `pdftotext` (no `-layout`) — it usually preserves reading order better for column text even though it loses spatial layout. Try both if the first pass looks questionable; don't assume `-layout` always wins.

### Step 2: Identify top-level headers

Identical rule to `extract-top-level-section-names`'s own Step 2 — reproduced here, not reinvented:

Look for numbered top-level section headers. Don't assume a single numbering convention — common ones include:

- Arabic numerals: `1 Introduction`, `1. Introduction`
- IEEE-style Roman numerals: `I. INTRODUCTION`, `II. RELATED WORK`
- Lettered appendices: `A Appendix Title`

A header is **top-level** if it isn't further subdivided by a decimal or nested numbering (`2.1 Design Goals` is a subsection, not top-level — exclude it from the top-level list; it belongs in Step 3 instead).

**Include Abstract, Preface, and Acknowledgments** as unnumbered top-level sections (`section_number: null`), along with other unnumbered front/back matter that reflects real structure — References, Appendix (or lettered appendix chapters), Bibliography — unless the user only wants numbered sections.

**This already generalizes to a paper whose main-body sections are entirely unnumbered, not just Abstract/Acknowledgments/References — confirmed directly against real prior output, not just theorized.** `extract-top-level-section-names` doesn't actually need a header to match one of the specific named front/back-matter examples above — its own anti-grep-alone strategy (below: "skim... for anything that looks like a section boundary the grep missed — a short, capitalized, standalone line followed by body text") is the real, general signal, and it doesn't require a number or a match against that example list. Checked directly against `crowdsourcinggraphical`'s (CHI 2010) already-produced `sections-no-appendices.json`: every top-level header — "Introduction", "Graphical Perception", every experiment section, not just Abstract/References — came out correctly with `section_number: null`. So this was already working correctly in practice; the named categories above are examples of what commonly shows up unnumbered, not an allow-list to check a header against before including it.

**Exclude purely navigational front matter that isn't a content section at all**: Cover Page, Table of Contents, List of Figures, List of Tables. **Also exclude publisher template/metadata blocks** that appear before Section 1 in some venues' formats — e.g. ACM's **CCS Concepts**, **Keywords**, and **ACM Reference Format** blocks.

Grep alone will miss things: PDF text extraction sometimes splits a header across two lines, drops the number, or merges it with the following paragraph's first line. After grepping, cross-check the count of headers found against the paper's actual page count and skim the extracted text for anything that looks like a section boundary the grep missed (a short, capitalized, standalone line followed by body text).

### Step 3: Identify second-level headers within each top-level section

For each top-level section from Step 2, look within its text (up to the start of the next top-level section) for BOTH of the following, in any combination — a single top-level section can have some numbered and some unnumbered subsections:

**3a. Numbered second-level headers** — nested numbering exactly one level below the parent:

- Under Arabic-numbered top-level `2`, second-level headers look like `2.1`, `2.2`, `2.3`, ...
- Under lettered top-level `A`, second-level headers look like `A.1`, `A.2`, ... (or occasionally `A.a`, `A.b` — check what the paper actually uses).
- IEEE Roman-numeral top-level sections (`II. RELATED WORK`) commonly number their subsections in Arabic (`II-A`, `II-B`, or sometimes just `A`, `B` restarting per section) rather than `2.1`/`2.2` — check the paper's actual convention rather than assuming decimal numbering universally applies.
- Under unnumbered top-level sections, a numbered subsection is rare but not impossible — check rather than assuming.

**3b. Unnumbered second-level headers — the same signal Step 2 already uses for top-level boundaries, applied one level down.** Step 2's own anti-grep-alone strategy identifies a numberless top-level section by exactly one signal: "a short, capitalized, standalone line followed by body text." Apply that identical signal here, one level down, with the details spelled out explicitly since subsections carry more false-positive risk (chart-axis labels, bolded emphasis mid-paragraph) than top-level boundaries do. A line counts as an unnumbered subsection header only if ALL of the following hold:

- It occupies its **own line**, with nothing else (no body prose) before or after it on that line.
- It's **short** — a title or phrase, not a sentence (no terminal punctuation like a period ending a full sentence; a phrase like "Stimuli" or "Foraging Loop" is typical, not "Our experiment proceeded as follows.").
- It's visually distinct in the source (bold, or a clear capitalization/title-case break from surrounding body prose) — cross-check against `-layout` or plain `pdftotext` output; font/weight isn't always preserved, so title-case-on-its-own-line is enough corroborating evidence even without a bold signal.
- It's **immediately followed by body paragraph text** (a new paragraph begins right after it) — this is the "followed by body text" half of Step 2's own signal.

**This deliberately excludes bolded run-in phrases fused into the start of a paragraph's own prose** — e.g. "**Select** refers to picking a data point..." or "**Requirement 1:** The system must..." — these continue directly into flowing sentence text on the same line and are emphasis, not structural headers, even though they're bold and even though they might look prominent. The test is standalone-line-then-new-paragraph, not boldness. Real examples of genuine unnumbered subsections, confirmed directly against PDFs in this corpus: `measuringseparability` uses "Stimuli", "Procedure", "Participant Recruitment", "Graphical Perception" this way throughout, with no numbering anywhere in the paper's subsections; `crowdsourcinggraphical` repeats "Method" and "Results" as standalone unnumbered headers under each of its several experiment sections; Pirolli & Card (2005) uses "Foraging Loop" and "Sense making loop" this way, but only in the later, unnumbered portion of the paper — its earlier sections use real `2.1`/`2.2` numbering, so both signals must be checked on every section rather than picking one convention for the whole paper.

**Stop at exactly one level down, for both 3a and 3b.** A numbered header two components below the parent (`2.1.1`) is third-level — exclude it entirely. An unnumbered bolded run-in phrase found *inside* an already-identified subsection's own paragraph text is third-level content, not a second-level header — exclude it too, don't extract it as a peer of the subsection it's nested inside.

Apply the same anti-grep-alone caution as Step 2: a subsection header (numbered or not) can be split across lines, have its number dropped, or merge with the paragraph that follows. Cross-check against the section's actual length and skim for boundaries grep might have missed.

### Step 4: Build the nested output

For each top-level section, in the order it appears in the paper, produce an entry with its own name/number plus a `subsections` array of its immediate second-level headers (from both 3a and 3b), in the order they appear within that section:

| Field | Description |
|---|---|
| `section_name` | The section's title, as written (don't reformat capitalization or punctuation) |
| `section_number` | The section's number/letter as a string (e.g. `"3"`, `"II"`, `"A"`), or `null` for unnumbered sections |
| `subsections` | Array of `{section_name, section_number}` objects for this section's immediate second-level headers, in order. `[]` if the section has none — never omitted, never `null` |

Each object inside `subsections` uses the same two fields (`section_name`, `section_number`) as a top-level entry — never a nested `subsections` field of its own. `section_number` inside a subsection object is `null` for an unnumbered subsection (Step 3b), exactly like an unnumbered top-level section.

## Output

Save as a JSON array of these nested objects, named `sections-with-subsections.json`, in the working directory (or wherever the user specifies).

Briefly tell the user how many top-level sections and how many total second-level subsections were found, how many of the subsections were numbered vs. unnumbered, and flag anything uncertain — an ambiguous section/subsection boundary, an inconsistent numbering convention, or a standalone line you weren't fully confident passed the Step 3b test.

### Output schema (strict)

ALWAYS use this exact shape for every top-level entry — exactly these three keys, no additions, no renaming, no reordering:

```json
{
  "section_name": "string, as written in the paper",
  "section_number": "string, or null for unnumbered sections",
  "subsections": [
    {"section_name": "string, as written in the paper", "section_number": "string, or null for unnumbered subsections"}
  ]
}
```

Each `subsections` entry uses exactly the two keys shown — no further nesting, no extra fields.

Full array example (numbered and unnumbered subsections both shown):

```json
[
  {"section_name": "Abstract", "section_number": null, "subsections": []},
  {"section_name": "Introduction", "section_number": "1", "subsections": []},
  {"section_name": "Related Work", "section_number": "2", "subsections": [
    {"section_name": "Prior Systems", "section_number": "2.1"},
    {"section_name": "Design Space", "section_number": "2.2"}
  ]},
  {"section_name": "General Methods", "section_number": "4", "subsections": [
    {"section_name": "Stimuli", "section_number": null},
    {"section_name": "Procedure", "section_number": null}
  ]},
  {"section_name": "References", "section_number": null, "subsections": []},
  {"section_name": "Data Collection Protocol", "section_number": "A", "subsections": [
    {"section_name": "Consent Materials", "section_number": "A.1"}
  ]}
]
```

Don't add extra fields at either level even if they'd seem useful — no `page_number`, no `confidence`, no section text, no third-level nesting. Downstream skills that consume this output are written against exactly this three-key top-level / two-key subsection schema.

## Common mistakes to avoid

- **Including third-level headers, numbered or not** — not `2.1.1` as its own entry, not an unnumbered run-in phrase found inside a subsection's own paragraph. Exclude both entirely; this is the documented two-level cap.
- **Treating a bolded run-in phrase fused into the start of a paragraph as a subsection just because it's bold or visually prominent.** Apply the full standalone-line test from Step 3b — own line, short, no terminal sentence punctuation, immediately followed by a new paragraph. A phrase that continues into flowing prose on the same line is emphasis, not a heading, no matter how it's styled.
- **Only checking for numbered subsections, or only checking for unnumbered ones, based on how the paper looks at a glance.** Check both 3a and 3b on every top-level section, every time — a paper can mix the two (confirmed directly: Pirolli & Card 2005 uses real `2.1`/`2.2` numbering early on and switches to unnumbered standalone headings later in the same document).
- **Assuming a numberless top-level header must match one of the specific named front/back-matter examples (Abstract/Acknowledgments/References/Appendix) before including it.** Those are examples, not an allow-list — apply `extract-top-level-section-names`'s own general signal (a short, standalone, capitalized line followed by body text) instead. This is already confirmed working correctly in practice on a fully-unnumbered paper (`crowdsourcinggraphical`), not a hypothetical edge case.
- **Omitting the `subsections` field, or setting it to `null`, for a section with no subsections.** Always `[]`.
- **Assuming decimal numbering (`2.1`) is universal for numbered subsections.** IEEE-style papers often use `II-A`/`II-B` or restart lettering per top-level section.
- **Reusing this skill's top-level identification logic loosely instead of applying `extract-top-level-section-names`'s exact Step 2 rules.** Step 2 here is that skill's Step 2, verbatim — don't drift from it.
- **Trusting a single grep pass** for either level. PDF text extraction is lossy enough that a header can be missed, split, or merged with body text — cross-check against section length/page count and skim before finalizing.
- **Adding fields beyond the strict schema** at either the top level or inside `subsections`.
- **Extracting or summarizing any section or subsection content.** Names and numbers only, at both levels.
- **Running this on a paper only to get top-level names.** If subsections aren't needed at all, use `extract-top-level-section-names` instead.

