---
name: "normalize-section-mapping-both-directions"
description: "Given the combined JSON output of \"section-mapping-by-paragraphs-and-questions-both-directions\" (an object with \"p1-p2\" and \"p2-p1\" keys, where paper1_*/paper2_* field identity is reversed between the two arrays), writes a normalized copy where every entry in both arrays uses the same, consistent paperA_*/paperB_* field names -- paperA always means fileA, paperB always means fileB, regardless of which array the entry came from. Saves {input-filename}-normalized.json. Use whenever the user wants to fix, clean up, or normalize the paper1/paper2 identity swap in a both-directions section mapping, wants a version of that output where fields mean the same thing in both arrays, or explicitly mentions the \"asymmetry\" between p1-p2 and p2-p1. This is a pure field-rename step -- no new matching, no PDF access, no filtering of entries."
---

## What this is (and isn't)

`section-mapping-by-paragraphs-and-questions-both-directions` produces a combined JSON with `p1-p2` and `p2-p1` arrays, but the field names inside them don't mean the same thing in both arrays: in `p1-p2`, `paper1_*` describes `fileA` and `paper2_*` describes `fileB`; in `p2-p1`, it's reversed -- `paper1_*` describes `fileB` and `paper2_*` describes `fileA` (because the sub-skill was run a second time with the two files swapped). Anyone reading both arrays without tracking that reversal can silently misread or misjoin the data.

This skill fixes exactly that, and nothing else: it renames every entry's fields into consistent `paperA_*`/`paperB_*` terms, swapping `p2-p1`'s fields back into the right identity along the way. It does not run any new matching, does not filter, merge, or drop any entries, does not open a PDF, and does not compute which pairings are bidirectionally confirmed -- for that, see `common-section-structure-by-paragraphs-and-questions` (which does its own internal version of this same normalization, but only exposes the confirmed subset, not the full renamed arrays).

**The script in this skill's Workflow is given verbatim and must be copied byte-for-byte, never authored or modified.** Wherever the instructions say "write the script," that means transcribe the exact code shown into a file -- not compose a variant, not add a flag, not adjust behavior for a specific case. If the script's documented behavior seems wrong for what you're trying to do, that's a stop-and-ask-the-user moment, not a reason to write custom logic (see `extract-paragraphs-as-pseudo-sections`'s "Stage 0 is strictly mechanical" section for the real incident this rule generalizes from).

## Inputs

One file: the combined output of `section-mapping-by-paragraphs-and-questions-both-directions`, named `{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions.json` -- a JSON object with exactly two keys, `p1-p2` and `p2-p1`, each a plain array of six-field entries (`paper1_section_name`, `paper1_section_number`, `paper2_section_name`, `paper2_section_number`, `basis`, `question_the_sections_both_answer`).

If the user only has the two separate intermediate files (`...-p1-p2-...json` and `...-p2-p1-...json`) rather than the combined file, ask whether they want you to assemble them into the combined shape first (`{"p1-p2": [...], "p2-p1": [...]}`) before running this skill, rather than guessing.

## Workflow

### Step 1: Confirm the input is the combined file

Check it has both a `p1-p2` key and a `p2-p1` key, each holding a plain array. If either is missing, this isn't the right input -- see "Inputs" above.

### Step 2: Run the normalization script

Don't do this rename by hand -- it's easy to get the swap direction backwards for exactly one of the two arrays (this is precisely the kind of identity-tracking mistake the skill exists to eliminate), and a script won't flip the wrong one.

Copy the script below byte-for-byte into a local file (e.g. `normalize_paper_identity.py`, in the same directory as the input file) -- this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant. Then run it:

```bash
python3 normalize_paper_identity.py {paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions.json
```

```python
#!/usr/bin/env python3
"""
Reads the combined output of section-mapping-by-paragraphs-and-questions-both-directions
(a JSON object with "p1-p2" and "p2-p1" keys, each a plain array of six-field
mapping entries using paper1_*/paper2_* field names) and writes a normalized
copy where every entry, in both arrays, uses the SAME field identity:
paperA_* always means fileA, paperB_* always means fileB.

The asymmetry being fixed: in the source "p1-p2" array, paper1_* describes
fileA and paper2_* describes fileB. In the source "p2-p1" array, it's
reversed -- paper1_* describes fileB and paper2_* describes fileA, because
the sub-skill was run a second time with fileB and fileA swapped. Anyone
reading both arrays without knowing this can silently misjoin or misread
data. This script performs the one mechanical fix: rename (and for p2-p1,
swap) every entry's fields into paperA_*/paperB_* terms, so downstream
consumers never need to remember which array reversed identity.

basis and question_the_sections_both_answer are carried over unchanged --
this script only renames/reassigns paper1_*/paper2_* to paperA_*/paperB_*,
it does not alter, merge, or drop any entry.

Usage:
    python3 normalize_paper_identity.py combined-section-mapping.json [output_path]

If output_path isn't given, writes to the same directory as the input, using
the input filename with "-normalized" inserted before the ".json" extension.
"""

import json
import sys
from pathlib import Path


REQUIRED_KEYS = ("p1-p2", "p2-p1")


def normalize_entry(entry: dict, direction: str) -> dict:
    """Rename one raw entry's paper1_*/paper2_* fields into paperA_*/paperB_* terms.

    direction == "p1-p2": paper1_* -> paperA_*, paper2_* -> paperB_* (rename only, no swap).
    direction == "p2-p1": paper1_* -> paperB_*, paper2_* -> paperA_* (rename AND swap).
    """
    if direction == "p1-p2":
        a_name, a_num = entry.get("paper1_section_name"), entry.get("paper1_section_number")
        b_name, b_num = entry.get("paper2_section_name"), entry.get("paper2_section_number")
    elif direction == "p2-p1":
        b_name, b_num = entry.get("paper1_section_name"), entry.get("paper1_section_number")
        a_name, a_num = entry.get("paper2_section_name"), entry.get("paper2_section_number")
    else:
        raise ValueError(f"unknown direction {direction!r}")

    return {
        "paperA_section_name": a_name,
        "paperA_section_number": a_num,
        "paperB_section_name": b_name,
        "paperB_section_number": b_num,
        "basis": entry.get("basis"),
        "question_the_sections_both_answer": entry.get("question_the_sections_both_answer"),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    with open(input_path, "r", encoding="utf-8") as f:
        combined = json.load(f)

    if not isinstance(combined, dict) or any(k not in combined for k in REQUIRED_KEYS):
        raise ValueError(f"{input_path} must be a JSON object with 'p1-p2' and 'p2-p1' keys")

    normalized = {
        "p1-p2": [normalize_entry(e, "p1-p2") for e in combined["p1-p2"]],
        "p2-p1": [normalize_entry(e, "p2-p1") for e in combined["p2-p1"]],
    }

    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    else:
        stem = input_path.stem  # filename without .json
        output_path = input_path.parent / f"{stem}-normalized.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"p1-p2 entries: {len(normalized['p1-p2'])}")
    print(f"p2-p1 entries: {len(normalized['p2-p1'])}")
    print("Every entry in both arrays now uses paperA_*/paperB_* consistently (paperA = fileA, paperB = fileB).")
    print(f"\nWrote {output_path}")


if __name__ == "__main__":
    main()
```

The script derives the output filename from the input filename automatically (inserting `-normalized` before `.json`) -- pass an explicit output path as a second argument only if you want it somewhere else.

### Step 3: Spot-check before reporting

Pick one entry from `p2-p1` where the two papers' section names clearly differ (not a same-titled pairing like Abstract/Abstract, which won't reveal a swap bug either way), and confirm `paperA_section_name` matches what `fileA` actually calls that section, not `fileB`. This is a cheap, high-value sanity check -- catching a reversed swap here is much cheaper than a downstream skill silently misjoining on it later.

