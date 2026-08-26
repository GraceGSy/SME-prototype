---
name: "section-pairings-with-paragraphs-and-questions"
description: "Given a two-paper common-section-structure.json and leftover-section-differences.json (from common-section-structure-by-paragraphs-and-questions), plus each paper's own sections-with-paragraphs-and-questions.json, merges them into one file per section PAIRING carrying both papers' paragraphs. Use whenever the user wants a pairwise analog of the single-paper sections-with-paragraphs-and-questions.json -- one entry per section correspondence (common-structure, alignable-diff, or non-alignable-diff) with the actual paragraph text from both papers attached, not just section names/numbers. Trigger for \"merge the common structure and leftovers with the actual paragraphs,\" \"give me paragraphs for each section pairing,\" or \"build the two-paper version of sections-with-paragraphs-and-questions.\" PDF-free -- reads only the four JSON inputs already produced by earlier skills in this family."
---

# Section Pairings With Paragraphs And Questions

## What this is (and isn't)

Merges the outputs of `common-section-structure-by-paragraphs-and-questions` (the confirmed `common-section-structure.json` and the tagged `leftover-section-differences.json`) with each paper's own `sections-with-paragraphs-and-questions.json` (from `orchestrator-extract-sections-paragraphs-and-questions` or `annotate-section-questions-given-paragraphs`), producing **one entry per section pairing** — the two-paper analog of the single-paper `sections-with-paragraphs-and-questions.json` file, but keyed by section *correspondence* rather than by single-paper section.

