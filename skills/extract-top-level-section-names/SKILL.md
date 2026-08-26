---
name: "extract-top-level-section-names"
description: "Extracts just the top-level section names (and their numbers/letters, e.g. \"1\", \"II\", \"A\") from a single paper PDF and saves them as a JSON array (sections.json). Names-only extraction — no section content, no subsections. Use whenever the user wants a paper's outline, table of contents, or list of top-level section names — \"what are the sections of this paper,\" \"give me the outline of this PDF,\" \"list the top-level headers/section names,\" or as a prerequisite before comparing/mapping sections across papers. The single-paper building block underlying \"directional-section-mapping\" and \"paper-section-alignment\" — use this one when only one PDF is involved and the user wants just top-level section names, no cross-paper comparison, no content. For mapping sections onto another paper, use \"directional-section-mapping\" or \"paper-section-alignment.\" For section content/paragraphs, use \"extract-section-paragraphs\" on this skill's output."
---

# Extract Top-Level Section Names

## What this is (and isn't)

This extracts one paper's top-level section names and their numbers — nothing else. It is a names-only extraction: it does not read section content, does not descend into subsections, and does not compare against any other paper. If the user's request involves a second PDF or a "closest match," this skill is the wrong tool — use `directional-section-mapping` (one-way) or `paper-section-alignment` (bidirectional) instead, both of which use this same extraction step internally before doing any comparison. If the user wants each section's actual text or paragraphs, that's `extract-section-paragraphs`, run on this skill's output.

## Input

One PDF path. If the user gives more than one PDF and wants them compared, stop and point them to `directional-section-mapping` or `paper-section-alignment` instead — don't silently run this skill once per file unless they specifically ask for each paper's section names extracted independently (not compared).

## Workflow

### Step 1: Extract text

Run `pdftotext -layout` on the PDF first. If the paper uses a two-column layout and headers come out garbled, split mid-word, or interleaved with running headers/footers/page numbers, fall back to plain `pdftotext` (no `-layout`) — it usually preserves reading order better for column text even though it loses spatial layout. Try both if the first pass looks questionable; don't assume `-layout` always wins.

### Step 2: Identify top-level headers

Look for numbered top-level section headers. Don't assume a single numbering convention — common ones include:

- Arabic numerals: `1 Introduction`, `1. Introduction`
- IEEE-style Roman numerals: `I. INTRODUCTION`, `II. RELATED WORK`
- Lettered appendices: `A Appendix Title`

A header is **top-level** if it isn't further subdivided by a decimal or nested numbering (`2.1 Design Goals` is a subsection, not top-level — exclude it). This skill only ever extracts the name and number of a top-level header, never its content and never a subsection's name.

**Include Abstract, Preface, and Acknowledgments** as unnumbered top-level sections (`section_number: null`), along with other unnumbered front/back matter that reflects real structure — References, Appendix (or lettered appendix chapters), Bibliography — unless the user only wants numbered sections.

**Exclude purely navigational front matter that isn't a content section at all**: Cover Page, Table of Contents, List of Figures, List of Tables. **Also exclude publisher template/metadata blocks** that appear before Section 1 in some venues' formats — e.g. ACM's **CCS Concepts**, **Keywords**, and **ACM Reference Format** blocks — these are formatting boilerplate imposed by the venue, not sections the authors wrote to structure their argument.

Grep alone will miss things: PDF text extraction sometimes splits a header across two lines, drops the number, or merges it with the following paragraph's first line. After grepping, cross-check the count of headers found against the paper's actual page count and skim the extracted text for anything that looks like a section boundary the grep missed (a short, capitalized, standalone line followed by body text).

### Step 3: Build the output

For each top-level section, in the order they appear in the paper, produce an entry with just its name and number — nothing about its content:

| Field | Description |
|---|---|
| `section_name` | The section's title, as written (don't reformat capitalization or punctuation) |
| `section_number` | The section's number/letter as a string (e.g. `"3"`, `"II"`, `"A"`), or `null` for unnumbered sections like Abstract/Acknowledgments/References |

### Output

Save as a JSON array of these objects, named `sections.json`, in the working directory (or wherever the user specifies).

Briefly tell the user how many top-level section names were found and flag anything uncertain — e.g. a section boundary that was ambiguous, or a numbering convention that was inconsistent partway through the paper.

### Output schema (strict)

ALWAYS use this exact shape for every entry — exactly these two keys, no additions, no renaming, no reordering:

```json
{
  "section_name": "string, as written in the paper",
  "section_number": "string, or null for unnumbered sections"
}
```

The file itself is a JSON array of these objects, e.g.:

```json
[
  {"section_name": "Abstract", "section_number": null},
  {"section_name": "Introduction", "section_number": "1"},
  {"section_name": "Related Work", "section_number": "2"},
  {"section_name": "References", "section_number": null},
  {"section_name": "Formative Interview Study Participants", "section_number": "A"}
]
```

Don't add extra fields even if they'd seem useful in the moment — no `page_number`, no `subsections`, no `confidence`, no section text or content of any kind. This skill's whole job is names and numbers only. Downstream skills that consume `sections.json` (`extract-section-paragraphs`, `annotate-section-questions`, `directional-section-mapping`, `directional-section-mapping-by-paragraphs-and-questions`, and others) are written against exactly this two-field schema, and an extra or renamed field will silently break them rather than raising an obvious error.

## Common mistakes to avoid

- **Including subsections.** Only top-level sections belong in the output — `2.1`, `2.2`, etc. are not top-level even if they look prominent in the layout.
- **Assuming Arabic numerals.** Always check what convention the paper actually uses before extracting; IEEE/robotics-style papers commonly use Roman numerals, and some papers use no numbers at all.
- **Trusting a single grep pass.** PDF text extraction is lossy enough that a header can be missed, split, or merged with body text. Cross-check against page count and skim before finalizing.
- **Dropping unnumbered sections like Abstract, Acknowledgments, References, or Appendix.** These are still top-level structural elements — include them with `section_number: null` rather than silently excluding them, unless the user asks only for numbered sections.
- **Including navigational front matter or venue metadata blocks.** Cover Page, Table of Contents, List of Figures, and List of Tables aren't content sections at all, and CCS Concepts/Keywords/ACM Reference Format are venue-imposed formatting boilerplate, not sections the authors wrote — always leave these out, even though Abstract/Preface/Acknowledgments (also boilerplate-ish) should be included.
- **Adding fields beyond `section_name` and `section_number`.** Even well-intentioned extras like a page number or a confidence score break the strict schema downstream skills expect — see "Output schema (strict)" above.
- **Extracting or summarizing any section content.** This skill produces names and numbers only — if the user also wants a section's text, that's `extract-section-paragraphs`, a separate step run on this skill's output.

