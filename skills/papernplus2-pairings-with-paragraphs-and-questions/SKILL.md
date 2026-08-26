---
name: "papernplus2-pairings-with-paragraphs-and-questions"
description: "The four-paper analog of \"papernplus1-pairings-with-paragraphs-and-questions\". Given papernplus2-common-section-structure.json and papernplus2-leftover-section-differences.json (from \"papernplus2-common-section-structure-by-paragraphs-questions\"), plus the three-paper pairing file and paperNplus2's own sections-with-paragraphs-and-questions.json, merges them into one entry per four-way pairing carrying paperA/paperB/paperNplus1/paperNplus2 paragraphs, a unified pairing_status read directly from the source (not hardcoded), split basis_papernplus2_to_pairing/basis_pairing_to_papernplus2 fields, and ancestor_questions/question_the_sections_answer carried over verbatim. Use whenever the user wants to fold a fifth (or Nth) paper into an existing four-paper section comparison and needs the four-paper \"pairing\" file with real paragraph content attached -- the required input for a papernplus3-family directional mapping. PDF-free."
---

# PaperNplus2 Pairings With Paragraphs And Questions

## What this is (and isn't)

This is the four-paper analog of `papernplus1-pairings-with-paragraphs-and-questions`, one generation further along the same pattern. That skill merges `papernplus1-common-section-structure.json`/`papernplus1-leftover-section-differences.json` with the two-paper pairing file and paperNplus1's own extracted file, producing a three-way pairing file. This skill does the same job one level up: it merges `papernplus2-common-section-structure.json`/`papernplus2-leftover-section-differences.json` (from `papernplus2-common-section-structure-by-paragraphs-questions`) — which carry paperA/paperB/paperNplus1/paperNplus2 section *names* and a composed question, but no paragraph text — with the three-paper pairing file (for paperA/paperB/paperNplus1 paragraphs) and paperNplus2's own extracted file (for paperNplus2 paragraphs), producing one entry per four-way pairing with all four sides' actual paragraph text attached.

This skill does no new matching, comparison, or classification of its own — same principle as its predecessors in this family. Every pairing it outputs comes straight from the two papernplus2-family input files; its only job is reattaching paragraph text those files don't carry, plus unifying their slightly different shapes into one consistent schema.

**Why this exists:** the output of this skill is the required "pairing" input for folding in a *fifth* paper (the papernplus3 family), the same way `papernplus1-pairings-with-paragraphs-and-questions`'s output is the required input for folding in the fourth paper. Without this merge step, a fifth paper has nothing with real paragraph content to be matched against — `papernplus2-common-section-structure.json`/`papernplus2-leftover-section-differences.json` alone only carry section names, basis text, and a question, never paragraphs.

**`pairing_status` is read directly from the source, not hardcoded — correct from the start, precedent from a real bug.** `build_papernplus1_pairings.py` originally hardcoded `pairing_status: "common-structure"` for every entry sourced from the common-structure file, discarding whatever that file's own (later corrected, 2026-08-16) `pairing_status` field actually said — a real bug, caught and fixed after the fact. This skill's script (`build_papernplus2_pairings.py`) reads `e.get("pairing_status")` for common entries from the start, since `papernplus2-common-section-structure-by-paragraphs-questions` already computes a freshly-derived, monotonic `pairing_status` per confirmed entry (`"common-structure"` only if the ancestor was already `"common-structure"`, else `"alignable-diff"`). Don't reintroduce the hardcoded-string mistake here — there's no reason to, since the correct value is already sitting on the source entry.

**No field-name collision to watch for at this generation, unlike the papernplus1-family original.** That skill's leftover input file carried a `pairing_status` field meaning something different from this skill's own output `pairing_status` (a two-paper-level status vs. a three-way one), which had to be explicitly dropped to avoid confusion. That collision no longer exists here: `papernplus2-leftover-section-differences.json`'s leftover entries carry `ancestor_pairing_status` (already renamed, 2026-08-16 fix) rather than a same-named `pairing_status` — so this skill's own `pairing_status` output has nothing ambiguous to be confused with. Leftover entries' `pairing_status` here is still derived from `diff_type` via `pairing_status_from_diff_type`, exactly as in the original — that mapping was never the bug.

