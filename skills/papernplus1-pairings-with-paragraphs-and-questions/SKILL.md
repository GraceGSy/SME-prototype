---
name: "papernplus1-pairings-with-paragraphs-and-questions"
description: "The three-paper analog of \"section-pairings-with-paragraphs-and-questions\". Given the papernplus1-common-section-structure.json and papernplus1-leftover-section-differences.json (from \"papernplus1-common-section-structure-by-paragraphs-questions\"), plus the original two-paper pairing file and paperNplus1's own sections-with-paragraphs-and-questions.json, merges them into one entry per three-way pairing carrying paperA/paperB/paperNplus1 paragraphs, a unified pairing_status (common-structure/alignable-diff/non-alignable-diff) read directly from the source entry, split basis_papernplus1_to_pairing/basis_pairing_to_papernplus1 fields, and ancestor_questions/question_the_sections_answer carried over verbatim (no new composition). Use whenever the user wants to fold a fourth (or Nth) paper into an existing three-paper section comparison and needs the three-paper \"pairing\" file with real paragraph content attached -- the required input for a papernplus2-family directional mapping. PDF-free."
---

# PaperNplus1 Pairings With Paragraphs And Questions

## What this is (and isn't)

This is the three-paper analog of `section-pairings-with-paragraphs-and-questions`. That skill merges a two-paper `common-section-structure.json`/`leftover-section-differences.json` pair with each paper's own extracted paragraphs, producing one entry per section pairing. This skill does the same job one level up: it merges `papernplus1-common-section-structure.json`/`papernplus1-leftover-section-differences.json` (from `papernplus1-common-section-structure-by-paragraphs-questions`) — which carry paperA/paperB/paperNplus1 section *names* and a composed question, but no paragraph text — with the original two-paper pairing file (for paperA/paperB paragraphs) and paperNplus1's own extracted file (for paperNplus1 paragraphs), producing one entry per three-way pairing with all three sides' actual paragraph text attached.

This skill does no new matching, comparison, or classification of its own — same principle as its two-paper sibling. Every pairing it outputs comes straight from the two papernplus1-family input files; its only job is reattaching paragraph text those files don't carry, plus unifying their slightly different shapes into one consistent schema.

**Why this exists:** the output of this skill is the required "pairing" input for folding in a *fourth* paper (the papernplus2 family), the same way the two-paper pairing file (from `section-pairings-with-paragraphs-and-questions`) is the required input for folding in the third paper (the papernplus1 family). Without this merge step, a fourth paper has nothing with real paragraph content to be matched against — `papernplus1-common-section-structure.json`/`papernplus1-leftover-section-differences.json` alone only carry section names, basis text, and a question, never paragraphs.

