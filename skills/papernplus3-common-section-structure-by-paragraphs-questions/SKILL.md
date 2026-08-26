---
name: "papernplus3-common-section-structure-by-paragraphs-questions"
description: "The papernplus3-family analog of papernplus2-common-section-structure-by-paragraphs-questions -- the planned cap of the bespoke-field-growth plan (5 papers total). Given papernplus3-both-directions-mapping's combined output plus the four-paper pairing file and the fifth paper's own sections-with-paragraphs-and-questions.json, writes {prefix}-papernplus3-common-section-structure.json and {prefix}-papernplus3-leftover-section-differences.json. Confirmed five-way matches get a fresh question; leftovers with a real pairing carry forward unchanged; leftovers with none pull paperNplus3's own question_this_section_answers forward verbatim instead of composing fresh (fixed 2026-08-17). A hard Step 4 validator (2026-08-16) blocks completion until every entry -- including carried-forward ones -- has a real question or is verified legitimately empty. No PDF opened. Use for confirmed five-paper section correspondences."
---

# PaperNplus3 Common Section Structure (by Paragraphs and Questions)

## What this is (and isn't)

This is the papernplus3-family analog of `papernplus2-common-section-structure-by-paragraphs-questions`, one generation further: a downstream step on top of `papernplus3-both-directions-mapping-by-paragraphs-and-questions`'s combined output. It splits every entry from both passes into two files — the five-way correspondences (a paperNplus3 section, and/or a paperA/paperB/paperNplus1/paperNplus2 side of an existing four-way pairing) that both directional passes independently agree on, and everything else.

**This generation is the planned cap on bespoke-field growth (5 papers total), per the design decision made when the papernplus1 family was first built.** If a sixth paper is ever needed, don't extend this skill's pattern with a sixth hardcoded field set — revisit the generalized `sides`-array redesign that was considered and deferred, instead.

**Same confirmed / carried-forward / true-singleton split as its predecessor, extended by one more side.** At this generation, most entries in a both-directions pass are not new information: they're either a genuinely new five-way confirmation, or the same four-way pairing that already existed, now simply found (or not found) to have no fifth-paper counterpart.

- **Confirmed (five-way) entries** — paperNplus3 genuinely, bidirectionally matched an existing four-way pairing (or part of one): `ancestor_questions` is the matched pairing's own prior `ancestor_questions` list with that pairing's own (now-superseded) `question_the_sections_answer` appended to it. A fresh `question_the_sections_answer` is composed in Step 3 from whichever of the (up to) five sides are present — a genuine multi-sided correlation, so a real new question is warranted.
- **Leftover entries where a real pairing is still present on at least one of paperA/paperB/paperNplus1/paperNplus2** — `ancestor_questions` and `question_the_sections_answer` are carried forward completely unchanged from that pairing's own prior values. **Step 3 must not touch these entries in the normal case.** (See "Step 3 completeness is now a hard gate" below for the one exception: if Step 4's validator flags a carried-forward entry as actually missing a real question, that means an *earlier* generation's own Step 3 was itself incomplete — go back and fix it then, even though the ordinary rule is hands-off.)
- **Leftover entries with no real pairing on any side (a true paperNplus3-only singleton) — corrected 2026-08-17.** A paperNplus3 section that matched nothing anywhere in the four-way structure (`reason: "no_counterpart_found"`, all four matched-pairing sides null): `ancestor_questions` is `[]`, and `question_the_sections_answer` is **pulled forward verbatim from paperNplus3's own `question_this_section_answers`** (already sitting in file 3) — **not composed fresh.** There is nothing here to correlate against, so there is nothing to newly reason about either; the only job is finding paperNplus3's own existing question and copying it forward. This mirrors, one generation further, the identical fix already applied to `directional-section-mapping-by-paragraphs-and-questions` and to the papernplus1- and papernplus2-family predecessors' own singleton cases.

**No normalize step is needed here**, same reason as every earlier generation: `paperA`/`paperB`/`paperNplus1`/`paperNplus2`/`paperNplus3` are stable identity labels in both directional passes, never reassigned per-pass.

**Departure from the base two-paper skill, extended one more level:** a confirmed five-way match can have any subset of paperA/paperB/paperNplus1/paperNplus2 present (not all four).

**`pairing_status` and `diff_type` are computed with the corrected (2026-08-16), monotonic logic from the start — no separate fix needed at this generation, unlike the papernplus1-family and papernplus2-family originals.** Those two skills initially conflated "the newest paper doesn't participate" with "nothing aligns with this at all" (a leftover entry's `diff_type` was set purely by checking whether the newest paper had a name, and a confirmed entry's `pairing_status` was a blind copy of the matched pairing's own prior status), and both had to be corrected after a real example surfaced the bug. This skill's script is built directly from the corrected version: a fresh bidirectional confirmation is `common-structure` only if the ancestor four-paper pairing was *already* `common-structure` (monotonic — never regained once lost); otherwise `alignable-diff`, including when the ancestor was `non-alignable-diff`. A leftover with *no* match found for paperNplus3 is `non-alignable` only if the ancestor pairing was *already* `non-alignable-diff` — otherwise `alignable`. Leftover entries carry the ancestor's own prior status under `ancestor_pairing_status` (not `pairing_status`), same rename as the corrected papernplus1/papernplus2 skills.

**Awareness note: this skill can't recover a role that was never split out upstream.** Every join here is mechanical (Step 2's script) and question composition (Step 3) only ever reads paragraphs the upstream directional-mapping passes already assigned to a given entry — this skill never re-reads a section from scratch to check whether it should have been split differently. This mattered concretely in the real end-to-end test that first exercised this generation: mesotext's own single "User Study" section only ended up correctly represented as six separate entries here (design/participants/procedure, qualitative Results, quantitative Results, plus three narrower AbstractExplorer-only entries sourced from mesotext's own Appendix C — a qualitative-coding methodology, verbatim task prompts, verbatim survey questions) because `directional-section-mapping-paragraphs-and-questions-papernplus3` and `pairing-to-papernplus3-mapping-by-paragraphs-and-questions` had already found and split those roles at the paragraph level upstream — this skill itself never read a single paragraph to discover them. If either of those two skills instead folds such a role into one entry, or drops it, there's nothing this skill can do to notice or recover it. See those two skills' "buried narrow role" guidance for the full explanation.

