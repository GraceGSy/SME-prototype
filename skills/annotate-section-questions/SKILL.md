---
name: "annotate-section-questions"
description: "Given a sections.json file (from \"extract-top-level-section-names\") and the PDF it was extracted from, reads each section's actual text in the PDF and adds a \"question_this_section_answers\" field to every entry, saved as a new file sections-with-questions.json. Use whenever the user wants to know what role or purpose each section of a single paper serves, \"what question does each section answer,\" \"annotate these sections with their purpose,\" or as a prerequisite before role-based section comparison across papers. This is a single-paper building block — it does not compare against any other paper. For comparing one paper's sections to another's, use \"directional-section-mapping\" or \"paper-section-alignment\" instead, both of which reason about this same kind of role-level question when matching sections."
---

# Annotate Section Questions

## What this is (and isn't)

This reads one paper's actual section content and, for each section already identified by `extract-top-level-section-names`, articulates the single question that section exists to answer in the paper's argument. It does not compare against another paper, judge quality, or summarize content in general — it produces exactly one new field per entry, framed around the section's *role*, not its topic.

If the user hasn't already run `extract-top-level-section-names` on this PDF, run that first (or point them to it) — this skill takes its output (`sections.json`) as input rather than re-deriving the section list itself.

## Inputs

1. A `sections.json` file: a JSON array of `{section_name, section_number}` objects, in the order the sections appear in the paper.
2. The PDF path those sections were extracted from.

## Workflow

### Step 1: Extract full text

Run `pdftotext -layout` on the PDF (fall back to plain `pdftotext` if headers or body text come out garbled for a two-column layout — same guidance as `extract-top-level-section-names`).

### Step 2: Locate each section's boundaries

For each entry in `sections.json`, in order:

