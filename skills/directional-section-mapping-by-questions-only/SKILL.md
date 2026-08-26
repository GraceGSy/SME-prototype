---
name: "directional-section-mapping-by-questions-only"
description: "Given two sections-with-questions-only.json files (or sections-with-questions.json — same schema, from \"annotate-section-questions-given-paragraphs\" or \"annotate-section-questions\"), maps every section of \"paper1\" onto its closest section in \"paper2\" by comparing their pre-computed question_this_section_answers fields only — no PDF, no full section text. Outputs p1-p2-section-mapping-by-questions-only.json. Use when both papers already have question-only files and the user wants a fast, cheap directional mapping without re-reading either PDF, or explicitly says \"map by questions only\" / \"without reading the full sections again.\" For full-content-based directional mapping, use \"directional-section-mapping\" instead, which reads each PDF directly."
---

# Directional Section Mapping (By Questions Only)

## What this is (and isn't)

This is the question-only variant of `directional-section-mapping`: for every section in `paper1`, find its closest corresponding section in `paper2`, but do it purely by comparing each section's pre-computed `question_this_section_answers` value — never by opening a PDF or reading full section/paragraph text. If that field doesn't already exist for both papers, this is the wrong skill; run `annotate-section-questions-given-paragraphs` (if paragraphs are already extracted) or `annotate-section-questions` (if not) on each paper first.

Like its full-content sibling, this is a **single-direction** pass and does not check whether paper2's side of a pairing agrees when reasoned about independently. Run it twice (swapping which paper is `paper1`) if both directions are wanted, using distinct output filenames.

## Inputs

Two files, each a JSON array of section objects with at least `section_name`, `section_number`, and `question_this_section_answers` (any of `sections-with-questions-only.json`, `sections-with-paragraphs-and-questions.json`, or `sections-with-questions.json` will work, since they all carry this field — extra fields like `paragraphs` are simply ignored). The order the user gives the two files matters: the first is `paper1`, the correspondence is found *from* paper1's sections *to* paper2's sections. If it's ambiguous which should anchor the mapping, ask.

No PDF is needed or should be opened for this skill. If you find yourself reaching for `pdftotext` or an original PDF file, stop — everything required is already in the two input JSON files.

## Workflow

### Step 1: Read every section's question in both files

For each entry in both `paper1` and `paper2`'s input arrays, read its `question_this_section_answers` value. This is the *entire* basis for matching — there is no fuller text to fall back on, so treat each question as a compressed statement of that section's role in its paper's argument (which is exactly what it's for, per the skills that produced it).

**If an entry's `question_this_section_answers` is `null`** (this happens when the section had no extracted paragraph content to derive a question from — see `annotate-section-questions-given-paragraphs`), there is nothing to match it on:
- If it's a `paper1` entry: output `null` for its `paper2_section_name`/`paper2_section_number`, with `basis` explaining that no question was available to match against (not that no counterpart exists — those are different claims; say so explicitly).
- If it's a `paper2` entry: exclude it from consideration as a match candidate for any `paper1` section, since there's nothing to compare against. Don't let a null question "win" a match by default.

### Step 2: Map each paper1 section to its closest paper2 counterpart by comparing questions

For each `paper1` section with a non-null question, compare it against every `paper2` section's question (skipping any that are null, per Step 1) and find the one addressing the closest underlying role — "are these two questions fundamentally asking the same thing about their section's job in the paper?" not "do these two questions share vocabulary or topic."

- **If paper1's question is plausibly answered by more than one paper2 section** (e.g., paper1's question spans both what a paper2 pair of sections cover separately), create a **separate entry for each** correspondence rather than combining them into one entry — the same splitting rule as `directional-section-mapping`, and for the same reason: a combined label silently breaks downstream bidirectional comparison.
  - **Make sure the split entries, taken together, cover the full scope of paper1's original question — don't silently drop a piece of it.** If paper1's question bundles three sub-roles and only two of them map onto paper2 sections, say so explicitly (e.g., in the third-role's absence, either add a `null` entry noting what part of paper1's question has no paper2 counterpart, or name the gap in the `basis` of the entries you do write). A two-way split that quietly discards a third component of the original question is a coverage error, not a clean split.
  - **Keep each split entry's `question_the_sections_both_answer` distinctive from its sibling entries, not a generic restatement.** Since only one compressed source question exists on the paper1 side, it's easy for two split entries' shared-questions to end up nearly identical and lose the very distinction that justified splitting them in the first place. Anchor each split entry's shared question in what's specific to *that* paper2 section (e.g., if one paper2 section is about observed behavior and the other is about self-reported survey ratings, the two shared questions should reflect that difference — "how did participants behave/use it" vs. "how did participants rate/self-report their experience" — not two near-identical phrasings of "how did participants experience the system").
  - This is the scenario where question-only matching is most lossy, since a single compressed question rarely preserves enough of the original section's internal structure to split cleanly — do this carefully rather than mechanically, and don't be afraid to leave a sub-role uncovered (rather than force-fitting it) if nothing in paper2 genuinely addresses it.