**Step 3 completeness is now a hard gate (added 2026-08-16), not an honor system.** A real 5-paper corpus run of this family surfaced entries in the final leftover file — e.g. the "Findings and Future Work" / "General Discussion" alignable pairing — with a `null` `question_the_sections_answer` despite `ancestor_questions` showing real prior content, because an earlier generation's Step 3 composition was never actually completed for that lineage, and this generation's own carry-forward rule (correctly) just passed the gap along untouched. Step 4 below re-checks *every* entry in both output files mechanically — including carried-forward ones — before this skill is allowed to be reported as done, specifically so a gap like that is caught at the point it's discovered rather than staying invisible in the "final" output. This gate stays in place even after the 2026-08-17 pull-forward fix — a silently-skipped pull-forward leaves exactly the same kind of null gap as a silently-skipped composition.

**Every script in this skill's Workflow (Steps 2 and 4) is given verbatim and must be copied byte-for-byte, never authored or modified.** Wherever the instructions say "write the script," that means transcribe the exact code shown into a file — not compose a variant, not add a flag, not adjust behavior for a specific entry or case. If a script's documented behavior seems wrong for a specific situation, that's a stop-and-ask-the-user moment, not a reason to write custom logic (see `extract-paragraphs-as-pseudo-sections`'s "Stage 0 is strictly mechanical" section for the real incident this rule generalizes from). This generation, being the last in the planned 5-paper cap, is also the last chance to catch a script substitution before it becomes part of the permanent final record.

## Inputs

Three files:

