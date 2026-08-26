---
name: "annotate-section-questions-given-paragraphs"
description: "Given a sections-with-paragraph-content.json file (from \"extract-section-paragraphs\"), composes a \"question_this_section_answers\" field for each section entry purely from its already-extracted paragraphs field, without opening or re-reading the source PDF. A hard Step 4 validator blocks completion until every entry has a real question or is verified legitimately empty (paragraphs == []). Saves two output files — sections-with-paragraphs-and-questions.json (full, paragraphs included) and sections-with-questions-only.json (same entries, paragraphs stripped out). Use whenever the user wants section-level role questions added but already has paragraph-level content extracted, wants to avoid re-parsing the PDF, or explicitly says \"based on the paragraphs already extracted\" / \"without going back to the PDF.\" If the user only has sections.json (no paragraphs field) or hasn't extracted paragraphs yet, use \"annotate-section-questions\" instead, which reads the PDF directly."
---

# Annotate Section Questions (Given Paragraphs)

## What this is (and isn't)

This is the same idea as `annotate-section-questions` — one role-based `question_this_section_answers` field per section, describing the job that section does in the paper's argument — but computed entirely from an already-extracted `sections-with-paragraph-content.json` file (from `extract-section-paragraphs`), never by opening the PDF. If the PDF isn't available, or re-reading it would be wasteful because the paragraph text has already been pulled out, use this skill instead of its sibling.

If the input file doesn't have a `paragraphs` field on its entries (i.e. it's a plain `sections.json`, not `sections-with-paragraph-content.json`), this is the wrong skill — use `annotate-section-questions` instead, which is built to read the PDF directly.

**Why this skill now has a hard completeness gate (Step 4).** This skill's own output — `question_this_section_answers` — is the single-paper foundation every downstream matching skill in this project reads: `directional-section-mapping-by-paragraphs-and-questions` and all six of its papernplus1/2/3-family siblings treat a section's own composed question as first-class evidence for role correspondence, not just a hint. A real 5-paper corpus run surfaced that this skill's own composition step (Step 2) can be silently skipped or left incomplete for a whole file with nothing catching it — the gap only became visible several matching stages later, when a downstream skill's output turned out to have relied on paragraph content alone for sections that should have had a question available. This step exists to catch that here, at the source, every run — mirroring the same hard-gate pattern already used by the papernplus1/2/3 common-section-structure family's own Step 4.