- **There is no subsection fallback available here.** Unlike `directional-section-mapping`, which can drop down into a paper's subsections when no top-level section fits, this skill only has the top-level questions it was given — if nothing in `paper2`'s question list addresses paper1's role, the honest answer is `null`, not a forced pick of the least-bad option.
- **Use `null` only when no paper2 question is genuinely trying to answer a similar underlying question.** Don't default to null just because no paper2 question is a close paraphrase — a paper2 section whose question is worded completely differently but is clearly asking about the same role (e.g., both are "what motivated this design?" in substance) is a real match.

Each entry needs these fields:

| Field | Description |
|---|---|
| `paper1_section_name` | Section name/title from paper1 |
| `paper1_section_number` | Section number from paper1 (as a string) |
| `paper2_section_name` | Closest corresponding section name in paper2, or `null` |
| `paper2_section_number` | Corresponding section number in paper2, or `null` |
| `basis` | Why these two *questions* indicate the same underlying role — quote or paraphrase both questions and explain the alignment (or, for a null match, explain why no paper2 question addresses this role, or that no question was available to compare). Since you have no fuller section text here, the basis must be argued from the questions alone. |
| `question_the_sections_both_answer` | One question both sections are fundamentally trying to answer, synthesized from paper1's and paper2's own questions. Keep it short and genuinely open — don't pack the answer into it via em-dashes or parentheticals (see the common mistake below). |

### Output

Save as a JSON array of these objects. Default filename: `p1-p2-section-mapping-by-questions-only.json`. If running this a second time in the reverse direction, use a distinct name like `p2-p1-section-mapping-by-questions-only.json` so it doesn't overwrite the first pass.

Briefly tell the user how many sections got a matched, and how many got `null` — and for each `null`, whether it was because no paper2 question fit, or because the question itself was unavailable (null input). Flag anything that stands out.

### Output schema (strict)

ALWAYS use this exact shape for every entry — exactly these six keys, no additions, no renaming, no reordering:

```json
{
  "paper1_section_name": "string",
  "paper1_section_number": "string or null",
  "paper2_section_name": "string, or null if no match",
  "paper2_section_number": "string or null, matches paper2_section_name's null-ness",
  "basis": "string, explains the match or why it's null — never null or empty itself",
  "question_the_sections_both_answer": "string, or null only if paper2_section_name is null"
}
```

The file itself is a JSON array of these objects, e.g.:

```json
[
  {
    "paper1_section_name": "Introduction",
    "paper1_section_number": "1",
    "paper2_section_name": "Introduction",
    "paper2_section_number": "1",
    "basis": "Both questions ask what gap motivates the system and what it contributes — same underlying role.",
    "question_the_sections_both_answer": "What gap in prior work motivates this system, and what does it contribute?"
  },
  {
    "paper1_section_name": "Formative Interview Study",
    "paper1_section_number": "3",
    "paper2_section_name": null,
    "paper2_section_number": null,
    "basis": "No paper2 question addresses formative fieldwork of any kind — this paper has no comparable study.",
    "question_the_sections_both_answer": null
  }
]
```

`paper2_section_name` and `paper2_section_number` are always both `null` together or both non-null together — never a name with a null number or vice versa. `question_the_sections_both_answer` is `null` only when `paper2_section_name` is `null`; a real match always gets a real shared question. `basis` is always a non-empty string, even for a null match — it must say *why* (no candidate question fit, vs. the input question itself was unavailable). Don't add extra fields — no `confidence`, no `paragraphs`, nothing beyond these six keys.

## Common mistakes to avoid

- **Opening a PDF, or asking for one.** This skill's entire reason to exist is to skip that cost — if the two input files don't have enough information to decide a match, say so and mark it `null` rather than going to find more.
- **Matching on shared vocabulary/topic instead of shared role.** Two questions can share keywords while asking about completely different jobs, and two questions can be worded totally differently while asking about the same job. Compare what each question is actually trying to establish, not its surface wording.
- **Combining multi-section correspondences into one label instead of splitting them.** Same rule as `directional-section-mapping`, same reason: breaks exact-match bidirectional comparison downstream.
- **Splitting a section but dropping part of its original question's scope, or making the split entries' shared questions nearly identical to each other.** A split is only useful if (a) it collectively still covers what paper1's original question was asking, and (b) each entry's `question_the_sections_both_answer` is anchored in what's actually distinctive about that particular paper2 target — otherwise the split adds noise instead of precision.
- **Treating a `null` question_this_section_answers as if it were a real (if minimal) question.** A `null` input means "no basis to match on," not "weak but usable basis" — exclude it as a match candidate, and if it's the paper1 side, say plainly that no question was available rather than forcing something.
- **Writing a long, compound `question_the_sections_both_answer` that answers itself via em-dash asides or parentheticals.** Same rule as the skills that produced the input questions — see [[feedback-questions-should-not-self-answer]]. Keep it short enough to ask out loud.
- **Treating this skill as if it already does the bidirectional check.** It doesn't, on purpose — same as its full-content sibling. Point users who want confirmed/bidirectional matches to `paper-section-alignment`, or run this skill twice.
- **Leaving `paper2_section_number` non-null when `paper2_section_name` is null, or vice versa, or writing an empty string instead of a real explanation in `basis`.** See "Output schema (strict)" above — these two fields' null-ness must always match each other, and `basis` is never empty.