1. The combined output of `papernplus3-both-directions-mapping-by-paragraphs-and-questions`, named `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-{paperNplus3-name}-both-directions-section-mapping-by-paragraphs-and-questions.json` — a JSON object with exactly two keys, `papernplus3-to-pairing` and `pairing-to-papernplus3`.
2. The four-paper pairing file, `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-sections-with-paragraphs-and-questions.json` — from `papernplus2-pairings-with-paragraphs-and-questions`. Used three times: mechanically in Step 2 (the script reads it directly, to look up each matched pairing's own `ancestor_questions`/`question_the_sections_answer`), again in Step 3's reasoning pass (to look up the actual `paperA_paragraphs`/`paperB_paragraphs`/`paperNplus1_paragraphs`/`paperNplus2_paragraphs` for composing a fresh question on confirmed entries), and again in Step 4's validator (same paragraph lookup, to check whether a missing question is legitimately empty-content).
3. The fifth paper's own `{paperNplus3-name}-sections-with-paragraphs-and-questions.json` — from `orchestrator-extract-sections-paragraphs-and-questions`. Gives Step 3 (and Step 4) the actual `paragraphs` for the paperNplus3 side, and — for a true paperNplus3-only singleton — its own precomputed `question_this_section_answers` to pull forward verbatim.

All filenames must use the literal PDF-filename prefixes (minus `.pdf`) already established earlier in the pipeline.

## Workflow

### Step 1: Confirm the inputs

Check file 1 is a JSON object with exactly `papernplus3-to-pairing` and `pairing-to-papernplus3` as its top-level keys. Confirm files 2 and 3 are present.

### Step 2: Run the matching script

Copy the script below byte-for-byte into a local file (e.g. `find_papernplus3_bidirectional_matches.py`) — this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant. Then run it with **both** file 1 and file 2:

```bash
python3 find_papernplus3_bidirectional_matches.py {paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-{paperNplus3-name}-both-directions-section-mapping-by-paragraphs-and-questions.json {paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-sections-with-paragraphs-and-questions.json
```

```python
#!/usr/bin/env python3
"""
Reads the combined output of papernplus3-both-directions-mapping-by-paragraphs-and-questions
(a JSON object with "papernplus3-to-pairing" and "pairing-to-papernplus3" keys) plus the
four-paper pairing file (papernplus2-pairings-with-paragraphs-and-questions output), and
splits every both-directions entry into two files:

  - {prefix}-papernplus3-common-section-structure.json     confirmed five-way matches
  - {prefix}-papernplus3-leftover-section-differences.json  everything else

A five-way match is "confirmed" only when the SAME (paperNplus3, paperA, paperB, paperNplus1,
paperNplus2) identity is independently found from both directions.

pairing_status / diff_type semantics (correct from the start at this generation, mirroring the
2026-08-16 correction applied to the papernplus1-family and papernplus2-family scripts):
  - CONFIRMED entries get a freshly computed `pairing_status`: "common-structure" only if
    the ancestor four-way pairing was ALSO common-structure (monotonic -- once broken,
    never regained); "alignable-diff" otherwise, including when the ancestor was
    non-alignable-diff (a bidirectional confirmation just happened, so it can't still be
    "nothing aligns with this").
  - LEFTOVER entries get a freshly computed `diff_type`: "alignable" if THIS pass found a
    real unidirectional match; if this pass found NOTHING, "non-alignable" only if the
    ancestor pairing was ALREADY non-alignable-diff -- otherwise "alignable", since the
    earlier papers still align with each other even though paperNplus3 doesn't participate.
    `reason` is a separate, raw fact about whether THIS pass found a match at all -- it
    does not drive diff_type, and vice versa.
  - LEFTOVER entries also carry `ancestor_pairing_status`: the underlying four-way pairing's
    own PRIOR status, preserved verbatim (not recomputed).

ancestor_questions handling (same confirmed/carried-forward split as papernplus2-family;
true-singleton case corrected 2026-08-17):
  - CONFIRMED entries: the matched pairing entry's own ancestor_questions list is APPENDED
    with that pairing's own (now-superseded) question_the_sections_answer. question_the_
    sections_answer itself is left None here -- composed fresh in Step 3 of the skill.
  - LEFTOVER entries where at least one of paperA/paperB/paperNplus1/paperNplus2 is present
    (a real pairing exists, whether or not it was independently confirmed): ancestor_questions
    AND question_the_sections_answer are CARRIED FORWARD UNCHANGED from that pairing entry --
    nothing new was learned, so nothing is recomposed. Step 3 must NOT touch these entries.
  - LEFTOVER entries where NONE of paperA/paperB/paperNplus1/paperNplus2 are present
    (paperNplus3's own section matched nothing at all in the whole pairing structure):
    ancestor_questions = [], question_the_sections_answer left None here -- a true
    singleton. Fixed 2026-08-17: this is PULLED FORWARD from paperNplus3's own question_
    this_section_answers in Step 3, not composed fresh.

Usage:
    python3 find_papernplus3_bidirectional_matches.py combined-both-directions.json four-paper-pairing-file.json [output_dir]
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


def build_pairing_lookup(pairing_entries):
    """Keys on the joint (paperA_key, paperB_key, paperNplus1_key, paperNplus2_key) tuple --
    a pairing entry's ancestor_questions/question is a property of the whole four-sided pairing."""
    lookup = {}
    for e in pairing_entries:
        a_key = side_key(e.get("paperA_section_number"), e.get("paperA_section_name"))
        b_key = side_key(e.get("paperB_section_number"), e.get("paperB_section_name"))
        n1_key = side_key(e.get("paperNplus1_section_number"), e.get("paperNplus1_section_name"))
        n2_key = side_key(e.get("paperNplus2_section_number"), e.get("paperNplus2_section_name"))
        lookup[(a_key, b_key, n1_key, n2_key)] = {
            "ancestor_questions": e.get("ancestor_questions", []),
            "question_the_sections_answer": e.get("question_the_sections_answer"),
        }
    return lookup


def lookup_pairing_entry(paperA_name, paperA_num, paperB_name, paperB_num, paperNplus1_name, paperNplus1_num, paperNplus2_name, paperNplus2_num, pairing_lookup, warnings):
    """Returns the matched pairing's own {ancestor_questions, question_the_sections_answer}
    dict, or None if there's no real pairing to point to at all (all four sides null), or
    a genuine lookup-miss (warns, returns None)."""
    a_key = side_key(paperA_num, paperA_name)
    b_key = side_key(paperB_num, paperB_name)
    n1_key = side_key(paperNplus1_num, paperNplus1_name)
    n2_key = side_key(paperNplus2_num, paperNplus2_name)
    if a_key is None and b_key is None and n1_key is None and n2_key is None:
        return None
    entry = pairing_lookup.get((a_key, b_key, n1_key, n2_key))
    if entry is None:
        warnings.append(
            f"No matching pairing-file entry for paperA={paperA_name!r}/{paperA_num!r}, "
            f"paperB={paperB_name!r}/{paperB_num!r}, paperNplus1={paperNplus1_name!r}/{paperNplus1_num!r}, "
            f"paperNplus2={paperNplus2_name!r}/{paperNplus2_num!r} -- ancestor_questions/question left "
            f"empty/null. Real data-integrity gap, not expected."
        )
        return None
    return entry


def appended_ancestor_questions(pairing_entry):
    """For a NEWLY CONFIRMED five-way match: old ancestor_questions + [old question], since
    that question is now superseded by a fresh one composed in Step 3."""
    if pairing_entry is None:
        return []
    old_list = list(pairing_entry.get("ancestor_questions", []))
    old_q = pairing_entry.get("question_the_sections_answer")
    return old_list + ([old_q] if old_q else [])


def key_of_forward(entry):
    """Key for a papernplus3-to-pairing entry, or None if no match was found at all (all
    four matched_pairing_paper*_section_name fields are empty)."""
    a_key = side_key(entry.get("matched_pairing_paperA_section_number"), entry.get("matched_pairing_paperA_section_name"))
    b_key = side_key(entry.get("matched_pairing_paperB_section_number"), entry.get("matched_pairing_paperB_section_name"))
    n1_key = side_key(entry.get("matched_pairing_paperNplus1_section_number"), entry.get("matched_pairing_paperNplus1_section_name"))
    n2_key = side_key(entry.get("matched_pairing_paperNplus2_section_number"), entry.get("matched_pairing_paperNplus2_section_name"))
    if a_key is None and b_key is None and n1_key is None and n2_key is None:
        return None
    n3_key = side_key(entry.get("paperNplus3_section_number"), entry.get("paperNplus3_section_name"))
    return (n3_key, a_key, b_key, n1_key, n2_key)


def key_of_reverse(entry):
    """Key for a pairing-to-papernplus3 entry, or None if no match was found at all
    (paperNplus3_section_name is empty)."""
    n3_key = side_key(entry.get("paperNplus3_section_number"), entry.get("paperNplus3_section_name"))
    if n3_key is None:
        return None
    a_key = side_key(entry.get("pairing_paperA_section_number"), entry.get("pairing_paperA_section_name"))
    b_key = side_key(entry.get("pairing_paperB_section_number"), entry.get("pairing_paperB_section_name"))
    n1_key = side_key(entry.get("pairing_paperNplus1_section_number"), entry.get("pairing_paperNplus1_section_name"))
    n2_key = side_key(entry.get("pairing_paperNplus2_section_number"), entry.get("pairing_paperNplus2_section_name"))
    return (n3_key, a_key, b_key, n1_key, n2_key)


def found_match_forward(entry) -> bool:
    """Did paperNplus3's own best-match search find a real candidate pairing at all (any of
    A/B/Nplus1/Nplus2 named)? Raw fact about this one pass -- used for `reason`, not `diff_type`."""
    a = entry.get("matched_pairing_paperA_section_name")
    b = entry.get("matched_pairing_paperB_section_name")
    n1 = entry.get("matched_pairing_paperNplus1_section_name")
    n2 = entry.get("matched_pairing_paperNplus2_section_name")
    return any(norm(x) is not None for x in (a, b, n1, n2))


def found_match_reverse(entry) -> bool:
    """Did this pairing's own best-match search land on a real paperNplus3 section? Raw
    fact about this one pass -- used for `reason`, not `diff_type`."""
    return norm(entry.get("paperNplus3_section_name")) is not None


def diff_type_forward(entry) -> str:
    """paperNplus3's own section found no candidate anywhere -- genuinely non-alignable.
    No ancestor status to fall back on: if nothing is named, there's no existing pairing
    for this to have inherited a status from."""
    return "alignable" if found_match_forward(entry) else "non-alignable"


def diff_type_reverse(entry, warnings) -> str:
    """If paperNplus3 matched this pairing unidirectionally, that's always alignable. If
    paperNplus3 found NOTHING for this pairing, fall back to the pairing's own prior status:
    only non-alignable if that pairing was ALREADY isolated (non-alignable-diff); otherwise
    the earlier papers still align with each other, so this is alignable, even though
    paperNplus3 doesn't participate."""
    if found_match_reverse(entry):
        return "alignable"
    ancestor_status = entry.get("pairing_status")
    if ancestor_status == "non-alignable-diff":
        return "non-alignable"
    if ancestor_status not in ("common-structure", "alignable-diff"):
        warnings.append(
            f"Unrecognized/missing ancestor pairing_status {ancestor_status!r} for paperA="
            f"{entry.get('pairing_paperA_section_name')!r}, paperB={entry.get('pairing_paperB_section_name')!r}, "
            f"paperNplus1={entry.get('pairing_paperNplus1_section_name')!r}, "
            f"paperNplus2={entry.get('pairing_paperNplus2_section_name')!r} -- defaulting to non-alignable. "
            f"Real data-integrity gap, not expected."
        )
        return "non-alignable"
    return "alignable"


def common_pairing_status(ancestor_status) -> str:
    """Fresh per-generation status for a CONFIRMED (bidirectional) five-way match:
    common-structure only if the ancestor four-way pairing was ALSO common-structure
    (monotonic). Otherwise alignable-diff -- including when the ancestor was
    non-alignable-diff, since a genuine bidirectional confirmation just happened."""
    return "common-structure" if ancestor_status == "common-structure" else "alignable-diff"


def leftover_from_forward(entry, pairing_lookup, warnings) -> dict:
    paperA_name = entry.get("matched_pairing_paperA_section_name")
    paperA_num = entry.get("matched_pairing_paperA_section_number")
    paperB_name = entry.get("matched_pairing_paperB_section_name")
    paperB_num = entry.get("matched_pairing_paperB_section_number")
    paperNplus1_name = entry.get("matched_pairing_paperNplus1_section_name")
    paperNplus1_num = entry.get("matched_pairing_paperNplus1_section_number")
    paperNplus2_name = entry.get("matched_pairing_paperNplus2_section_name")
    paperNplus2_num = entry.get("matched_pairing_paperNplus2_section_number")

    pairing_entry = lookup_pairing_entry(paperA_name, paperA_num, paperB_name, paperB_num, paperNplus1_name, paperNplus1_num, paperNplus2_name, paperNplus2_num, pairing_lookup, warnings)
    has_real_pairing = any(norm(x) is not None for x in (paperA_name, paperB_name, paperNplus1_name, paperNplus2_name))

    if has_real_pairing:
        ancestor_questions = pairing_entry.get("ancestor_questions", []) if pairing_entry else []
        question = pairing_entry.get("question_the_sections_answer") if pairing_entry else None
    else:
        # True paperNplus3-only singleton -- Step 3 pulls this forward from file 3,
        # verbatim (fixed 2026-08-17), it does NOT compose anything fresh here.
        ancestor_questions = []
        question = None

    return {
        "direction": "papernplus3-to-pairing",
        "reason": "matched_one_direction_only" if found_match_forward(entry) else "no_counterpart_found",
        "diff_type": diff_type_forward(entry),
        "paperNplus3_section_name": entry.get("paperNplus3_section_name"),
        "paperNplus3_section_number": entry.get("paperNplus3_section_number"),
        "paperA_section_name": paperA_name,
        "paperA_section_number": paperA_num,
        "paperB_section_name": paperB_name,
        "paperB_section_number": paperB_num,
        "paperNplus1_section_name": paperNplus1_name,
        "paperNplus1_section_number": paperNplus1_num,
        "paperNplus2_section_name": paperNplus2_name,
        "paperNplus2_section_number": paperNplus2_num,
        "ancestor_pairing_status": entry.get("matched_pairing_status"),
        "basis": entry.get("basis"),
        "ancestor_questions": ancestor_questions,
        "question_the_sections_answer": question,
    }


def leftover_from_reverse(entry, pairing_lookup, warnings) -> dict:
    paperA_name = entry.get("pairing_paperA_section_name")
    paperA_num = entry.get("pairing_paperA_section_number")
    paperB_name = entry.get("pairing_paperB_section_name")
    paperB_num = entry.get("pairing_paperB_section_number")
    paperNplus1_name = entry.get("pairing_paperNplus1_section_name")
    paperNplus1_num = entry.get("pairing_paperNplus1_section_number")
    paperNplus2_name = entry.get("pairing_paperNplus2_section_name")
    paperNplus2_num = entry.get("pairing_paperNplus2_section_number")

    pairing_entry = lookup_pairing_entry(paperA_name, paperA_num, paperB_name, paperB_num, paperNplus1_name, paperNplus1_num, paperNplus2_name, paperNplus2_num, pairing_lookup, warnings)
    ancestor_questions = pairing_entry.get("ancestor_questions", []) if pairing_entry else []
    question = pairing_entry.get("question_the_sections_answer") if pairing_entry else None

    return {
        "direction": "pairing-to-papernplus3",
        "reason": "matched_one_direction_only" if found_match_reverse(entry) else "no_counterpart_found",
        "diff_type": diff_type_reverse(entry, warnings),
        "paperNplus3_section_name": entry.get("paperNplus3_section_name"),
        "paperNplus3_section_number": entry.get("paperNplus3_section_number"),
        "paperA_section_name": paperA_name,
        "paperA_section_number": paperA_num,
        "paperB_section_name": paperB_name,
        "paperB_section_number": paperB_num,
        "paperNplus1_section_name": paperNplus1_name,
        "paperNplus1_section_number": paperNplus1_num,
        "paperNplus2_section_name": paperNplus2_name,
        "paperNplus2_section_number": paperNplus2_num,
        "ancestor_pairing_status": entry.get("pairing_status"),
        "basis": entry.get("basis"),
        "ancestor_questions": ancestor_questions,
        "question_the_sections_answer": question,
    }


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    pairing_path = Path(sys.argv[2])
    with open(input_path, "r", encoding="utf-8") as f:
        combined = json.load(f)
    with open(pairing_path, "r", encoding="utf-8") as f:
        pairing_entries = json.load(f)

    if not isinstance(combined, dict) or "papernplus3-to-pairing" not in combined or "pairing-to-papernplus3" not in combined:
        raise ValueError(f"{input_path} must be a JSON object with 'papernplus3-to-pairing' and 'pairing-to-papernplus3' keys")

    pairing_lookup = build_pairing_lookup(pairing_entries)
    warnings = []

    fwd = combined["papernplus3-to-pairing"]
    rev = combined["pairing-to-papernplus3"]

    fwd_by_key = {}
    for e in fwd:
        k = key_of_forward(e)
        if k is not None:
            fwd_by_key.setdefault(k, []).append(e)
    rev_by_key = {}
    for e in rev:
        k = key_of_reverse(e)
        if k is not None:
            rev_by_key.setdefault(k, []).append(e)

    common_keys = set(fwd_by_key.keys()) & set(rev_by_key.keys())

    common = []
    for key in common_keys:
        for f in fwd_by_key[key]:
            for r in rev_by_key[key]:
                paperA_name = f.get("matched_pairing_paperA_section_name")
                paperA_num = f.get("matched_pairing_paperA_section_number")
                paperB_name = f.get("matched_pairing_paperB_section_name")
                paperB_num = f.get("matched_pairing_paperB_section_number")
                paperNplus1_name = f.get("matched_pairing_paperNplus1_section_name")
                paperNplus1_num = f.get("matched_pairing_paperNplus1_section_number")
                paperNplus2_name = f.get("matched_pairing_paperNplus2_section_name")
                paperNplus2_num = f.get("matched_pairing_paperNplus2_section_number")
                pairing_entry = lookup_pairing_entry(paperA_name, paperA_num, paperB_name, paperB_num, paperNplus1_name, paperNplus1_num, paperNplus2_name, paperNplus2_num, pairing_lookup, warnings)
                common.append({
                    "paperNplus3_section_name": f["paperNplus3_section_name"],
                    "paperNplus3_section_number": f["paperNplus3_section_number"],
                    "paperA_section_name": paperA_name,
                    "paperA_section_number": paperA_num,
                    "paperB_section_name": paperB_name,
                    "paperB_section_number": paperB_num,
                    "paperNplus1_section_name": paperNplus1_name,
                    "paperNplus1_section_number": paperNplus1_num,
                    "paperNplus2_section_name": paperNplus2_name,
                    "paperNplus2_section_number": paperNplus2_num,
                    "pairing_status": common_pairing_status(f.get("matched_pairing_status")),
                    "basis_papernplus3_to_pairing": f.get("basis"),
                    "basis_pairing_to_papernplus3": r.get("basis"),
                    "ancestor_questions": appended_ancestor_questions(pairing_entry),
                    "question_the_sections_answer": None,
                })

    def common_sort_key(e):
        n = e["paperNplus3_section_number"]
        return (n is None, n if n is not None else "")

    common.sort(key=common_sort_key)

    leftovers = []
    for e in fwd:
        k = key_of_forward(e)
        if k is None or k not in common_keys:
            leftovers.append(leftover_from_forward(e, pairing_lookup, warnings))
    for e in rev:
        k = key_of_reverse(e)
        if k is None or k not in common_keys:
            leftovers.append(leftover_from_reverse(e, pairing_lookup, warnings))

    def leftover_sort_key(e):
        n = e["paperNplus3_section_number"]
        return (e["direction"], n is None, n if n is not None else "")

    leftovers.sort(key=leftover_sort_key)

    if len(sys.argv) >= 4:
        output_dir = Path(sys.argv[3])
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = input_path.parent

    stem = input_path.name
    suffix = "-both-directions-section-mapping-by-paragraphs-and-questions.json"
    prefix = stem[: -len(suffix)] if stem.endswith(suffix) else input_path.stem

    common_path = output_dir / f"{prefix}-papernplus3-common-section-structure.json"
    leftover_path = output_dir / f"{prefix}-papernplus3-leftover-section-differences.json"

    with open(common_path, "w", encoding="utf-8") as f:
        json.dump(common, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(leftover_path, "w", encoding="utf-8") as f:
        json.dump(leftovers, f, indent=2, ensure_ascii=False)
        f.write("\n")

    needs_step3_common = len(common)
    needs_step3_leftover = sum(
        1 for e in leftovers
        if all(norm(e[k]) is None for k in ("paperA_section_name", "paperB_section_name", "paperNplus1_section_name", "paperNplus2_section_name"))
    )
    already_complete_leftover = len(leftovers) - needs_step3_leftover

    print(f"papernplus3-to-pairing pairings: {len(fwd)}")
    print(f"pairing-to-papernplus3 pairings: {len(rev)}")
    print(f"Confirmed five-way matches: {len(common)}  (ALL need Step 3 fresh composition)")
    for e in common:
        print(f"  [common] {e['paperNplus3_section_name']} <-> {e['paperA_section_name']} / {e['paperB_section_name']} / {e['paperNplus1_section_name']} / {e['paperNplus2_section_name']} ({e['pairing_status']})")
    print(f"Leftover entries: {len(leftovers)}  ({needs_step3_leftover} are true singletons -- need Step 3 PULL-FORWARD from paperNplus3's own file, not composition; {already_complete_leftover} already complete -- carried forward, do NOT touch in Step 3)")
    for e in leftovers:
        tag = "NEEDS PULL-FORWARD" if all(norm(e[k]) is None for k in ("paperA_section_name", "paperB_section_name", "paperNplus1_section_name", "paperNplus2_section_name")) else "already complete"
        print(f"  [leftover:{e['diff_type']}/{e['reason']}, ancestor={e['ancestor_pairing_status']}, {e['direction']}, {tag}] {e['paperNplus3_section_name']} <-> {e['paperA_section_name']} / {e['paperB_section_name']} / {e['paperNplus1_section_name']} / {e['paperNplus2_section_name']}")
    if warnings:
        print(f"\n{len(warnings)} WARNING(S):")
        for w in warnings:
            print(f"  - {w}")
    print(f"\nWrote {common_path}")
    print(f"Wrote {leftover_path}")
    print(f"\nNOTE: question_the_sections_answer is null on every CONFIRMED entry (Step 3 must compose those fresh) and on leftover entries tagged NEEDS PULL-FORWARD above (Step 3 must pull paperNplus3's own question_this_section_answers forward from file 3, verbatim -- NOT compose a new one). Leftover entries tagged 'already complete' must NOT be touched by Step 3 under the normal rule (but ARE still checked by Step 4's validator).")


if __name__ == "__main__":
    main()
```

The script prints, for every entry, whether it still needs Step 3 treatment (and which kind — fresh composition vs. pull-forward) or is already complete — use that report directly rather than re-deriving which entries need which treatment by hand.

### Step 3: Set `question_the_sections_answer` — compose fresh for confirmed matches, pull forward for true singletons, leave everything else alone

Process only:

1. **Every entry in the common-structure file** (all of them — a confirmed match always has 2+ sides present, a genuine correlation, so it always needs a freshly composed question). Look up the actual paragraph content for each side present on that entry: `paperNplus3_paragraphs` from file 3 when `paperNplus3_section_name` isn't null; `paperA_paragraphs`/`paperB_paragraphs`/`paperNplus1_paragraphs`/`paperNplus2_paragraphs` from file 2's matching entry when the corresponding name isn't null. If every side you looked up has zero paragraphs, leave `question_the_sections_answer` as `null` (the empty-content exact-title-fallback exception, same as every earlier generation). Otherwise, read every title and paragraph for the present side(s), then compose **one new question** written fresh from that content — never copy, trim, or merge any entry from `ancestor_questions`, and never copy a directional pass's own pre-existing question. Same role-based framing, same short-and-genuinely-open rule, same type-narrow-question vigilance as every earlier generation.
2. **Leftover entries where `paperA_section_name`, `paperB_section_name`, `paperNplus1_section_name`, AND `paperNplus2_section_name` are all `null`** — a true paperNplus3-only singleton, nothing else present to correlate against. **Fixed 2026-08-17: don't compose. Pull the existing question forward instead** — copy paperNplus3's own `question_this_section_answers` value from file 3, matched by `paperNplus3_section_number`/`paperNplus3_section_name`, byte-for-byte. Don't reword or "clean up" it. (If file 3's own value for that section is itself null — unusual — leave `question_the_sections_answer` as `null` too; don't invent a replacement.)

**Leave every other leftover entry completely untouched in this step** — its `question_the_sections_answer` and `ancestor_questions` were already set by Step 2's carry-forward logic. (Step 4 below is the one place that carried-forward entry is revisited, and only if it turns out its carried-forward value was never actually composed or pulled forward at all.)

Once all needed entries are processed, rewrite both files with their full, updated arrays, in the same order Step 2 produced.

### Step 4: Validate Step 3 is complete (hard gate — do not proceed until this passes)

Step 3 is a reasoning-and-lookup step, and steps like that are the ones that get skipped or left half-done. This is exactly what happened in a real 5-paper corpus run: the "Findings and Future Work" / "General Discussion" alignable leftover entry — a pairing with real `ancestor_questions` content going back multiple generations — reached this generation's final output with `question_the_sections_answer` still `null`, because an earlier generation's own Step 3 pass never actually composed a value for that lineage in the first place. This generation's carry-forward rule correctly passed that gap along untouched (there was nothing new to confirm), which is exactly how it stayed invisible until someone went looking. This step exists to catch that mechanically, every run, rather than trusting that Step 3 — this generation's or any earlier one's — actually finished. **Do not report this skill's output as done, and do not treat the resulting five-paper structure as final, until this step passes clean.**

The check below applies uniformly to **every entry in both files**, common-structure and leftover alike, regardless of whether Step 3 was supposed to touch it this generation.

Copy the script below byte-for-byte into a local file (e.g. `validate_papernplus3_step3_complete.py`) — this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant. Then run it with the two files Step 2/3 just wrote plus the same two paragraph-source files (2 and 3) already used in Step 3:

```bash
python3 validate_papernplus3_step3_complete.py {prefix}-papernplus3-common-section-structure.json {prefix}-papernplus3-leftover-section-differences.json {paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-sections-with-paragraphs-and-questions.json {paperNplus3-name}-sections-with-paragraphs-and-questions.json
```

```python
#!/usr/bin/env python3
"""
Validates that {prefix}-papernplus3-common-section-structure.json and
{prefix}-papernplus3-leftover-section-differences.json satisfy Step 3's completeness rule:
EVERY entry in both files -- common-structure and leftover alike, including entries this
generation's Step 3 deliberately left untouched because they were supposed to already carry
a correct, previously-composed or previously-pulled-forward question forward -- has a real,
non-null question_the_sections_answer, UNLESS every side actually present on that entry has
zero paragraphs (the one legitimate empty-content case Step 3 itself allows).

A carried-forward entry that turns out to have a null question despite real content present
means an EARLIER generation's own Step 3 was itself incomplete -- this validator does not
care which generation was "responsible"; it only checks whether a real question exists now.
This is precisely the bug this validator was written to catch: a real 5-paper run left the
"Findings and Future Work" / "General Discussion" leftover entry null all the way to the
final generation despite real ancestor content, because no earlier Step 3 pass ever actually
composed a value for it.

Paragraph counts are looked up from the same two paragraph-source files Step 2/3 already
require (the four-paper pairing file for paperA/paperB/paperNplus1/paperNplus2 paragraphs,
paperNplus3's own sections-with-paragraphs-and-questions.json for paperNplus3 paragraphs) --
never re-derived, assumed, or trusted just because a value was carried forward from elsewhere.

Exit 0: every entry either has a real question or is verified legitimately empty -- Step 3
(across every generation that touched this lineage) is genuinely complete, safe to treat the
five-paper structure as final.
Exit 1: one or more entries are missing a question with real content present. Do not report
success. Go back, compose (common-structure entries) or pull forward (singleton leftover
entries) a real question for every entry listed below, rewrite both files, and re-run this
validator. This applies even to a carry-forward leftover entry Step 3 would ordinarily leave
untouched.

Usage:
    python3 validate_papernplus3_step3_complete.py common.json leftover.json four-paper-pairing-file.json paperNplus3-file.json
"""
import json
import sys
from pathlib import Path


def norm(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def side_key(number, name):
    num = norm(number)
    if num is not None:
        return ("num", num)
    n = norm(name)
    return ("name", n) if n is not None else None


def build_flat_lookup(sections):
    lookup = {}
    for e in sections:
        key = side_key(e.get("section_number"), e.get("section_name"))
        if key is not None:
            lookup[key] = e.get("paragraphs", [])
    return lookup


def build_pairing_side_lookup(pairing_entries, side):
    name_field = f"paper{side}_section_name"
    num_field = f"paper{side}_section_number"
    para_field = f"paper{side}_paragraphs"
    lookup = {}
    for e in pairing_entries:
        key = side_key(e.get(num_field), e.get(name_field))
        if key is not None:
            lookup[key] = e.get(para_field, [])
    return lookup


def paragraph_count(lookup, number, name, missing_lookups):
    if norm(name) is None:
        return 0  # side not present on this entry at all -- not counted
    key = side_key(number, name)
    if key is None or key not in lookup:
        missing_lookups.append((name, number))
        return None  # unverifiable -- do NOT treat as legitimately empty
    return len(lookup[key])


def main():
    common_path, leftover_path, pairing_path, paperNplus3_path = (Path(a) for a in sys.argv[1:5])
    common = json.load(open(common_path, encoding="utf-8"))
    leftover = json.load(open(leftover_path, encoding="utf-8"))
    pairing_entries = json.load(open(pairing_path, encoding="utf-8"))
    paperNplus3_sections = json.load(open(paperNplus3_path, encoding="utf-8"))

    lookups = {
        "A": build_pairing_side_lookup(pairing_entries, "A"),
        "B": build_pairing_side_lookup(pairing_entries, "B"),
        "Nplus1": build_pairing_side_lookup(pairing_entries, "Nplus1"),
        "Nplus2": build_pairing_side_lookup(pairing_entries, "Nplus2"),
        "Nplus3": build_flat_lookup(paperNplus3_sections),
    }
    sides = ["A", "B", "Nplus1", "Nplus2", "Nplus3"]
    missing_lookups = []

    def present_side_counts(e):
        counts = []
        for s in sides:
            name = e.get(f"paper{s}_section_name")
            if norm(name) is None:
                continue
            num = e.get(f"paper{s}_section_number")
            c = paragraph_count(lookups[s], num, name, missing_lookups)
            counts.append((s, name, c))
        return counts

    violations = []
    for kind, entries in (("common-structure", common), ("leftover", leftover)):
        for e in entries:
            if e.get("question_the_sections_answer") is not None:
                continue
            counts = present_side_counts(e)
            if not counts:
                continue
            if all(c == 0 for _, _, c in counts):
                continue
            violations.append((kind, e, counts))

    if violations:
        print(f"BLOCKED: {len(violations)} entries have a missing question_the_sections_answer "
              f"that is NOT legitimately empty-content. Step 3 (this generation's or an "
              f"earlier one's) is incomplete -- do not treat this structure as final. "
              f"Compose (common-structure) or pull forward (singleton leftover) a real "
              f"question for each entry below, rewrite both files, and re-run this validator.")
        for kind, e, counts in violations:
            sides_desc = ", ".join(f"{s}={name!r}({c} paragraphs)" for s, name, c in counts)
            print(f"  [{kind}] {sides_desc}")
        if missing_lookups:
            print(f"\n{len(missing_lookups)} paragraph lookup(s) could not be resolved against "
                  f"the pairing/paperNplus3 files -- these count as unverified, not empty:")
            for name, num in missing_lookups:
                print(f"  - {name!r} ({num!r})")
        sys.exit(1)

    print(f"Step 3 validation passed: {len(common)} common-structure + {len(leftover)} leftover "
          f"entries all have a real question or are verified legitimately empty. Safe to report.")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

If the script exits 0, move on to Step 5. **If it exits 1**, it lists every entry with a missing `question_the_sections_answer` that isn't legitimately empty-content — go back and compose (common-structure) or pull forward (a true singleton leftover) a real question for each one listed, following the same discipline as Step 3. This applies even to an entry you'd otherwise leave untouched under Step 3's normal carry-forward rule — if the validator flags it, its question is genuinely missing, full stop. Rewrite both files, and re-run this validator. Repeat until it passes clean before moving on.

### Step 5: Report to the user

State the counts: how many confirmed five-way matches, how many leftovers, how many of those leftovers were true singletons (question pulled forward from paperNplus3's own file) vs. carried forward unchanged. Flag any `null` questions from the empty-content case, and proactively point out any entry where the current `question_the_sections_answer` looks notably narrower than the most recent entry in `ancestor_questions`. Confirm Step 4's validator exited 0 before reporting anything as done — if Step 4 caught and fixed a gap left by an earlier generation, mention that explicitly (which entries, and roughly how far back the gap traced) rather than folding it silently into the final counts.

## Output

Two files, both saved in the same directory as the input unless the user specifies otherwise:

| File | Contents |
|---|---|
| `{prefix}-papernplus3-common-section-structure.json` | Five-way correspondences both directional passes independently agree on, each with a freshly-composed question and an `ancestor_questions` list appended with the just-superseded four-paper question |
| `{prefix}-papernplus3-leftover-section-differences.json` | Every remaining entry, each tagged `alignable`/`non-alignable`; entries with a real pairing on any side carry their prior question/ancestor_questions forward unchanged (backfilled by Step 4 if that carried value turns out to have been missing); true singleton entries (no real pairing at all) get paperNplus3's own question pulled forward verbatim, not freshly composed |

`{prefix}` is the input filename with `-both-directions-section-mapping-by-paragraphs-and-questions.json` stripped (typically `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-{paperNplus3-name}`). Both files are only considered finished once Step 4's validator has exited 0 against them.

### Output schema (strict)

**`{prefix}-papernplus3-common-section-structure.json`** — a JSON array:

```json
{
  "paperNplus3_section_name": "string",
  "paperNplus3_section_number": "string or null",
  "paperA_section_name": "string or null",
  "paperA_section_number": "string or null",
  "paperB_section_name": "string or null",
  "paperB_section_number": "string or null",
  "paperNplus1_section_name": "string or null",
  "paperNplus1_section_number": "string or null",
  "paperNplus2_section_name": "string or null",
  "paperNplus2_section_number": "string or null",
  "pairing_status": "string -- freshly computed for THIS confirmed match: common-structure only if the ancestor four-paper pairing was ALSO common-structure; alignable-diff otherwise, including when the ancestor was non-alignable-diff",
  "basis_papernplus3_to_pairing": "string",
  "basis_pairing_to_papernplus3": "string",
  "ancestor_questions": "array of strings, oldest first -- the matched pairing's own PRIOR ancestor_questions list with that pairing's own now-superseded question_the_sections_answer appended. Set by Step 2's script, not Step 3.",
  "question_the_sections_answer": "string composed fresh in Step 3 (a confirmed entry always has 2+ sides present, never a singleton), verified non-null (or legitimately null on empty content) by Step 4"
}
```

`paperNplus3_section_name` is always non-null. At least one of `paperA_section_name`/`paperB_section_name`/`paperNplus1_section_name`/`paperNplus2_section_name` is always non-null, but none of the four is individually guaranteed.

**`{prefix}-papernplus3-leftover-section-differences.json`** — a JSON array:

```json
{
  "direction": "\"papernplus3-to-pairing\" or \"pairing-to-papernplus3\"",
  "reason": "\"no_counterpart_found\" or \"matched_one_direction_only\" -- a RAW fact about this one pass, independent of diff_type",
  "diff_type": "freshly computed, NOT derived from reason: \"alignable\" if this pass found a real unidirectional match; if this pass found nothing, \"non-alignable\" only if ancestor_pairing_status was ALREADY non-alignable-diff, otherwise \"alignable\"",
  "paperNplus3_section_name": "string or null",
  "paperNplus3_section_number": "string or null",
  "paperA_section_name": "string or null",
  "paperA_section_number": "string or null",
  "paperB_section_name": "string or null",
  "paperB_section_number": "string or null",
  "paperNplus1_section_name": "string or null",
  "paperNplus1_section_number": "string or null",
  "paperNplus2_section_name": "string or null",
  "paperNplus2_section_number": "string or null",
  "ancestor_pairing_status": "string, or null only when direction is papernplus3-to-pairing and reason is no_counterpart_found -- the underlying pairing's own PRIOR status, preserved verbatim, NOT this entry's own current classification (that's diff_type)",
  "basis": "string, carried over unchanged from the source entry",
  "ancestor_questions": "array of strings -- CARRIED FORWARD UNCHANGED from the matched pairing entry if any of paperA/paperB/paperNplus1/paperNplus2 is non-null, or [] if none are (a true paperNplus3-only singleton)",
  "question_the_sections_answer": "string -- carried forward unchanged if any of paperA/paperB/paperNplus1/paperNplus2 is non-null (and verified by Step 4 to be genuinely non-null, backfilled there if it wasn't); PULLED FORWARD verbatim from paperNplus3's own question_this_section_answers (file 3) -- not composed -- only when all four are null (fixed 2026-08-17)"
}
```

Whether an entry's `question_the_sections_answer`/`ancestor_questions` were carried forward, freshly composed, or pulled forward is fully determined by whether `paperA_section_name`, `paperB_section_name`, `paperNplus1_section_name`, and `paperNplus2_section_name` are all null on that entry — not by `direction` alone. `reason` and `diff_type` are two SEPARATE facts, computed independently and can diverge.

## Common mistakes to avoid

- **Recomposing `question_the_sections_answer` for every leftover entry in Step 3, the way the papernplus1-family original does.** This skill deliberately does NOT do that in the normal case — see "What this is and isn't" above. Only common-structure entries get fresh composition; true paperNplus3-only singleton leftovers get a pull-forward lookup instead; carried-forward entries are only revisited if Step 4 flags them.
- **Composing a brand-new question for a true singleton leftover entry instead of pulling paperNplus3's own `question_this_section_answers` forward verbatim — fixed 2026-08-17.** A singleton has nothing to correlate against; recomposing its question is wasted work with a real risk of drift from the already-correct text sitting in file 3.
- **Rewording, paraphrasing, or "improving" a pulled-forward singleton question.** Copy it byte-for-byte from file 3, same discipline as every other pull-forward in this family.
- **Assuming "forward-direction leftover" and "needs fresh composition" are the same thing.** The correct test is whether all four of paperA/paperB/paperNplus1/paperNplus2 are null (pull forward from file 3) or at least one is non-null (leave alone), not which pass produced the entry.
- **Replacing `ancestor_questions` instead of appending to it on confirmed entries.**
- **Appending to `ancestor_questions` on a carried-forward leftover entry.**
- **Running Step 2's script without the four-paper pairing file as its second argument.**
- **Requiring all four of paperA_section_name/paperB_section_name/paperNplus1_section_name/paperNplus2_section_name to be non-null on a confirmed entry.** Not guaranteed — same relaxation as every earlier generation, extended one more level.
- **Opening a PDF at any point.**
- **Discarding `basis_papernplus3_to_pairing`/`basis_pairing_to_papernplus3` or merging them into one field on common-structure entries.**
- **Recomputing `diff_type` from `reason` or vice versa.** `reason` is a raw fact about whether this pass found a match; `diff_type` also consults `ancestor_pairing_status` when the pass found nothing.
- **Treating "paperNplus3 found no match" as automatically non-alignable.** This was the actual bug in the two earlier generations, caught 2026-08-16 and fixed at the time — don't reintroduce it here: `diff_type_reverse`'s "no match" branch must check `ancestor_pairing_status` first.
- **Assuming a confirmed entry's `pairing_status` always equals the ancestor pairing's status.** It's freshly computed via `common_pairing_status`: common-structure only if the ancestor was ALSO common-structure.
- **Confusing entries in `ancestor_questions` with `question_the_sections_answer`, or treating a gap between them as an error.** The gap is the point, for genuinely multi-sided confirmed entries.
- **Adding a sixth bespoke field set if a sixth paper is ever requested.** This generation is the planned cap — see "What this is and isn't" above.
- **Assuming a thin or all-`non-alignable` leftover file proves the source papers really have nothing else in common.** This skill only reorganizes and describes whatever entries the upstream `directional-section-mapping-paragraphs-and-questions-papernplus3`/`pairing-to-papernplus3-mapping-by-paragraphs-and-questions` passes already produced — the mesotext Appendix C example in the "buried narrow role" awareness note above is a real case where the correct entries only existed because the upstream passes found them at the paragraph level.
- **Skipping Step 4, or treating it as optional.** It's a hard gate, added 2026-08-16 specifically because a real 5-paper corpus run reached this generation's own final output with a leftover entry's question still null despite real, multi-generation ancestor content — the exact kind of gap this step exists to catch. Treat the output as final only after Step 4 exits 0.
- **Treating a Step 4 violation on a carried-forward leftover entry as "not this generation's problem" and leaving it null.** The validator doesn't care which generation was originally responsible — if the question is missing now and real content is present, compose or pull it forward now. This generation, being the last in the planned 5-paper cap, is also the last chance to catch a gap like this before it becomes the permanent final record.
- **Treating Step 4 as read-only / advisory and moving on anyway when it exits 1.** Exit 1 means go back, fix the missing questions it lists, rewrite both files, and re-run the validator — not "note the warning and continue."
- **Writing a custom variant of either Step 2's or Step 4's bundled script instead of copying it verbatim, or "fixing" its behavior for a specific entry.** Both scripts are mechanical and fixed — if either flags or produces something that looks wrong, that's a signal to check the underlying data (the both-directions file, the four-paper pairing file), not to rewrite the script.