**Schema unification, and one important field-meaning change to watch for.** The two input files aren't quite the same shape: common-structure entries have no `direction`/`reason`/`diff_type` fields (they're definitionally confirmed) and carry two basis fields (`basis_papernplus1_to_pairing`/`basis_pairing_to_papernplus1`); leftover entries have those three fields plus a single `basis` field tied to whichever one `direction` produced them. This skill unifies both into one consistent output schema — every entry gets `basis_papernplus1_to_pairing` and `basis_pairing_to_papernplus1` (only the one matching a leftover entry's own `direction` populated, the other `null`), and a single `pairing_status` field. **`pairing_status` in this skill's output means something different from the `pairing_status` field the leftover file also happens to carry**: the leftover file's `pairing_status` is the *underlying two-paper* pairing's own status (whether paperA and paperB confirmed with each other) — a different axis entirely from whether paperNplus1 confirmed with that pairing (which is what `diff_type` captures). This skill's own `pairing_status` is the *three-way* status: for entries sourced from the common-structure file, read **directly from that entry's own `pairing_status` field** (see "Bug fixed 2026-08-16" below — do not hardcode this); for entries sourced from the leftover file, `diff_type` + `"-diff"`. The underlying two-paper-level `pairing_status` (the one the leftover file carries) is deliberately **dropped**, not carried forward, specifically to avoid two same-named fields silently meaning different things at different points in this pipeline.

**Bug fixed 2026-08-16 (real fix, not just documented intent).** An earlier version of this skill's bundled script (`from_common_entry`) hardcoded `"pairing_status": "common-structure"` for every entry sourced from the common-structure file, discarding whatever `papernplus1-common-section-structure-by-paragraphs-questions`'s own (already-corrected, monotonic) `pairing_status` computation actually said for that entry. This silently promoted `alignable-diff` confirmed matches (a paperNplus1 section bidirectionally confirming against a pairing whose ancestor two-paper status was `alignable-diff` or `non-alignable-diff`) back up to `common-structure`, discarding real information. The bug was caught and worked around manually during a real run (a confirmed match between illusionofcausality and measuringseparability paragraphs, with no crowdsourcinggraphical counterpart, that should have read `alignable-diff` but was silently overwritten to `common-structure`) — a prior pass at documenting this fix updated this file's prose to claim it was corrected without actually changing the script, which is exactly the kind of drift this note exists to prevent recurring. The script below now reads `e.get("pairing_status")` directly from the source entry, matching how `papernplus2-pairings-with-paragraphs-and-questions`'s own script was built correctly from the start (see that skill's own "Correction, 2026-08-16" note, which cites this bug as its precedent). **If this skill is ever copied or forked again, verify the fix actually landed in the code, not just the prose** — check `from_common_entry` reads `pairing_status` from `e`, never a literal string.

`ancestor_questions` and `question_the_sections_answer` are carried over **verbatim, unchanged** — this skill does no question composition of its own, same "just reattach paragraphs" philosophy as its two-paper sibling. Don't recompute, reword, or re-validate either field here.

Not a PDF-reading skill — nothing here opens a PDF.

**The script in this skill's Workflow is given verbatim and must be copied byte-for-byte, never authored or modified.** Wherever the instructions say "write the script," that means transcribe the exact code shown into a file — not compose a variant, not add a flag, not adjust behavior for a specific case. If the script's documented behavior seems wrong for what you're trying to do, that's a stop-and-ask-the-user moment, not a reason to write custom logic (see `extract-paragraphs-as-pseudo-sections`'s "Stage 0 is strictly mechanical" section for the real incident this rule generalizes from).

## Inputs

Four files:

1. `{prefix}-papernplus1-common-section-structure.json` — from `papernplus1-common-section-structure-by-paragraphs-questions`.
2. `{prefix}-papernplus1-leftover-section-differences.json` — from the same skill.
3. `{paperA-name}-{paperB-name}-sections-with-paragraphs-and-questions.json` — the two-paper pairing file, from `section-pairings-with-paragraphs-and-questions`. Its own entries carry `paperA_paragraphs`/`paperB_paragraphs` embedded per pairing, not as flat single-paper lists — this skill's lookup logic accounts for that.
4. `{paperNplus1-name}-sections-with-paragraphs-and-questions.json` — paperNplus1's own extracted file, a flat single-paper list.

`{prefix}` is typically `{paperA-name}-{paperB-name}-{paperNplus1-name}`. All paper-name strings must be the literal PDF filenames (minus `.pdf`) already established earlier in the pipeline — don't guess or reformat.

## Workflow

### Step 1: Copy the script into a local file

Copy the script below byte-for-byte into a local file (e.g. `build_papernplus1_pairings.py`) — this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant.

```python
#!/usr/bin/env python3
"""
Merges papernplus1-common-section-structure.json + papernplus1-leftover-section-differences.json
(from papernplus1-common-section-structure-by-paragraphs-questions) with the two-paper pairing
file (for paperA_paragraphs/paperB_paragraphs) and paperNplus1's own sections-with-paragraphs-
and-questions.json (for paperNplus1_paragraphs), producing ONE entry per three-way pairing with
all three sides' paragraphs attached -- the three-paper analog of section-pairings-with-
paragraphs-and-questions.

Unifies the common-structure and leftover files into one consistent schema (mirroring how
section-pairings-with-paragraphs-and-questions unifies the base pipeline's two files):
pairing_status becomes this entry's OWN three-way status (common-structure / alignable-diff /
non-alignable-diff) -- NOT the underlying two-paper pairing_status the leftover file also happens
to carry, which is dropped here to avoid a same-named field meaning two different things.
basis_papernplus1_to_pairing/basis_pairing_to_papernplus1 are both populated for common entries;
for leftover entries only the one matching that entry's own `direction` field is populated, the
other left null (same split convention as the base skill's basis_p1_p2/basis_p2_p1).

pairing_status for COMMON entries is read DIRECTLY from the source entry's own pairing_status
field (fixed 2026-08-16 -- a real bug, not just a documentation update: an earlier version of
this script hardcoded "common-structure" here regardless of what papernplus1-common-section-
structure-by-paragraphs-questions had actually computed, silently discarding a real
alignable-diff classification. Verified fix: from_common_entry below reads e.get("pairing_status"),
never a literal string. This matches how build_papernplus2_pairings.py was built correctly from
the start one generation up -- see that script's own docstring, which cites this exact bug as
precedent for why it never hardcodes the value.). For LEFTOVER entries, pairing_status is still
derived from diff_type via pairing_status_from_diff_type -- that mapping was never the bug.

ancestor_questions and question_the_sections_answer are carried over VERBATIM, unchanged -- this
skill does no question composition of its own, same "just reattach paragraphs" philosophy as
section-pairings-with-paragraphs-and-questions.

Usage:
    python3 build_papernplus1_pairings.py <papernplus1-common-section-structure.json> <papernplus1-leftover-section-differences.json> <paperA-paperB-pairing-file.json> <paperNplus1-sections-with-paragraphs-and-questions.json> [output_path]
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
    """For paperA/paperB, whose sections live embedded (dual-sided) inside the two-paper
    pairing file's own entries rather than as a flat single-paper list. side is 'A' or 'B'."""
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


def attach_paragraphs(e: dict, paperA_lookup, paperB_lookup, paperNplus1_lookup, warnings) -> dict:
    return {
        "paperA_paragraphs": paragraphs_for(paperA_lookup, e.get("paperA_section_number"), e.get("paperA_section_name"), warnings, "paperA"),
        "paperB_paragraphs": paragraphs_for(paperB_lookup, e.get("paperB_section_number"), e.get("paperB_section_name"), warnings, "paperB"),
        "paperNplus1_paragraphs": paragraphs_for(paperNplus1_lookup, e.get("paperNplus1_section_number"), e.get("paperNplus1_section_name"), warnings, "paperNplus1"),
    }


def from_common_entry(e: dict, paperA_lookup, paperB_lookup, paperNplus1_lookup, warnings) -> dict:
    paras = attach_paragraphs(e, paperA_lookup, paperB_lookup, paperNplus1_lookup, warnings)
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
        # FIX (2026-08-16): read from the source entry -- never hardcode "common-structure" here.
        # papernplus1-common-section-structure-by-paragraphs-questions already computes the
        # correct, monotonic per-entry pairing_status (common-structure only if the ancestor
        # two-paper pairing was also common-structure; alignable-diff otherwise). Hardcoding
        # this string silently discards that computation for every confirmed match whose
        # ancestor wasn't itself common-structure.
        "pairing_status": e.get("pairing_status"),
        "basis_papernplus1_to_pairing": e.get("basis_papernplus1_to_pairing"),
        "basis_pairing_to_papernplus1": e.get("basis_pairing_to_papernplus1"),
        "ancestor_questions": e.get("ancestor_questions", []),
        "question_the_sections_answer": e.get("question_the_sections_answer"),
    }


def from_leftover_entry(e: dict, paperA_lookup, paperB_lookup, paperNplus1_lookup, warnings) -> dict:
    paras = attach_paragraphs(e, paperA_lookup, paperB_lookup, paperNplus1_lookup, warnings)
    direction = e.get("direction")
    basis = e.get("basis")
    if direction == "papernplus1-to-pairing":
        basis_fwd, basis_rev = basis, None
    elif direction == "pairing-to-papernplus1":
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
        "pairing_status": pairing_status_from_diff_type(e.get("diff_type"), e),
        "basis_papernplus1_to_pairing": basis_fwd,
        "basis_pairing_to_papernplus1": basis_rev,
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
    paperNplus1_path = Path(sys.argv[4])

    with open(common_path, "r", encoding="utf-8") as f:
        common = json.load(f)
    with open(leftover_path, "r", encoding="utf-8") as f:
        leftover = json.load(f)
    with open(pairing_path, "r", encoding="utf-8") as f:
        pairing_entries = json.load(f)
    with open(paperNplus1_path, "r", encoding="utf-8") as f:
        paperNplus1_sections = json.load(f)

    paperA_lookup = build_paragraph_lookup_from_pairing(pairing_entries, "A")
    paperB_lookup = build_paragraph_lookup_from_pairing(pairing_entries, "B")
    paperNplus1_lookup = build_paragraph_lookup(paperNplus1_sections)

    warnings = []
    output = [from_common_entry(e, paperA_lookup, paperB_lookup, paperNplus1_lookup, warnings) for e in common]
    output += [from_leftover_entry(e, paperA_lookup, paperB_lookup, paperNplus1_lookup, warnings) for e in leftover]

    def sort_key(e):
        status_order = {"common-structure": 0, "alignable-diff": 1, "non-alignable-diff": 2}
        n = e["paperNplus1_section_number"]
        return (status_order.get(e["pairing_status"], 3), n is None, n if n is not None else "")

    output.sort(key=sort_key)

    if len(sys.argv) >= 6:
        output_path = Path(sys.argv[5])
    else:
        stem = common_path.name
        suffix = "-papernplus1-common-section-structure.json"
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
python3 build_papernplus1_pairings.py <papernplus1-common-section-structure.json> <papernplus1-leftover-section-differences.json> <two-paper pairing file> <paperNplus1's own sections-with-paragraphs-and-questions.json>
```

### Step 3: Check for warnings

If the script prints any "WARNING(S)" lines, a section named in one of the two papernplus1-family input files couldn't be found in its own extracted/pairing source — a real data-integrity gap (mismatched prefix, stale file, renumbered section), not something to silently accept. Investigate before handing the output to the user.

## Output

`{paperA-name}-{paperB-name}-{paperNplus1-name}-sections-with-paragraphs-and-questions.json` — one entry per three-way pairing, sorted common-structure first, then alignable-diff, then non-alignable-diff.

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
  "pairing_status": "\"common-structure\", \"alignable-diff\", or \"non-alignable-diff\" -- THIS entry's own three-way status, not the underlying two-paper pairing_status the leftover file also carries (that field is dropped). For common-structure-sourced entries, read directly from the source entry's own pairing_status (never hardcoded -- see Bug fixed 2026-08-16 above)",
  "basis_papernplus1_to_pairing": "string or null",
  "basis_pairing_to_papernplus1": "string or null",
  "ancestor_questions": "array of strings, carried over verbatim from the source entry, unchanged",
  "question_the_sections_answer": "string or null, carried over verbatim from the source entry, unchanged"
}
```

- `pairing_status` is read directly from the source entry's own `pairing_status` field for every entry sourced from the common-structure file (never hardcoded — see "Bug fixed 2026-08-16" above). For leftover-sourced entries it's derived from that entry's own `diff_type` (`"alignable"` → `"alignable-diff"`, `"non-alignable"` → `"non-alignable-diff"`) — same suffix convention as `section-pairings-with-paragraphs-and-questions`.
- `paperA_paragraphs`/`paperB_paragraphs`/`paperNplus1_paragraphs` are `[]` when that side has no section at all (name is null) — normal and expected, not an error.
- `basis_papernplus1_to_pairing`/`basis_pairing_to_papernplus1` are both populated for common-structure entries (both directions independently confirmed it). For leftover entries, only the one matching that entry's own `direction` field is populated — the other is `null`.
- `ancestor_questions` and `question_the_sections_answer` are copied through exactly as they appeared in the source entry — this skill performs no composition, editing, or re-validation of either field.

## Common mistakes to avoid

- **Re-deriving which sections pair together, or `pairing_status`, instead of taking it from the two source files.** This skill's only job is reattaching paragraphs and unifying shape — it does not re-judge matches.
- **Hardcoding `pairing_status` to `"common-structure"` for common-structure-sourced entries instead of reading it from the source entry.** This was a real bug in this skill, fixed 2026-08-16 — see "Bug fixed 2026-08-16" above. Verify `from_common_entry` reads `e.get("pairing_status")`, not a literal string, if this script is ever copied, forked, or hand-edited.
- **Confusing this skill's `pairing_status` output with the underlying two-paper `pairing_status` field the leftover file also carries.** They're different axes (three-way confirmation vs. two-way confirmation) — this skill deliberately drops the two-paper-level one rather than carrying forward a same-named field with a different meaning.
- **Composing, rewording, or re-validating `ancestor_questions` or `question_the_sections_answer`.** Both are carried over verbatim — that's the whole point of separating this merge step from `papernplus1-common-section-structure-by-paragraphs-questions`'s own reasoning step.
- **Looking up paperA/paperB paragraphs as if they were flat single-paper lists.** They're embedded per-entry inside the two-paper pairing file — use `build_paragraph_lookup_from_pairing`, not `build_paragraph_lookup`, for those two sides.
- **Silently swallowing a lookup-miss warning for a named section.** Surface it — it signals a real mismatch between the papernplus1-family files and their underlying sources.
- **Opening a PDF at any point.** Everything needed is already in the four JSON inputs.
- **Guessing paper-name strings instead of reading them off the input filenames.** Same literal-filename rule as every skill in this family.
- **Trusting this file's own prose without checking the code.** This exact skill previously had prose elsewhere in this pipeline (in `papernplus1-common-section-structure-by-paragraphs-questions`'s SKILL.md) claiming this bug was already fixed when the actual bundled script here still had it — a documentation/code drift that went undetected until a real run surfaced a wrong `pairing_status` value. When in doubt, read the script, not the changelog note.
- **Writing a custom variant of the bundled script instead of copying it verbatim, or "fixing" its behavior for a specific pairing or paper.** The merge logic is fixed and mechanical — if it produces something that looks wrong, that's a signal to check the underlying data (the two papernplus1-family files, the pairing file), not to rewrite the script.