- **Start**: find where that section's header actually appears in the body text (not just a mention of the title elsewhere, and not the Table of Contents if the PDF has one — skip past any ToC-style listing near the front of the document).
- **End**: the start of the *next* entry in `sections.json` (regardless of whether that next entry is numbered or not — e.g. if `sections.json` lists `8 Discussion` followed by `Acknowledgments`, Discussion's content runs up to the start of Acknowledgments). For the last entry in the list, its content runs to the end of that section's natural extent (end of document, or wherever the next unlisted boilerplate like a bibliography actually starts if the last entry isn't References/Bibliography itself).
- A section's own subsections belong to it — don't stop at the first subsection header, keep going until the next entry in `sections.json`.

If a section's header can't be confidently located in the body text (extraction dropped it, wrapped it across lines, etc.), don't guess at arbitrary boundaries — search nearby text for the title's distinctive wording before giving up, the same way `extract-top-level-section-names` cross-checks against page count.

### Step 3: Read the section and articulate the question it answers

Read the section's actual text — not just its title. Then write one question that this section exists to answer in the paper's argument, following the same role-based framing used elsewhere in this project: ask "what job is this section doing — what does the reader need answered before moving to the next part of the paper?" not "what topic does this section cover?"

- Frame the question around the section's function in the paper's arc (e.g. "What gap in prior work does this system address?"), not a restatement of its title or a content summary (not "What is discussed in the Related Work section?").
- **If the section has multiple subsections, the question must span all of them, not just the first or most prominent one.** A section with subsections is usually doing several related jobs (e.g. describing multiple system components, or reporting several sub-studies) that together answer one broader question — find that broader question rather than picking whichever subsection happens to be most interesting or easiest to summarize. If the subsections are different enough that no single question honestly covers all of them, say so explicitly in the question itself rather than silently narrowing it (e.g. "What are the system's components, and how does implementation and a worked usage scenario together demonstrate them?" rather than just "What are the system's components?" when the section also has implementation and usage-scenario subsections).
- **Watch for a single connecting verb-frame that's topically complete but type-narrow.** A section can name every sub-topic and still silently exclude a different kind of content coexisting with it — e.g. a qualitative-results section built from interview coding often reports both what participants did (behavior/usage) and how they felt about it (confidence, satisfaction, perception), sometimes in the same paragraph. A question framed only as "what did analysis reveal about how participants used X" can list every feature and still exclude the self-reported half of those same paragraphs. Before finalizing, check each paragraph for what TYPE of finding it reports (behavior vs. attitude/experience vs. both), not just which topic it belongs to.
- **Keep the question short and genuinely open — don't embed the answer inside the question itself.** A question padded with an em-dash aside or parenthetical listing out specifics has stopped being a question; it's an answer wearing a question mark. For example, this is too wordy and self-answering: "What problem does existing corpus-reading tooling fail to solve—the cost of serial reading and the information loss inherent in prior lossy representations—and what novel, minimally lossy, Structural-Mapping-Theory-informed approach does AbstractExplorer contribute and validate through its three studies to address that gap?" (the em-dash clause answers the first half, and "novel, minimally lossy, Structural-Mapping-Theory-informed" answers the second half, before the question is even finished). Prefer something short and direct instead: "What gap in existing corpus-reading approaches motivates AbstractExplorer, and what approach does it contribute to address it?" If you're tempted to reach for a dash, colon, or parenthetical full of specifics, that detail belongs in your own understanding of the section, not in the question text — a genuine question doesn't give away its own answer.
- Even boilerplate-feeling sections get a real question: Abstract → something like "What does this paper contribute, and how was that established?"; References → "What prior work does this paper build on or cite?"; Acknowledgments can get a minimal but honest answer ("Who supported this work?") rather than being skipped, since every entry in `sections.json` must get one.
- This question should be usable on its own, without the reader having the section's content in front of them — write it so it stands alone.

### Step 4: Build the output

Copy every field from the original `sections.json` entry unchanged, and add one new field:

| Field | Description |
|---|---|
| `question_this_section_answers` | One question this section exists to answer, framed around its role in the paper's argument (see Step 3) |

Preserve the original order and all original fields (`section_name`, `section_number`, and any others already present).

### Output

Save as `sections-with-questions.json`, a JSON array, in the same directory as the input `sections.json` unless the user specifies otherwise. Don't overwrite `sections.json` itself.

Briefly tell the user how many sections were annotated and flag anything uncertain — e.g. a section whose boundary was ambiguous, or one where the "question" is a stretch because the section is thin (like a short Acknowledgments block).

### Output schema (strict)

ALWAYS use this exact shape for every entry — every field from the input `sections.json` preserved unchanged, plus exactly one new key (`question_this_section_answers`), no others added, none renamed, none reordered:

```json
{
  "section_name": "string, unchanged from the input",
  "section_number": "string or null, unchanged from the input",
  "question_this_section_answers": "string — a real question, never null or empty"
}
```

The file itself is a JSON array of these objects, e.g.:

```json
[
  {"section_name": "Abstract", "section_number": null, "question_this_section_answers": "What does this paper contribute, and how was that established?"},
  {"section_name": "Introduction", "section_number": "1", "question_this_section_answers": "What gap in prior work motivates this system, and what does it contribute?"},
  {"section_name": "References", "section_number": null, "question_this_section_answers": "What prior work does this paper build on or cite?"}
]
```

Unlike its PDF-free sibling (`annotate-section-questions-given-paragraphs`), `question_this_section_answers` is **never `null`** here — since this skill always has the actual PDF to read, every entry gets a real (if minimal) question, per Step 3. Don't add extra fields — no `confidence`, no `subsections`, no paragraph text — this skill's only job is adding the one question field.

## Common mistakes to avoid

- **Guessing the question from the title alone.** "Related Work" doesn't tell you what gap this paper's related work section is establishing — that requires reading the actual paragraphs. Always read the section text before writing its question.
- **Writing a topic/content question instead of a role question.** "What visualization techniques are discussed?" describes content; "What existing approaches does this design build on or depart from?" describes role. The latter is what this skill produces.
- **Misplacing a section boundary because the header text also appears elsewhere** (a citation to "Section 4," a running header/footer repeating the title, or a Table of Contents entry). Confirm you've found the actual body-text occurrence where the section content begins, not an incidental mention.
- **Stopping a section's text at its first subsection.** A section's content includes all of its subsections — only stop at the *next top-level entry* from `sections.json`.
- **Writing a question that only covers one subsection instead of the whole section.** Reading all the subsections (per the mistake above) isn't enough if the resulting question still only reflects one of them — e.g. a system-description section with "components," "implementation," and "usage scenario" subsections needs a question broad enough to cover all three, not just "what are the system's components?" because that subsection came first or was easiest to summarize.
- **Writing a long, compound question that answers itself via em-dash asides or parentheticals.** If the question needs a dash or parenthetical to pack in specific details ("...the cost of X and the information loss of Y..."), those details are the answer, not the question — cut them and keep the question short enough to actually be asked out loud.
- **Choosing one verb-frame ("how participants used X") that names every sub-topic but excludes a different kind of content that coexists with it (how participants felt about X).** Topical breadth isn't the same as coverage — check finding type per paragraph, not just topic.
- **Skipping thin or boilerplate sections.** Every entry in the input must get a `question_this_section_answers` value, even if the honest answer for something like Acknowledgments is minimal.
- **Overwriting `sections.json`.** This skill always writes a new file (`sections-with-questions.json`) so the original extraction is preserved.
- **Writing `null` for `question_this_section_answers`.** Unlike the paragraph-based sibling skill, this skill always has the PDF to read — there's no legitimate "no content to work from" case here, so every entry gets a real string.