`ancestor_questions` and `question_the_sections_answer` are carried over **verbatim, unchanged** — this skill does no question composition of its own, same "just reattach paragraphs" philosophy as every skill in this family that isn't itself doing role-based reasoning.

Not a PDF-reading skill — nothing here opens a PDF.

**The script in this skill's Workflow is given verbatim and must be copied byte-for-byte, never authored or modified.** Wherever the instructions say "write the script," that means transcribe the exact code shown into a file — not compose a variant, not add a flag, not adjust behavior for a specific case. If the script's documented behavior seems wrong for what you're trying to do, that's a stop-and-ask-the-user moment, not a reason to write custom logic (see `extract-paragraphs-as-pseudo-sections`'s "Stage 0 is strictly mechanical" section for the real incident this rule generalizes from).

## Inputs

Four files:

1. `{prefix}-papernplus2-common-section-structure.json` — from `papernplus2-common-section-structure-by-paragraphs-questions`.
2. `{prefix}-papernplus2-leftover-section-differences.json` — from the same skill.
3. `{paperA-name}-{paperB-name}-{paperNplus1-name}-sections-with-paragraphs-and-questions.json` — the three-paper pairing file, from `papernplus1-pairings-with-paragraphs-and-questions`. Its own entries carry `paperA_paragraphs`/`paperB_paragraphs`/`paperNplus1_paragraphs` embedded per pairing, not as flat single-paper lists — this skill's lookup logic accounts for that.
4. `{paperNplus2-name}-sections-with-paragraphs-and-questions.json` — paperNplus2's own extracted file, a flat single-paper list.

`{prefix}` is typically `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}`. All paper-name strings must be the literal PDF filenames (minus `.pdf`) already established earlier in the pipeline — don't guess or reformat.

## Workflow

### Step 1: Copy the script into a local file

Copy the script below byte-for-byte into a local file (e.g. `build_papernplus2_pairings.py`) — this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant.

```python
#!/usr/bin/env python3
"""
Merges papernplus2-common-section-structure.json + papernplus2-leftover-section-differences.json
(from papernplus2-common-section-structure-by-paragraphs-questions) with the three-paper pairing
file (for paperA_paragraphs/paperB_paragraphs/paperNplus1_paragraphs) and paperNplus2's own
sections-with-paragraphs-and-questions.json (for paperNplus2_paragraphs), producing ONE entry per
four-way pairing with all four sides' paragraphs attached -- the four-paper analog of
papernplus1-pairings-with-paragraphs-and-questions.

Unifies the common-structure and leftover files into one consistent schema, same convention as
papernplus1-pairings-with-paragraphs-and-questions: basis_papernplus2_to_pairing/basis_pairing_to_
papernplus2 are both populated for common entries; for leftover entries only the one matching that
entry's own `direction` field is populated, the other left null.

pairing_status: for COMMON entries, read directly from the source entry's own (already freshly
computed, 2026-08-16-corrected) pairing_status field -- NOT hardcoded to "common-structure". This
mirrors the fix applied to build_papernplus1_pairings.py after a real bug was caught there (that
script originally hardcoded "common-structure" on every confirmed entry, discarding whatever the
upstream fix had actually computed). Baking the correct behavior in here from the start avoids
needing the same fix applied twice more at this generation. For LEFTOVER entries, pairing_status is
still derived from diff_type via pairing_status_from_diff_type -- that mapping was never the bug.

ancestor_questions and question_the_sections_answer are carried over VERBATIM, unchanged -- this
skill does no question composition of its own.

Usage:
    python3 build_papernplus2_pairings.py <papernplus2-common-section-structure.json> <papernplus2-leftover-section-differences.json> <paperA-paperB-paperNplus1-pairing-file.json> <paperNplus2-sections-with-paragraphs-and-questions.json> [output_path]
"""

import json
import sys
from pathlib import Path


def norm(value):
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def side_key(number, name):
    num = norm(number)
    if num is not None:
        return ("num", num)
    name_norm = norm(name)
    return ("name", name_norm) if name_norm is not None else None


def build_paragraph_lookup(sections: list) -> dict:
    """For a flat single-paper sections-with-paragraphs-and-questions.json list."""
    lookup = {}
    for e in sections:
        key = side_key(e.get("section_number"), e.get("section_name"))
        if key is not None:
            lookup[key] = e.get("paragraphs", [])
    return lookup


def build_paragraph_lookup_from_pairing(pairing_entries: list, side: str) -> dict:
    """For paperA/paperB/paperNplus1, whose sections live embedded (multi-sided) inside the
    three-paper pairing file's own entries rather than as a flat single-paper list. side is
    'A', 'B', or 'Nplus1'."""
    name_field = f"paper{side}_section_name"
    num_field = f"paper{side}_section_number"
    para_field = f"paper{side}_paragraphs"
    lookup = {}
    for e in pairing_entries:
        key = side_key(e.get(num_field), e.get(name_field))
        if key is not None:
            lookup[key] = e.get(para_field, [])
    return lookup


def paragraphs_for(lookup: dict, number, name, warnings: list, label: str):
    if norm(name) is None:
        return []
    key = side_key(number, name)
    if key is None:
        return []
    if key not in lookup:
        warnings.append(f"{label} section not found in its own extracted/pairing file: {name!r} ({number!r})")
        return []
    return lookup[key]


def pairing_status_from_diff_type(diff_type, e):
    if diff_type == "alignable":
        return "alignable-diff"
    if diff_type == "non-alignable":
        return "non-alignable-diff"
    raise ValueError(f"unknown diff_type {diff_type!r} in leftover entry: {e!r}")


def attach_paragraphs(e: dict, paperA_lookup, paperB_lookup, paperNplus1_lookup, paperNplus2_lookup, warnings) -> dict:
    return {
        "paperA_paragraphs": paragraphs_for(paperA_lookup, e.get("paperA_section_number"), e.get("paperA_section_name"), warnings, "paperA"),
        "paperB_paragraphs": paragraphs_for(paperB_lookup, e.get("paperB_section_number"), e.get("paperB_section_name"), warnings, "paperB"),
        "paperNplus1_paragraphs": paragraphs_for(paperNplus1_lookup, e.get("paperNplus1_section_number"), e.get("paperNplus1_section_name"), warnings, "paperNplus1"),
        "paperNplus2_paragraphs": paragraphs_for(paperNplus2_lookup, e.get("paperNplus2_section_number"), e.get("paperNplus2_section_name"), warnings, "paperNplus2"),
    }


def from_common_entry(e: dict, paperA_lookup, paperB_lookup, paperNplus1_lookup, paperNplus2_lookup, warnings) -> dict:
    paras = attach_paragraphs(e, paperA_lookup, paperB_lookup, paperNplus1_lookup, paperNplus2_lookup, warnings)
    return {
        "paperA_section_name": e.get("paperA_section_name"),
        "paperA_section_number": e.get("paperA_section_number"),
        "paperA_paragraphs": paras["paperA_paragraphs"],
        "paperB_section_name": e.get("paperB_section_name"),
        "paperB_section_number": e.get("paperB_section_number"),
        "paperB_paragraphs": paras["paperB_paragraphs"],
        "paperNplus1_section_name": e.get("paperNplus1_section_name"),
        "paperNplus1_section_number": e.get("paperNplus1_section_number"),
        "paperNplus1_paragraphs": paras["paperNplus1_paragraphs"],
        "paperNplus2_section_name": e.get("paperNplus2_section_name"),
        "paperNplus2_section_number": e.get("paperNplus2_section_number"),
        "paperNplus2_paragraphs": paras["paperNplus2_paragraphs"],
        "pairing_status": e.get("pairing_status"),
        "basis_papernplus2_to_pairing": e.get("basis_papernplus2_to_pairing"),
        "basis_pairing_to_papernplus2": e.get("basis_pairing_to_papernplus2"),
        "ancestor_questions": e.get("ancestor_questions", []),
        "question_the_sections_answer": e.get("question_the_sections_answer"),
    }


def from_leftover_entry(e: dict, paperA_lookup, paperB_lookup, paperNplus1_lookup, paperNplus2_lookup, warnings) -> dict:
    paras = attach_paragraphs(e, paperA_lookup, paperB_lookup, paperNplus1_lookup, paperNplus2_lookup, warnings)
    direction = e.get("direction")
    basis = e.get("basis")
    if direction == "papernplus2-to-pairing":
        basis_fwd, basis_rev = basis, None
    elif direction == "pairing-to-papernplus2":
        basis_fwd, basis_rev = None, basis
    else:
        raise ValueError(f"unknown direction {direction!r} in leftover entry: {e!r}")

    return {
        "paperA_section_name": e.get("paperA_section_name"),
        "paperA_section_number": e.get("paperA_section_number"),
        "paperA_paragraphs": paras["paperA_paragraphs"],
        "paperB_section_name": e.get("paperB_section_name"),
        "paperB_section_number": e.get("paperB_section_number"),
        "paperB_paragraphs": paras["paperB_paragraphs"],
        "paperNplus1_section_name": e.get("paperNplus1_section_name"),
        "paperNplus1_section_number": e.get("paperNplus1_section_number"),
        "paperNplus1_paragraphs": paras["paperNplus1_paragraphs"],
        "paperNplus2_section_name": e.get("paperNplus2_section_name"),
        "paperNplus2_section_number": e.get("paperNplus2_section_number"),
        "paperNplus2_paragraphs": paras["paperNplus2_paragraphs"],
        "pairing_status": pairing_status_from_diff_type(e.get("diff_type"), e),
        "basis_papernplus2_to_pairing": basis_fwd,
        "basis_pairing_to_papernplus2": basis_rev,
        "ancestor_questions": e.get("ancestor_questions", []),
        "question_the_sections_answer": e.get("question_the_sections_answer"),
    }


def main() -> None:
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    common_path = Path(sys.argv[1])
    leftover_path = Path(sys.argv[2])
    pairing_path = Path(sys.argv[3])
    paperNplus2_path = Path(sys.argv[4])

    with open(common_path, "r", encoding="utf-8") as f:
        common = json.load(f)
    with open(leftover_path, "r", encoding="utf-8") as f:
        leftover = json.load(f)
    with open(pairing_path, "r", encoding="utf-8") as f:
        pairing_entries = json.load(f)
    with open(paperNplus2_path, "r", encoding="utf-8") as f:
        paperNplus2_sections = json.load(f)

    paperA_lookup = build_paragraph_lookup_from_pairing(pairing_entries, "A")
    paperB_lookup = build_paragraph_lookup_from_pairing(pairing_entries, "B")
    paperNplus1_lookup = build_paragraph_lookup_from_pairing(pairing_entries, "Nplus1")
    paperNplus2_lookup = build_paragraph_lookup(paperNplus2_sections)

    warnings = []
    output = [from_common_entry(e, paperA_lookup, paperB_lookup, paperNplus1_lookup, paperNplus2_lookup, warnings) for e in common]
    output += [from_leftover_entry(e, paperA_lookup, paperB_lookup, paperNplus1_lookup, paperNplus2_lookup, warnings) for e in leftover]

    def sort_key(e):
        status_order = {"common-structure": 0, "alignable-diff": 1, "non-alignable-diff": 2}
        n = e["paperNplus2_section_number"]
        return (status_order.get(e["pairing_status"], 3), n is None, n if n is not None else "")

    output.sort(key=sort_key)

    if len(sys.argv) >= 6:
        output_path = Path(sys.argv[5])
    else:
        stem = common_path.name
        suffix = "-papernplus2-common-section-structure.json"
        prefix = stem[: -len(suffix)] if stem.endswith(suffix) else common_path.stem
        output_path = common_path.parent / f"{prefix}-sections-with-paragraphs-and-questions.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Common-structure entries: {len(common)}")
    print(f"Leftover entries: {len(leftover)}")
    print(f"Total entries written: {len(output)}")
    if warnings:
        print(f"\n{len(warnings)} WARNING(S):")
        for w in warnings:
            print(f"  - {w}")
    print(f"\nWrote {output_path}")


if __name__ == "__main__":
    main()
```

### Step 2: Run it

```
python3 build_papernplus2_pairings.py <papernplus2-common-section-structure.json> <papernplus2-leftover-section-differences.json> <three-paper pairing file> <paperNplus2's own sections-with-paragraphs-and-questions.json>
```

### Step 3: Check for warnings

If the script prints any "WARNING(S)" lines, a section named in one of the two papernplus2-family input files couldn't be found in its own extracted/pairing source — a real data-integrity gap, not something to silently accept. Investigate before handing the output to the user.

## Output

`{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-sections-with-paragraphs-and-questions.json` — one entry per four-way pairing, sorted common-structure first, then alignable-diff, then non-alignable-diff.

### Output schema (strict — no extra fields)

```json
{
  "paperA_section_name": "string or null",
  "paperA_section_number": "string or null",
  "paperA_paragraphs": [{"paragraph_number": 0, "text": "..."}],
  "paperB_section_name": "string or null",
  "paperB_section_number": "string or null",
  "paperB_paragraphs": [{"paragraph_number": 0, "text": "..."}],
  "paperNplus1_section_name": "string or null",
  "paperNplus1_section_number": "string or null",
  "paperNplus1_paragraphs": [{"paragraph_number": 0, "text": "..."}],
  "paperNplus2_section_name": "string or null",
  "paperNplus2_section_number": "string or null",
  "paperNplus2_paragraphs": [{"paragraph_number": 0, "text": "..."}],
  "pairing_status": "\"common-structure\", \"alignable-diff\", or \"non-alignable-diff\" -- read verbatim from the source entry for common-structure-sourced entries, derived from diff_type for leftover-sourced entries",
  "basis_papernplus2_to_pairing": "string or null",
  "basis_pairing_to_papernplus2": "string or null",
  "ancestor_questions": "array of strings, carried over verbatim from the source entry, unchanged",
  "question_the_sections_answer": "string or null, carried over verbatim from the source entry, unchanged"
}
```

- `paperA_paragraphs`/`paperB_paragraphs`/`paperNplus1_paragraphs`/`paperNplus2_paragraphs` are `[]` when that side has no section at all (name is null) — normal and expected, not an error.
- `basis_papernplus2_to_pairing`/`basis_pairing_to_papernplus2` are both populated for common-structure entries (both directions independently confirmed it). For leftover entries, only the one matching that entry's own `direction` field is populated — the other is `null`.
- `ancestor_questions` and `question_the_sections_answer` are copied through exactly as they appeared in the source entry — this skill performs no composition, editing, or re-validation of either field.

## Common mistakes to avoid

- **Re-deriving which sections pair together, or `pairing_status`, instead of taking it from the two source files.** This skill's only job is reattaching paragraphs and unifying shape — it does not re-judge matches.
- **Hardcoding `pairing_status` to `"common-structure"` for common-structure-sourced entries instead of reading it from the source.** This is the specific bug caught in `build_papernplus1_pairings.py` one generation down — don't reintroduce it here. The source entry's `pairing_status` is already correctly, freshly computed by `papernplus2-common-section-structure-by-paragraphs-questions`.
- **Composing, rewording, or re-validating `ancestor_questions` or `question_the_sections_answer`.** Both are carried over verbatim — that's the whole point of separating this merge step from the reasoning step upstream.
- **Looking up paperA/paperB/paperNplus1 paragraphs as if they were flat single-paper lists.** They're embedded per-entry inside the three-paper pairing file — use `build_paragraph_lookup_from_pairing`, not `build_paragraph_lookup`, for those three sides.
- **Silently swallowing a lookup-miss warning for a named section.** Surface it — it signals a real mismatch between the papernplus2-family files and their underlying sources.
- **Opening a PDF at any point.** Everything needed is already in the four JSON inputs.
- **Guessing paper-name strings instead of reading them off the input filenames.** Same literal-filename rule as every skill in this family.
- **Writing a custom variant of the bundled script instead of copying it verbatim, or "fixing" its behavior for a specific pairing or paper.** The merge logic is fixed and mechanical — if it produces something that looks wrong, that's a signal to check the underlying data (the two papernplus2-family files, the three-paper pairing file), not to rewrite the script.