This skill does no new matching, comparison, or classification of its own. Every pairing it outputs — which sections go together, whether they're common-structure/alignable-diff/non-alignable-diff, and the basis/question text — comes straight from the two input files it's given. Its only job is to reattach the actual paragraph text (which `common-section-structure.json`/`leftover-section-differences.json` don't carry) by looking each section up in its own paper's extracted file.

Not a PDF-reading skill — nothing here opens a PDF. If either paper's own `sections-with-paragraphs-and-questions.json` doesn't exist yet, run `orchestrator-extract-sections-paragraphs-and-questions` on that paper's PDF first.

**The script in this skill's Workflow is given verbatim and must be copied byte-for-byte, never authored or modified.** Wherever the instructions say "write the script," that means transcribe the exact code shown into a file — not compose a variant, not add a flag, not adjust behavior for a specific case. If the script's documented behavior seems wrong for what you're trying to do, that's a stop-and-ask-the-user moment, not a reason to write custom logic (see `extract-paragraphs-as-pseudo-sections`'s "Stage 0 is strictly mechanical" section for the real incident this rule generalizes from).

## Inputs

Four files:

1. `{paperA-name}-{paperB-name}-common-section-structure.json` — from `common-section-structure-by-paragraphs-and-questions`.
2. `{paperA-name}-{paperB-name}-leftover-section-differences.json` — from the same skill.
3. `{paperA-name}`'s own `sections-with-paragraphs-and-questions.json`.
4. `{paperB-name}`'s own `sections-with-paragraphs-and-questions.json`.

`{paperA-name}`/`{paperB-name}` must be the literal PDF filenames (minus `.pdf`) already used as the prefix on files 1 and 2 — don't guess or reformat.

## Workflow

### Step 1: Copy the script into a local file

Copy the script below byte-for-byte into a local file (e.g. `build_section_pairings.py`) — this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant.

```python
#!/usr/bin/env python3
"""
Merges the confirmed common-section-structure.json and the leftover-section-differences.json
outputs of common-section-structure-by-paragraphs-and-questions with each paper's own
sections-with-paragraphs-and-questions.json, producing one entry per section PAIRING (not
per single-paper section) with both papers' paragraphs attached -- the pairwise analog of
the single-paper sections-with-paragraphs-and-questions.json file.

Every entry from both source files becomes one output entry: common-structure matches keep
both their independently-derived basis/question pairs (question_p1_p2/question_p2_p1);
leftover entries populate only the one direction they actually came from, leaving the other
pair null. paperA_paragraphs/paperB_paragraphs are pulled from each paper's own extracted
file by matching section number (falling back to exact section name for unnumbered
sections, same join-key rule used throughout this family) -- [] when that side has no
section at all.

Usage:
    python3 build_section_pairings.py common-section-structure.json leftover-section-differences.json paperA-sections-with-paragraphs-and-questions.json paperB-sections-with-paragraphs-and-questions.json [output_path]

If output_path isn't given, writes to the same directory as the common-section-structure
file, named <prefix>-sections-with-paragraphs-and-questions.json, where <prefix> is that
file's name with "-common-section-structure.json" stripped (or its full stem if that
suffix isn't present).
"""

import json
import sys
from pathlib import Path


def norm(value):
    """Normalize a value for comparison: None/empty-ish stays None, else stripped string."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def side_key(number, name):
    """Join key for one section: number when numbered, else exact name. None if neither."""
    num = norm(number)
    if num is not None:
        return ("num", num)
    name_norm = norm(name)
    return ("name", name_norm) if name_norm is not None else None


def build_paragraph_lookup(paper_sections: list) -> dict:
    lookup = {}
    for e in paper_sections:
        key = side_key(e.get("section_number"), e.get("section_name"))
        if key is not None:
            lookup[key] = e.get("paragraphs", [])
    return lookup


def paragraphs_for(lookup: dict, number, name, warnings: list, paper_label: str):
    """Returns the paragraphs array for this section, or [] if the side has no section at
    all (name is null). If the side DOES name a section but it can't be found in the
    per-paper lookup, that's a real data-integrity problem -- return [] but record a
    warning rather than silently pretending it's a legitimately-empty section."""
    if norm(name) is None:
        return []
    key = side_key(number, name)
    if key is None:
        return []
    if key not in lookup:
        warnings.append(f"{paper_label} section not found in its own extracted file: {name!r} ({number!r})")
        return []
    return lookup[key]


def from_common_entry(e: dict, paperA_lookup: dict, paperB_lookup: dict, warnings: list) -> dict:
    return {
        "paperA_section_name": e.get("paperA_section_name"),
        "paperA_section_number": e.get("paperA_section_number"),
        "paperA_paragraphs": paragraphs_for(paperA_lookup, e.get("paperA_section_number"), e.get("paperA_section_name"), warnings, "paperA"),
        "paperB_section_name": e.get("paperB_section_name"),
        "paperB_section_number": e.get("paperB_section_number"),
        "paperB_paragraphs": paragraphs_for(paperB_lookup, e.get("paperB_section_number"), e.get("paperB_section_name"), warnings, "paperB"),
        "basis_p1_p2": e.get("basis_p1_p2"),
        "question_p1_p2": e.get("question_p1_p2"),
        "basis_p2_p1": e.get("basis_p2_p1"),
        "question_p2_p1": e.get("question_p2_p1"),
        "pairing_status": "common-structure",
    }


def pairing_status_from_diff_type(diff_type, e):
    """Maps leftover-section-differences.json's diff_type onto this skill's own
    pairing_status vocabulary, appending "-diff" so the value signals it came from the
    leftover (diff) file rather than the common-structure file."""
    if diff_type == "alignable":
        return "alignable-diff"
    if diff_type == "non-alignable":
        return "non-alignable-diff"
    raise ValueError(f"unknown diff_type {diff_type!r} in leftover entry: {e!r}")


def from_leftover_entry(e: dict, paperA_lookup: dict, paperB_lookup: dict, warnings: list) -> dict:
    direction = e.get("direction")
    basis = e.get("basis")
    question = e.get("question_the_sections_both_answer")
    if direction == "p1-p2":
        basis_p1_p2, question_p1_p2 = basis, question
        basis_p2_p1, question_p2_p1 = None, None
    elif direction == "p2-p1":
        basis_p1_p2, question_p1_p2 = None, None
        basis_p2_p1, question_p2_p1 = basis, question
    else:
        raise ValueError(f"unknown direction {direction!r} in leftover entry: {e!r}")

    return {
        "paperA_section_name": e.get("paperA_section_name"),
        "paperA_section_number": e.get("paperA_section_number"),
        "paperA_paragraphs": paragraphs_for(paperA_lookup, e.get("paperA_section_number"), e.get("paperA_section_name"), warnings, "paperA"),
        "paperB_section_name": e.get("paperB_section_name"),
        "paperB_section_number": e.get("paperB_section_number"),
        "paperB_paragraphs": paragraphs_for(paperB_lookup, e.get("paperB_section_number"), e.get("paperB_section_name"), warnings, "paperB"),
        "basis_p1_p2": basis_p1_p2,
        "question_p1_p2": question_p1_p2,
        "basis_p2_p1": basis_p2_p1,
        "question_p2_p1": question_p2_p1,
        "pairing_status": pairing_status_from_diff_type(e.get("diff_type"), e),
    }


def main() -> None:
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    common_path = Path(sys.argv[1])
    leftover_path = Path(sys.argv[2])
    paperA_path = Path(sys.argv[3])
    paperB_path = Path(sys.argv[4])

    with open(common_path, "r", encoding="utf-8") as f:
        common = json.load(f)
    with open(leftover_path, "r", encoding="utf-8") as f:
        leftover = json.load(f)
    with open(paperA_path, "r", encoding="utf-8") as f:
        paperA_sections = json.load(f)
    with open(paperB_path, "r", encoding="utf-8") as f:
        paperB_sections = json.load(f)

    paperA_lookup = build_paragraph_lookup(paperA_sections)
    paperB_lookup = build_paragraph_lookup(paperB_sections)

    warnings = []
    output = [from_common_entry(e, paperA_lookup, paperB_lookup, warnings) for e in common]
    output += [from_leftover_entry(e, paperA_lookup, paperB_lookup, warnings) for e in leftover]

    def sort_key(e):
        status_order = {"common-structure": 0, "alignable-diff": 1, "non-alignable-diff": 2}
        n = e["paperA_section_number"]
        return (status_order.get(e["pairing_status"], 3), n is None, n if n is not None else "")

    output.sort(key=sort_key)

    if len(sys.argv) >= 6:
        output_path = Path(sys.argv[5])
    else:
        stem = common_path.name
        suffix = "-common-section-structure.json"
        prefix = stem[: -len(suffix)] if stem.endswith(suffix) else common_path.stem
        output_path = common_path.parent / f"{prefix}-sections-with-paragraphs-and-questions.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Common-structure pairings: {len(common)}")
    print(f"Leftover pairings: {len(leftover)}")
    print(f"Total entries written: {len(output)}")
    if warnings:
        print(f"\n{len(warnings)} WARNING(S) -- section named in the pairing file but not found in its own per-paper extracted file:")
        for w in warnings:
            print(f"  - {w}")
    print(f"\nWrote {output_path}")


if __name__ == "__main__":
    main()
```

### Step 2: Run it

```
python3 build_section_pairings.py <common-section-structure.json> <leftover-section-differences.json> <paperA's own sections-with-paragraphs-and-questions.json> <paperB's own sections-with-paragraphs-and-questions.json>
```

### Step 3: Check for warnings

If the script prints any "WARNING(S)" lines, a section named in the common-structure or leftover file couldn't be found in that paper's own extracted file — this is a real data-integrity gap (e.g. mismatched paper prefix, stale intermediate file, or a section number/name that changed between pipeline runs), not something to silently accept. Investigate before handing the output to the user; don't just note the warning and move on.

## Output

`{paperA-name}-{paperB-name}-sections-with-paragraphs-and-questions.json` — one entry per section pairing, sorted common-structure first, then alignable-diff, then non-alignable-diff (each group ordered by paperA section number where present).

### Output schema (strict — no extra fields)

```json
[
  {
    "paperA_section_name": "string or null",
    "paperA_section_number": "string or null",
    "paperA_paragraphs": [
      {"paragraph_number": 0, "text": "..."}
    ],
    "paperB_section_name": "string or null",
    "paperB_section_number": "string or null",
    "paperB_paragraphs": [
      {"paragraph_number": 0, "text": "..."}
    ],
    "basis_p1_p2": "string or null",
    "question_p1_p2": "string or null",
    "basis_p2_p1": "string or null",
    "question_p2_p1": "string or null",
    "pairing_status": "common-structure"
  }
]
```

- `pairing_status` is one of three literal values: `"common-structure"`, `"alignable-diff"`, `"non-alignable-diff"`.
  - `"common-structure"` is hardcoded for every entry sourced from `common-section-structure.json` — a pairing both directional mapping passes independently confirmed.
  - `"alignable-diff"` / `"non-alignable-diff"` are for entries sourced from `leftover-section-differences.json`, derived from that entry's own `diff_type` field (`"alignable"` / `"non-alignable"`) with `"-diff"` appended — the suffix signals the value came from the *leftover/diff* file, not the confirmed-structure file, since `"alignable"` alone would otherwise read as ambiguous between "this section-name pair is alignable" and "this pairing is a diff, of the alignable kind."
    - `"alignable-diff"`: both papers name a section, but it wasn't bidirectionally confirmed.
    - `"non-alignable-diff"`: at least one paper has no section at all on that side.
  - This skill performs no independent judgment for this field — it's a straight hardcode/rename from the source entry's origin file and (for leftovers) its `diff_type`. Note the field name itself has changed from `diff_type` (leftover file) to `pairing_status` (this file) — don't expect the raw `diff_type` string to appear unmodified.
- `paperA_paragraphs`/`paperB_paragraphs` are `[]` when that side has no section at all (name is null, i.e. a non-alignable-diff entry with nothing on that side) — this is the normal, expected case, not an error.
- **Both** basis/question pairs (`_p1_p2` and `_p2_p1`) are kept side by side rather than collapsed into one field — explicit user choice, same convention as `common-section-structure-by-paragraphs-and-questions`. For common-structure entries both pairs are populated (two independently-derived justifications). For leftover-diff entries, only the pair matching that entry's `direction` field is populated; the other pair is `null`.

## Common mistakes to avoid

- **Re-deriving which sections pair together, or what `pairing_status` should be, instead of taking it verbatim/derived from the two input files.** This skill's only job is reattaching paragraphs — it does not re-judge matches.
- **Copying `diff_type`'s raw values (`"alignable"`/`"non-alignable"`) straight into `pairing_status` without the `-diff` suffix.** The literal values are `"alignable-diff"` and `"non-alignable-diff"` — always append `-diff` when mapping from the leftover file's `diff_type` field.
- **Using `"confirmed"` instead of `"common-structure"` for the hardcoded value.** The literal string is `"common-structure"` — matches the source filename's own terminology (`common-section-structure.json`) rather than a separate vocabulary.
- **Treating `paperA_paragraphs: []`/`paperB_paragraphs: []` as an error when the corresponding section name is null.** That's the correct, expected output for a non-alignable-diff entry with nothing on that side.
- **Silently swallowing a lookup-miss warning for a *named* section.** A named section with no match in its own paper's extracted file signals a real mismatch (stale file, wrong prefix, renumbering between runs) — surface it, don't bury it in a WARNING line nobody reads.
- **Collapsing `basis_p1_p2`/`basis_p2_p1` (or the two question fields) into a single field.** Keep both, per the explicit schema decision above.
- **Guessing `{paperA-name}`/`{paperB-name}` instead of reading them off the input filenames.** Same literal-filename rule as every other skill in this family.
- **Opening a PDF at any point.** Everything needed is already in the four JSON inputs.
- **Writing a custom variant of the bundled script instead of copying it verbatim, or "fixing" its behavior for a specific pairing or paper.** The merge logic is fixed and mechanical — if it produces something that looks wrong, that's a signal to check the underlying data (the common-structure/leftover files, each paper's own extracted file), not to rewrite the script.