## Output

One file, `{input-filename-without-.json}-normalized.json`, saved in the same directory as the input unless the user specifies otherwise -- e.g. `abstractexplorer-corpusstudio-section-mapping-by-paragraphs-and-questions-normalized.json`. Same overall shape as the input (an object with `p1-p2` and `p2-p1` keys, each a plain array), same entry count in each array as the input -- only the field names (and, for `p2-p1` only, which raw field maps to which normalized field) change.

### Output schema (strict)

```json
{
  "p1-p2": [
    {
      "paperA_section_name": "string",
      "paperA_section_number": "string or null",
      "paperB_section_name": "string, or null if no match",
      "paperB_section_number": "string or null, matches paperB_section_name's null-ness",
      "basis": "string, unchanged from the input entry",
      "question_the_sections_both_answer": "string, or null only if paperB_section_name is null, unchanged from the input entry"
    }
  ],
  "p2-p1": [
    { "...": "same six fields as above -- paperA_* still means fileA, paperB_* still means fileB, even though this array's raw source fields were reversed" }
  ]
}
```

`paperA_*` means `fileA` and `paperB_*` means `fileB` in *both* arrays now -- that's the entire point of this skill. No other fields are added (no `confidence`, no `direction` marker, nothing beyond the six listed here), and no entries are added, removed, or reordered relative to the input.

## Common mistakes to avoid

- **Renaming `p1-p2` and `p2-p1` the same way (both a straight rename, no swap for `p2-p1`).** This is the single most likely way to get this wrong, precisely because it's the "obvious" thing to do and silently produces output that still has the original bug, just with different field names. `p2-p1` needs `paper1_* -> paperB_*` and `paper2_* -> paperA_*` -- a swap, not a straight rename. See the script's `normalize_entry` function.
- **Doing this rename by hand across a large array instead of running the script.** Easy to get right on the first few entries and then slip after a page break or context switch -- run the script.
- **Altering `basis` or `question_the_sections_both_answer` text to "read better" after the rename.** This skill only renames fields; the content of every entry must stay byte-for-byte identical to the input.
- **Dropping, merging, splitting, or reordering entries.** The output must have exactly the same entries, in the same order, as the input -- this is a rename, not a re-derivation. (For confirmed-match filtering, that's a different skill: `common-section-structure-by-paragraphs-and-questions`.)
- **Overwriting the input file instead of writing a new `-normalized.json` file.** Keep both -- the caller may still want the original combined file for other downstream skills expecting the original field names.
- **Writing a custom variant of the script instead of the one shown, or "fixing" its behavior for a specific pair of papers.** The rename/swap logic is fixed and mechanical -- if it produces something that looks wrong, that's a signal to check the input file, not to rewrite the script.