**Any script in this skill's Workflow is given verbatim and must be copied byte-for-byte, never authored or modified.** Wherever a step says "write the script," that means transcribe the exact code shown into a file — not compose a variant, not add a flag, not adjust behavior for a specific case. If a script's documented behavior seems wrong for what you're trying to do, that's a stop-and-ask-the-user moment, not a reason to write custom logic (see `extract-paragraphs-as-pseudo-sections`'s "Stage 0 is strictly mechanical" section for the real incident this rule generalizes from).

## Inputs

A single `sections-with-paragraph-content.json` file: a JSON array of section objects, each with at least `section_name`, `section_number`, and a `paragraphs` array (each paragraph an object with `paragraph_number` and `text`), in the order the sections appear in the paper.

No PDF is needed or should be opened for this skill — that's the entire point of it. If you find yourself reaching for `pdftotext` or the original PDF file, stop; everything required is already in the input JSON.

## Workflow

### Step 1: Read every paragraph in each section

For each entry in the input array, read the full `text` of every paragraph in its `paragraphs` array — not just the first one or two. A section's `paragraphs` array is the complete substitute for "reading the section" here; there is no PDF to fall back on for anything a thin paragraph list doesn't capture.

### Step 2: Compose the question each section answers

Using only the paragraph text just read, write one question that this section exists to answer in the paper's argument — the same role-based framing used throughout this project: ask "what job is this section doing — what does the reader need answered before moving to the next part of the paper?" not "what topic does this section cover?"

- Frame the question around the section's function in the paper's arc, not a restatement of its title or a content summary.
- **The question must span all of the section's paragraphs, not just the first or most prominent one.** If the paragraphs cover several related jobs (e.g. separate paragraphs for different system components, or different sub-studies), find the broader question that covers all of them, the way `annotate-section-questions` requires spanning all subsections. If the paragraphs are different enough that no single question honestly covers all of them, say so explicitly in the question rather than silently narrowing it.
- **Watch for a single connecting verb-frame that's topically complete but type-narrow.** A section can name every sub-topic and still silently exclude a different kind of content coexisting with it — e.g. a qualitative-results section built from interview coding often reports both what participants did (behavior/usage) and how they felt about it (confidence, satisfaction, perception), sometimes in the same paragraph. A question framed only as "what did analysis reveal about how participants used X" can list every feature and still exclude the self-reported half of those same paragraphs. Before finalizing, check each paragraph for what TYPE of finding it reports (behavior vs. attitude/experience vs. both), not just which topic it belongs to.
- **Keep the question short and genuinely open — don't embed the answer inside the question itself.** A question padded with an em-dash aside or parenthetical listing out specifics has stopped being a question; it's an answer wearing a question mark. For example, this is too wordy and self-answering: "What problem does existing corpus-reading tooling fail to solve—the cost of serial reading and the information loss inherent in prior lossy representations—and what novel, minimally lossy, Structural-Mapping-Theory-informed approach does AbstractExplorer contribute and validate through its three studies to address that gap?" (the em-dash clause answers the first half, and "novel, minimally lossy, Structural-Mapping-Theory-informed" answers the second half, before the question is even finished). Prefer something short and direct instead: "What gap in existing corpus-reading approaches motivates AbstractExplorer, and what approach does it contribute to address it?" If you're tempted to reach for a dash, colon, or parenthetical full of specifics, that detail belongs in your own understanding of the section, not in the question text — a genuine question doesn't give away its own answer.
- **If a section's `paragraphs` array is empty** (this happens for sections like References, per `extract-section-paragraphs`'s own rules, where there's no real prose to extract), there is no content to read for that entry. Set `question_this_section_answers` to `null` rather than guessing a question from `section_name`/`section_number` alone — this skill only composes questions from actual paragraph content, and a title-based guess would misrepresent itself as content-derived. Flag in your summary to the user which entries got `null` and why.
- Even thin sections with only one or two short paragraphs (Acknowledgments, Preface) get a real, honest question rather than being skipped.
- This question should be usable on its own, without the reader having the section's content in front of them — write it so it stands alone.

### Step 3: Build the output

For each section entry, preserve every existing field unchanged — including the full `paragraphs` array exactly as given, with no edits to paragraph text or numbering — and add one new field:

| Field | Description |
|---|---|
| `question_this_section_answers` | One question this section exists to answer, framed around its role in the paper's argument, composed only from the section's `paragraphs` (see Step 2) — or `null` if the section's `paragraphs` array is empty |

Save both output files now (see "Output" below) before moving to Step 4 — the validator reads the file you just wrote, not your in-progress reasoning.

### Step 4: Validate completeness (hard gate — do not proceed until this passes)

Step 2 is a reasoning step performed once per section across a whole file, and steps like that are the ones that get skipped or left half-done, especially under time pressure or across a long section list — a real corpus run of this family produced a file where several sections were left with `question_this_section_answers: null` despite having substantial real paragraph content, and the gap wasn't caught until multiple downstream matching stages later, when a skill that treats this field as first-class evidence turned out to have been given nothing for those sections. This step exists to catch that mechanically, every single run, rather than trusting that Step 2 actually finished. **Do not report this skill's output as done, and do not let any downstream skill (directional section mapping, a fold-in generation, anything) consume `sections-with-paragraphs-and-questions.json` until this step passes clean.**

Copy the script below byte-for-byte into a local file (e.g. `validate_annotate_step_complete.py`) — this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant. Then run it against the file you just wrote in Step 3:

```bash
python3 validate_annotate_step_complete.py sections-with-paragraphs-and-questions.json
```

```python
#!/usr/bin/env python3
"""
Step 4 (hard gate): validates that sections-with-paragraphs-and-questions.json satisfies
this skill's own null rule: question_this_section_answers is non-null for every entry,
UNLESS that entry's own paragraphs array is [] (the one legitimate case Step 2 allows).

Exit 0: every entry either has a real question or has genuinely empty paragraphs.
Exit 1: one or more entries have a null question despite non-empty paragraphs -- Step 2
was not actually completed for those entries. Compose a real question for each one listed,
rewrite both output files (sections-with-paragraphs-and-questions.json and
sections-with-questions-only.json), and re-run this validator.

Usage:
    python3 validate_annotate_step_complete.py sections-with-paragraphs-and-questions.json
"""
import json
import sys
from pathlib import Path


def main():
    path = Path(sys.argv[1])
    entries = json.load(open(path, encoding="utf-8"))

    violations = []
    for e in entries:
        if e.get("question_this_section_answers") is not None:
            continue
        if len(e.get("paragraphs", [])) == 0:
            continue  # legitimately empty -- allowed
        violations.append(e)

    if violations:
        print(f"BLOCKED: {len(violations)} entries have question_this_section_answers=null "
              f"despite having real paragraph content -- Step 2 is incomplete. Do not report "
              f"this skill's output as done.")
        for e in violations:
            n = len(e.get("paragraphs", []))
            print(f"  - {e.get('section_name')!r} (section_number={e.get('section_number')!r}, {n} paragraphs)")
        sys.exit(1)

    print(f"Validation passed: {len(entries)} entries all have a real question or are verified "
          f"legitimately empty (paragraphs == []). Safe to report.")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

If the script exits 0, it's safe to report this skill's output as done. **If it exits 1**, it lists every section with a missing `question_this_section_answers` that isn't legitimately empty-content — go back to Step 2, compose a real question for each one listed (grounded in that section's actual paragraphs, per Step 2's own rules), rewrite both output files (the full file and the paragraph-stripped `sections-with-questions-only.json`, which must stay in sync), and re-run this validator. Repeat until it passes clean before reporting anything as done.

## Output

Save two files, both in the same directory as the input file unless the user specifies otherwise:

1. **`sections-with-paragraphs-and-questions.json`** — the full output described above: every original field preserved, including the `paragraphs` array, plus `question_this_section_answers`.
2. **`sections-with-questions-only.json`** — the same array of section entries with the same fields, *except* the `paragraphs` array is dropped from each entry. This is a lighter-weight file for cases where only the section-level question is needed and the underlying paragraph text would just be dead weight.

Don't overwrite the input file, and don't overwrite `sections-with-questions.json` if one already exists from the sibling skill (`annotate-section-questions`) — that's a different file for a different workflow, distinct from this skill's own `sections-with-questions-only.json`.

Briefly tell the user how many sections were annotated, how many (if any) had an empty `paragraphs` array and therefore got `null` instead of a question, and confirm Step 4's validator exited 0 before reporting anything as done — if Step 4 caught and you had to fix a gap, mention that explicitly rather than folding it silently into the final counts.

### Output schema (strict)

ALWAYS use these exact shapes — no extra fields, none renamed, none reordered, in either file.

**`sections-with-paragraphs-and-questions.json`** — every field from the input preserved unchanged, plus exactly one new key (`question_this_section_answers`):

```json
{
  "section_name": "string, unchanged from the input",
  "section_number": "string or null, unchanged from the input",
  "paragraphs": [
    {"paragraph_number": 0, "text": "string, unchanged from the input"}
  ],
  "question_this_section_answers": "string, or null only if paragraphs is []"
}
```

**`sections-with-questions-only.json`** — identical entries, `paragraphs` key removed, nothing else changed:

```json
{
  "section_name": "string, unchanged from the input",
  "section_number": "string or null, unchanged from the input",
  "question_this_section_answers": "string, or null only if the source paragraphs array was []"
}
```

Full array example (showing both the `[0]` empty-paragraphs/null-question case for References and the ordinary populated case):

```json
[
  {"section_name": "Introduction", "section_number": "1", "paragraphs": [{"paragraph_number": 0, "text": "Prior work on..."}], "question_this_section_answers": "What gap in prior work motivates this system?"},
  {"section_name": "References", "section_number": null, "paragraphs": [], "question_this_section_answers": null}
]
```

`question_this_section_answers` is `null` **only** when the source `paragraphs` array is `[]` — never as a placeholder for "I couldn't think of a good question," and never omitted (it must be present as an explicit `null`, not a missing key). The two output files must contain the same entries, in the same order, with identical `question_this_section_answers` values — `sections-with-questions-only.json` is a mechanical strip of `paragraphs`, not a separately-derived result. Don't add extra fields to either file — no `confidence`, no `source`, nothing beyond what's specified here.

## Common mistakes to avoid

- **Opening the PDF or running `pdftotext`.** This skill's entire reason to exist is to avoid that cost when paragraph content has already been extracted. If the input JSON doesn't have enough information, say so rather than falling back to the source PDF.
- **Guessing the question from the section title alone when paragraph content is available.** Read every paragraph in the section before writing its question — the same rule as the PDF-reading sibling skill, just sourced from JSON instead of raw text.
- **Writing a topic/content question instead of a role question.** "What visualization techniques are discussed?" describes content; "What existing approaches does this design build on or depart from?" describes role.
- **Writing a question that only covers one paragraph or one sub-topic instead of the whole section.** A section's paragraphs collectively answer one broader question; find that question rather than picking whichever paragraph is easiest to summarize.
- **Writing a long, compound question that answers itself via em-dash asides or parentheticals.** If the question needs a dash or parenthetical to pack in specific details ("...the cost of X and the information loss of Y..."), those details are the answer, not the question — cut them and keep the question short enough to actually be asked out loud.
- **Choosing one verb-frame ("how participants used X") that names every sub-topic but excludes a different kind of content that coexists with it (how participants felt about X).** Topical breadth isn't the same as coverage — check finding type per paragraph, not just topic.
- **Writing a title-based guess for a section with an empty `paragraphs` array instead of `null`.** This skill only composes questions from actual extracted paragraph content — if there's none, the honest output is `null`, not a plausible-sounding guess based on the section name alone.
- **Losing or reordering paragraphs.** Every paragraph object from the input must appear in the output completely unchanged — this skill only adds one new field per section, it never edits existing ones.
- **Overwriting the input file or a differently-named sibling-skill output.** Always write `sections-with-paragraphs-and-questions.json` and `sections-with-questions-only.json` as new files.
- **Forgetting to write the second, paragraph-free file, or letting the two files' questions/order drift out of sync.** Both files must contain the same entries in the same order with identical `question_this_section_answers` values — `sections-with-questions-only.json` is just `sections-with-paragraphs-and-questions.json` with the `paragraphs` field stripped from each entry, not a separately-derived result.
- **Omitting `question_this_section_answers` instead of setting it to an explicit `null`, or using `null` for any reason other than an empty `paragraphs` array.** See "Output schema (strict)" above.
- **Skipping Step 4, or treating it as optional busywork.** This is the exact step whose absence let a real corpus run silently ship a file with unfilled questions that several downstream matching stages ended up relying on anyway. Run it every time, on the actual file just written, and do not report done until it exits 0.
- **Declaring Step 2 "mostly done" and moving on when only a handful of entries are missing a question.** Step 4 checks every entry, not a sample — a partial completion is exactly what it exists to catch.
- **Writing a custom variant of the Step 4 validator script instead of the one shown, or "fixing" its behavior for a specific file.** The validator's rule (real question OR verified-empty paragraphs) is fixed and mechanical — if it flags something that seems wrong, that's a signal to check the underlying data, not to rewrite the check.
