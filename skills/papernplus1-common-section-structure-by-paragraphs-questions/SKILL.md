---
name: "papernplus1-common-section-structure-by-paragraphs-questions"
description: "The papernplus1-family analog of \"common-section-structure-by-paragraphs-and-questions\". Given papernplus1-both-directions-mapping's combined output plus the two-paper pairing file and the third paper's own sections-with-paragraphs-and-questions.json, writes {prefix}-papernplus1-common-section-structure.json and {prefix}-papernplus1-leftover-section-differences.json. Multi-sided entries get a freshly-composed question_the_sections_answer; true single-sided (singleton) leftover entries pull their existing question forward verbatim instead of recomposing (fixed 2026-08-17). Gated by a hard Step 4 validator (2026-08-16) that blocks completion until every entry needing a question actually has one. pairing_status/diff_type freshly computed per generation. No normalize step needed. No PDF opened. Use when the user wants confirmed three-paper section correspondences."
---

# PaperNplus1 Common Section Structure (by Paragraphs and Questions)

## What this is (and isn't)

This is the papernplus1-family analog of `common-section-structure-by-paragraphs-and-questions`: a downstream step on top of `papernplus1-both-directions-mapping-by-paragraphs-and-questions`'s combined output. It splits every entry from both passes into two files — the three-way correspondences (a paperNplus1 section, a paperA section, and/or a paperB section) that both directional passes independently agree on, and everything else. The structural join itself is mechanical (a script), but for every entry in both output files, this skill also determines one question the entry's present section(s) together answer — composing a genuinely new one when multiple sides are actually present to correlate, or pulling an existing one forward verbatim when only one side is present at all (see the fix below). It opens no PDF.

**No normalize step is needed first, unlike the base two-paper pipeline.** The base pipeline's `common-section-structure-by-paragraphs-and-questions` requires `normalize-section-mapping-both-directions`'s output specifically, because that pipeline's raw combined file reuses `paper1_*`/`paper2_*` as role labels that mean different actual papers in each array. Here, `paperA`, `paperB`, and `paperNplus1` are fixed identity labels — `matched_pairing_paperA_*` (in `papernplus1-to-pairing`) and `pairing_paperA_*` (in `pairing-to-papernplus1`) always refer to the same actual paper in both arrays, just under different field-name prefixes. This skill's bundled script already knows that correspondence and reads the raw both-directions combined file directly — there is no `-normalized.json` intermediate in this family.

**Departure from the base skill worth calling out explicitly:** in the base skill's common-structure file, every confirmed entry has both `paperA_section_name` and `paperB_section_name` non-null, because a two-paper pairing that's missing a side can never be "confirmed" — it's definitionally a leftover. Here, a confirmed three-way match legitimately *can* have one of `paperA_section_name`/`paperB_section_name` null: if the underlying pairing itself was already an `alignable-diff` or `non-alignable-diff` (one side present, or neither side bidirectionally confirmed between paperA and paperB), a paperNplus1 section can still independently, bidirectionally confirm against it. That's new information the two-paper comparison alone couldn't have produced — paperNplus1 has content matching a section that only paperA (or only paperB) has — and it belongs in the confirmed file, not the leftovers, even though `paperA_section_name`/`paperB_section_name` aren't both present.

**Every script in this skill's Workflow (Steps 2 and 4) is given verbatim and must be copied byte-for-byte, never authored or modified.** Wherever a step says "write the script," that means transcribe the exact code shown into a file — not compose a variant, not add a flag, not adjust behavior for a specific entry or case. If a script's documented behavior seems wrong for a specific situation, that's a stop-and-ask-the-user moment, not a reason to write custom logic (see `extract-paragraphs-as-pseudo-sections`'s "Stage 0 is strictly mechanical" section for the real incident this rule generalizes from).

**`pairing_status` and `diff_type` are freshly computed each run, not carried over — correction, 2026-08-16.** An earlier version of this skill set a leftover entry's alignment classification purely by checking whether paperNplus1 itself had a name, and set a confirmed entry's `pairing_status` by blindly copying whatever the matched two-paper pairing already had. Both were wrong in the same way: they conflated "paperNplus1 doesn't participate here" with "nothing aligns with this at all." A real example caught this — AbstractExplorer and CorpusStudio both have a dedicated survey-wording appendix (a genuine, already-confirmed two-paper pairing); Examplore simply has no counterpart section for it. The old logic stamped that `non-alignable-diff` purely because Examplore was silent, discarding the fact that AbstractExplorer and CorpusStudio still validly align with each other. The corrected rule, for both confirmed and leftover entries: a fresh bidirectional confirmation is `common-structure` only if the ancestor pairing was *already* `common-structure` (monotonic — once broken, it's never regained just because a later paper agrees); otherwise `alignable-diff`, including when the ancestor was `non-alignable-diff` (a genuine confirmation just happened, so it can no longer be "nothing aligns with this"). A leftover with *no* match found for paperNplus1 is `non-alignable` only if the ancestor pairing was *already* `non-alignable-diff` — otherwise it's `alignable`, since the earlier two papers still align with each other even though paperNplus1 doesn't participate. `reason` (`no_counterpart_found` / `matched_one_direction_only`) stays a separate, raw fact about whether paperNplus1's own pass found a match at all — it no longer drives `diff_type`, and vice versa. Leftover entries carry the ancestor's own prior status under a renamed field, `ancestor_pairing_status` (not `pairing_status` — that name was ambiguous between "this entry's own current classification" and "the pairing's historical one," which is exactly what caused the bug to go unnoticed). A related bug in the downstream merge skill (`papernplus1-pairings-with-paragraphs-and-questions`) hardcoded every confirmed entry's `pairing_status` to the literal string `"common-structure"` regardless of what this skill's own common-structure file said — that's fixed too, so the corrected value now actually survives into the three-paper pairing file a 4th-paper fold-in reads from.

**Multi-sided entries get one question, composed fresh; true single-sided (singleton) entries pull their existing question forward instead — correction, 2026-08-17.** Earlier versions of this skill carried over both `question_papernplus1_to_pairing` and `question_pairing_to_papernplus1` on every common-structure entry, mirroring how both `basis` fields are kept; those two questions turned out to be near-duplicates of each other often enough to add no value, so common-structure entries now get one composed question instead (the two `basis` fields do stay genuinely distinct and are still both kept). That fresh-composition treatment was later extended to the leftover file too — but a subsequent correction narrowed it again: a leftover entry with **exactly one** of `paperA_section_name`/`paperB_section_name`/`paperNplus1_section_name` present is a true singleton, with nothing else to correlate its content against, and composing a "new" question for it was pure, needless rework — that single section already has its own perfectly good, previously-computed question sitting in its own source file (or, for a paperA/paperB singleton, in `ancestor_questions`, which by this point already holds that section's own pulled-forward original question — see the base-skill fix this one extends). The corrected rule: **only compose a genuinely new question when 2 or 3 sides are actually present together on an entry** (a real correlation is happening, so a real new question is warranted); **for a true singleton, pull the existing question forward verbatim instead** — see Step 3 below for exactly where each existing question comes from depending on which side is the lone one present. This mirrors, one level up, the exact same fix already applied to `directional-section-mapping-by-paragraphs-and-questions` (the skill whose own no-match entries populate `ancestor_questions` here in the first place).

**Narrowing across successive papers, and why `ancestor_questions` exists.** When paperA and paperB's two-paper pairing already answered one broad question (e.g. "what are the system's core components, how do they work together, and how is the system built?"), and paperNplus1 draws a finer distinction than either paperA or paperB did on their own (e.g. treating "design rationale," "usage walkthrough," and "backend pipeline" as three separate sections instead of one), the resulting three-way entries necessarily answer something narrower than the original two-paper pairing did — and each additional paper folded in afterward is another chance to narrow further, compounding over time. That narrowing is often correct (the finer paper really does treat these as distinct concerns), but it can silently leave out content the original two-paper question covered and no single three-way entry now speaks to. Rather than trying to prevent or auto-detect narrowing, this skill makes it visible: every entry that involves a real pairing (i.e., `paperA_section_name` and/or `paperB_section_name` is non-null) carries an `ancestor_questions` field — a **list**, not a single string. At this stage of the pipeline (folding in a third paper), the list holds at most one entry: the underlying two-paper pairing's own original question, copied verbatim from the pairing file, not re-derived or paraphrased. It's a list rather than a scalar specifically so that a future fourth, fifth paper folded in later can *append* that generation's own now-superseded question onto the same field, rather than overwriting it — preserving the full narrowing lineage (oldest question first), not just the most recent hop. A reader can then always compare the most recent entry in `ancestor_questions` (or all of them) against `question_the_sections_answer` to see how much of the original scope this particular entry actually covers, and judge for themselves whether anything important got left out along the way. Populating `ancestor_questions` is a pure lookup, not a reasoning step — it's computed by the Step 2 script, not composed in Step 3. Any skill in this family that later folds in a further paper on top of this one's output must *append* to this list, never replace or truncate it — that append behavior is out of scope for this version of the skill, which only ever produces a list of length 0 or 1, but is documented here so a future extension gets it right.

**Awareness note: this skill can't recover a role that was never split out upstream.** Every join here is mechanical (Step 2's script) and question composition (Step 3) only ever reads paragraphs the upstream directional-mapping passes already assigned to a given entry — this skill never re-reads a section from scratch to check whether it should have been split differently. If paperNplus1 (or the underlying pairing) folds a narrow role into a much broader section without its own heading, and `directional-section-mapping-paragraphs-and-questions-papernplus1` / `pairing-to-papernplus1-mapping-by-paragraphs-and-questions` failed to split that role into its own entry upstream, there's nothing for this skill to notice or fix after the fact. See those two skills' "buried narrow role" guidance for the full explanation and a real example.

**Step 3 completeness is now a hard gate (added 2026-08-16), not an honor system.** Real corpus runs of this family surfaced entries — including ones in a *later* generation's leftover file that carry this generation's question forward — where a Step 3 composition pass was silently skipped or left half-finished, and the resulting `null` only became visible several fold-ins later, far from where it actually went wrong. Step 4 below re-checks every entry mechanically before this skill is allowed to be reported as done, specifically so an incomplete Step 3 is caught here, at the source, rather than surfacing as a mystery null two or three papers later. This gate stays in place even after the 2026-08-17 pull-forward fix — it's just as easy to silently skip a pull-forward as a composition, and Step 4 doesn't care which kind of gap it's catching.

## Inputs

Three files:

1. The combined output of `papernplus1-both-directions-mapping-by-paragraphs-and-questions`, named `{paperA-name}-{paperB-name}-{paperNplus1-name}-both-directions-section-mapping-by-paragraphs-and-questions.json` — a JSON object with exactly two keys, `papernplus1-to-pairing` (entries with `paperNplus1_section_name`/`_number`, `matched_pairing_paperA_*`, `matched_pairing_paperB_*`, `matched_pairing_status`, `basis`, `question_the_sections_answer`) and `pairing-to-papernplus1` (entries with `pairing_paperA_*`, `pairing_paperB_*`, `pairing_status`, `paperNplus1_section_name`/`_number`, `basis`, `question_the_sections_answer`).
2. The two-paper pairing file, `{paperA-name}-{paperB-name}-sections-with-paragraphs-and-questions.json` — from `section-pairings-with-paragraphs-and-questions`. Used three times: mechanically in Step 2 (the script reads it directly now, to look up each matched pairing's own `question_p1_p2`/`question_p2_p1` for the new `ancestor_questions` field), again in Step 3's reasoning pass (to look up the actual `paperA_paragraphs`/`paperB_paragraphs` for composing `question_the_sections_answer`, and to source a paperA/paperB singleton's pulled-forward question via `ancestor_questions`), and again in Step 4's validator (same paragraph lookup, to check whether a missing question is legitimately empty-content).
3. The third paper's own `{paperNplus1-name}-sections-with-paragraphs-and-questions.json` — from `orchestrator-extract-sections-paragraphs-and-questions`. Gives Step 3 (and Step 4) the actual `paragraphs` for the paperNplus1 side of each entry, and — for a paperNplus1-only singleton — its own precomputed `question_this_section_answers` to pull forward.

All three filenames must use the literal PDF-filename prefixes (minus `.pdf`) already established earlier in the pipeline — don't guess or reformat; ask if any isn't evident.

## Workflow

### Step 1: Confirm the inputs

Check file 1 is a JSON object with exactly `papernplus1-to-pairing` and `pairing-to-papernplus1` as its top-level keys. If instead you only have the two separate intermediate files (not yet combined), either combine them yourself into this shape or run `papernplus1-both-directions-mapping-by-paragraphs-and-questions` to produce the combined file properly. Confirm files 2 and 3 are also present — Step 2 needs file 2 for the `ancestor_questions` lookup, and Steps 3 and 4 can't compose, pull forward, or verify real questions for either output file without files 2 and 3.

### Step 2: Run the matching script

Don't do this by hand — it's a mechanical three-way key comparison across two arrays that can each run to dozens of entries, plus a lookup into a third file for `ancestor_questions`, and a script won't misremember an entry or which array it came from. This step performs the structural join and the ancestor-question lookup (both mechanical); it does not compose or pull forward `question_the_sections_answer` (that's Step 3, for both output files).

Copy the script below byte-for-byte into a local file (e.g. `find_papernplus1_bidirectional_matches.py`, in the same directory as the input files) — this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant. Then run it with **both** file 1 and file 2:

```bash
python3 find_papernplus1_bidirectional_matches.py {paperA-name}-{paperB-name}-{paperNplus1-name}-both-directions-section-mapping-by-paragraphs-and-questions.json {paperA-name}-{paperB-name}-sections-with-paragraphs-and-questions.json
```

```python
#!/usr/bin/env python3
"""
Reads the combined output of papernplus1-both-directions-mapping-by-paragraphs-and-questions
(a JSON object with "papernplus1-to-pairing" and "pairing-to-papernplus1" keys) plus the
two-paper pairing file, and splits every both-directions entry into two files:

  - {prefix}-papernplus1-common-section-structure.json     confirmed three-way matches
  - {prefix}-papernplus1-leftover-section-differences.json  everything else

Unlike the base two-paper common-section-structure script, NO prior normalization step is
needed here: paperA/paperB/paperNplus1 are stable identity labels in both arrays (never
reassigned per-pass the way paper1/paper2 are in the base pipeline), so this script can
read the raw both-directions combined file directly.

Matching is done on section NUMBER, falling back to exact section NAME only for unnumbered
sections, same convention as every join in this family.

A three-way match is "confirmed" only when the SAME (paperNplus1 section, paperA section,
paperB section) identity is independently found from both directions: paperNplus1's own
best-match pass picked that pairing, AND the pairing's own best-match pass picked that
paperNplus1 section. Everything else is a leftover.

pairing_status / diff_type semantics (fixed 2026-08-16 -- see "Correction" note below):
  - CONFIRMED entries get a freshly computed `pairing_status`: "common-structure" only if
    the ancestor two-paper pairing was ALSO common-structure (monotonic -- once broken,
    never regained); "alignable-diff" otherwise, including when the ancestor was
    non-alignable-diff (a bidirectional confirmation just happened, so it can't still be
    "nothing aligns with this").
  - LEFTOVER entries get a freshly computed `diff_type`: "alignable" if THIS pass found a
    real unidirectional match (regardless of the ancestor's own status); if this pass found
    NOTHING, "non-alignable" only if the ancestor pairing was ALREADY non-alignable-diff
    (genuinely isolated content) -- otherwise "alignable", since the earlier papers still
    align with each other even though paperNplus1 doesn't participate. `reason`
    ("no_counterpart_found" / "matched_one_direction_only") is a separate, raw fact about
    whether THIS pass found a match at all -- it no longer drives diff_type, and vice versa.
  - LEFTOVER entries also carry `ancestor_pairing_status`: the underlying pairing's own
    PRIOR status, preserved verbatim (not recomputed) -- this is what `diff_type` and
    `common_pairing_status` read to make their fresh-generation decision, and what a future
    generation's fold-in would read in turn.

Correction, 2026-08-16: the original version of this script computed diff_type_reverse and
common-entry pairing_status by checking ONLY whether paperNplus1 had a name at all, ignoring
whether the ancestor pairing already had real cross-paper alignment. That conflated "the
newest paper is silent on this" with "nothing aligns with this anywhere" -- e.g. a pairing
where paperA and paperB both confirm each other, and paperNplus1 simply has no counterpart,
was wrongly classified non-alignable-diff instead of alignable-diff. See "What this is and
isn't" above for the caught example (AbstractExplorer/CorpusStudio's shared survey appendix,
which Examplore doesn't have).

Every entry in EITHER output file that has a real paperA and/or paperB side also gets an
ancestor_questions field: a LIST containing the underlying two-paper pairing's own original
question (question_p1_p2, falling back to question_p2_p1 if that's null), copied verbatim
from the pairing file -- not re-derived. It's a list (not a single string) so that folding
in a 4th, 5th paper later can append each successive generation's now-superseded question
onto the same field, preserving the full narrowing lineage rather than only the most recent
hop. At this stage (folding in the 3rd paper), the list holds at most one entry. This is a
pure lookup, included here in the script because it needs no judgment, unlike
question_the_sections_answer (composed or pulled forward in Step 3 of the skill's workflow,
which this script does NOT set on either file).

Usage:
    python3 find_papernplus1_bidirectional_matches.py combined-both-directions.json pairing-file.json [output_dir]
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


def build_pairing_question_lookup(pairing_entries):
    """Keys on the joint (paperA_side_key, paperB_side_key) tuple -- a pairing-file entry
    is a property of the WHOLE pairing, not either side alone, so both sides of the key
    matter (including when one side is None, e.g. an alignable-diff/non-alignable-diff
    pairing with only one side present)."""
    lookup = {}
    for e in pairing_entries:
        a_key = side_key(e.get("paperA_section_number"), e.get("paperA_section_name"))
        b_key = side_key(e.get("paperB_section_number"), e.get("paperB_section_name"))
        lookup[(a_key, b_key)] = {
            "question_p1_p2": e.get("question_p1_p2"),
            "question_p2_p1": e.get("question_p2_p1"),
        }
    return lookup


def ancestor_questions_for(paperA_name, paperA_num, paperB_name, paperB_num, pairing_lookup, warnings):
    """Returns a LIST (0 or 1 entries at this stage of the pipeline). Empty list if this
    entry has no real pairing to point back to at all (both sides null -- only possible on
    a leftover forward-direction entry where paperNplus1 matched nothing), OR if a pairing
    WAS found but its own question fields are both null too (e.g. an empty-content
    exact-title match) -- that's a legitimate empty list, not a lookup failure. Future
    generations of this family (folding in a 4th, 5th paper) should APPEND their own
    now-superseded question onto whatever list this pairing already carried, never replace
    or truncate it -- see the skill's "Narrowing across successive papers" note. NOTE: after
    the 2026-08-17 fix to directional-section-mapping-by-paragraphs-and-questions, a paperA-
    or paperB-only pairing entry's own question_p1_p2/question_p2_p1 is now itself already a
    pulled-forward singleton question (not composed, not null) -- so this list, for a
    paperA/paperB-only entry, already holds exactly the value Step 3 should use verbatim for
    a papernplus1-level singleton on that same side. See Step 3's pull-forward rule."""
    a_key = side_key(paperA_num, paperA_name)
    b_key = side_key(paperB_num, paperB_name)
    if a_key is None and b_key is None:
        return []
    entry = pairing_lookup.get((a_key, b_key))
    if entry is None:
        warnings.append(
            f"No matching pairing-file entry for paperA={paperA_name!r}/{paperA_num!r}, "
            f"paperB={paperB_name!r}/{paperB_num!r} -- ancestor_questions left empty. "
            f"This is a real data-integrity gap (stale pairing file, renumbered section), not expected."
        )
        return []
    q = entry.get("question_p1_p2") or entry.get("question_p2_p1")
    return [q] if q else []


def key_of_forward(entry):
    """Key for a papernplus1-to-pairing entry, or None if no match was found at all
    (both matched_pairing_paperA_* and matched_pairing_paperB_* are empty)."""
    a_key = side_key(entry.get("matched_pairing_paperA_section_number"), entry.get("matched_pairing_paperA_section_name"))
    b_key = side_key(entry.get("matched_pairing_paperB_section_number"), entry.get("matched_pairing_paperB_section_name"))
    if a_key is None and b_key is None:
        return None
    n1_key = side_key(entry.get("paperNplus1_section_number"), entry.get("paperNplus1_section_name"))
    return (n1_key, a_key, b_key)


def common_pairing_status(ancestor_status) -> str:
    """Fresh per-generation status for a CONFIRMED (bidirectional) match: common-structure
    only if the ancestor pairing was ALSO common-structure (monotonic -- once broken, never
    regained). Otherwise alignable-diff, covering both an ancestor that was already
    alignable-diff (stays alignable-diff) AND an ancestor that was non-alignable-diff (a
    genuine bidirectional confirmation just happened, so it can no longer be "nothing aligns
    with this" -- promoted to alignable-diff, not left at non-alignable-diff)."""
    return "common-structure" if ancestor_status == "common-structure" else "alignable-diff"


def key_of_reverse(entry):
    """Key for a pairing-to-papernplus1 entry, or None if no match was found at all
    (paperNplus1_section_name is empty)."""
    n1_key = side_key(entry.get("paperNplus1_section_number"), entry.get("paperNplus1_section_name"))
    if n1_key is None:
        return None
    a_key = side_key(entry.get("pairing_paperA_section_number"), entry.get("pairing_paperA_section_name"))
    b_key = side_key(entry.get("pairing_paperB_section_number"), entry.get("pairing_paperB_section_name"))
    return (n1_key, a_key, b_key)


def found_match_forward(entry) -> bool:
    """Did paperNplus1's own best-match search find a real candidate pairing at all
    (either side named)? This is a RAW fact about this one pass, independent of how the
    resulting alignment gets classified -- used for `reason`, not `diff_type`."""
    a_name = entry.get("matched_pairing_paperA_section_name")
    b_name = entry.get("matched_pairing_paperB_section_name")
    return norm(a_name) is not None or norm(b_name) is not None


def found_match_reverse(entry) -> bool:
    """Did this pairing's own best-match search land on a real paperNplus1 section? Raw
    fact about this one pass -- used for `reason`, not `diff_type`."""
    return norm(entry.get("paperNplus1_section_name")) is not None


def diff_type_forward(entry) -> str:
    """paperNplus1's own section found no candidate anywhere -- genuinely non-alignable.
    (There's no "ancestor status" to fall back on here: if neither side is named, there's
    no existing pairing at all for this to have inherited a status from.)"""
    return "alignable" if found_match_forward(entry) else "non-alignable"


def diff_type_reverse(entry, warnings) -> str:
    """If paperNplus1 matched this pairing unidirectionally, that's always alignable
    (Fix 1 rule 2: unidirectional -> alignable-diff, regardless of prior label). If
    paperNplus1 found NOTHING for this pairing, don't automatically call it non-alignable --
    that conflates "the newest paper doesn't participate" with "nothing aligns with this at
    all". Fall back to the pairing's own prior status: only non-alignable if that pairing was
    ALREADY isolated (non-alignable-diff) before paperNplus1 was even considered; otherwise
    the earlier papers still align with each other, so this is alignable."""
    if found_match_reverse(entry):
        return "alignable"
    ancestor_status = entry.get("pairing_status")
    if ancestor_status == "non-alignable-diff":
        return "non-alignable"
    if ancestor_status not in ("common-structure", "alignable-diff"):
        warnings.append(
            f"Unrecognized/missing ancestor pairing_status {ancestor_status!r} for paperA="
            f"{entry.get('pairing_paperA_section_name')!r}, paperB={entry.get('pairing_paperB_section_name')!r} "
            f"-- defaulting to non-alignable. Real data-integrity gap, not expected."
        )
        return "non-alignable"
    return "alignable"


def leftover_from_forward(entry, pairing_lookup, warnings) -> dict:
    paperA_name = entry.get("matched_pairing_paperA_section_name")
    paperA_num = entry.get("matched_pairing_paperA_section_number")
    paperB_name = entry.get("matched_pairing_paperB_section_name")
    paperB_num = entry.get("matched_pairing_paperB_section_number")
    return {
        "direction": "papernplus1-to-pairing",
        "reason": "matched_one_direction_only" if found_match_forward(entry) else "no_counterpart_found",
        "diff_type": diff_type_forward(entry),
        "paperNplus1_section_name": entry.get("paperNplus1_section_name"),
        "paperNplus1_section_number": entry.get("paperNplus1_section_number"),
        "paperA_section_name": paperA_name,
        "paperA_section_number": paperA_num,
        "paperB_section_name": paperB_name,
        "paperB_section_number": paperB_num,
        "ancestor_pairing_status": entry.get("matched_pairing_status"),
        "basis": entry.get("basis"),
        "ancestor_questions": ancestor_questions_for(paperA_name, paperA_num, paperB_name, paperB_num, pairing_lookup, warnings),
    }


def leftover_from_reverse(entry, pairing_lookup, warnings) -> dict:
    paperA_name = entry.get("pairing_paperA_section_name")
    paperA_num = entry.get("pairing_paperA_section_number")
    paperB_name = entry.get("pairing_paperB_section_name")
    paperB_num = entry.get("pairing_paperB_section_number")
    return {
        "direction": "pairing-to-papernplus1",
        "reason": "matched_one_direction_only" if found_match_reverse(entry) else "no_counterpart_found",
        "diff_type": diff_type_reverse(entry, warnings),
        "paperNplus1_section_name": entry.get("paperNplus1_section_name"),
        "paperNplus1_section_number": entry.get("paperNplus1_section_number"),
        "paperA_section_name": paperA_name,
        "paperA_section_number": paperA_num,
        "paperB_section_name": paperB_name,
        "paperB_section_number": paperB_num,
        "ancestor_pairing_status": entry.get("pairing_status"),
        "basis": entry.get("basis"),
        "ancestor_questions": ancestor_questions_for(paperA_name, paperA_num, paperB_name, paperB_num, pairing_lookup, warnings),
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

    if not isinstance(combined, dict) or "papernplus1-to-pairing" not in combined or "pairing-to-papernplus1" not in combined:
        raise ValueError(f"{input_path} must be a JSON object with 'papernplus1-to-pairing' and 'pairing-to-papernplus1' keys")

    pairing_lookup = build_pairing_question_lookup(pairing_entries)
    warnings = []

    fwd = combined["papernplus1-to-pairing"]
    rev = combined["pairing-to-papernplus1"]

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
                common.append({
                    "paperNplus1_section_name": f["paperNplus1_section_name"],
                    "paperNplus1_section_number": f["paperNplus1_section_number"],
                    "paperA_section_name": paperA_name,
                    "paperA_section_number": paperA_num,
                    "paperB_section_name": paperB_name,
                    "paperB_section_number": paperB_num,
                    "pairing_status": common_pairing_status(f.get("matched_pairing_status")),
                    "basis_papernplus1_to_pairing": f.get("basis"),
                    "basis_pairing_to_papernplus1": r.get("basis"),
                    "ancestor_questions": ancestor_questions_for(paperA_name, paperA_num, paperB_name, paperB_num, pairing_lookup, warnings),
                })

    def common_sort_key(e):
        n = e["paperNplus1_section_number"]
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
        n = e["paperNplus1_section_number"]
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

    common_path = output_dir / f"{prefix}-papernplus1-common-section-structure.json"
    leftover_path = output_dir / f"{prefix}-papernplus1-leftover-section-differences.json"

    with open(common_path, "w", encoding="utf-8") as f:
        json.dump(common, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(leftover_path, "w", encoding="utf-8") as f:
        json.dump(leftovers, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"papernplus1-to-pairing pairings: {len(fwd)}")
    print(f"pairing-to-papernplus1 pairings: {len(rev)}")
    print(f"Confirmed three-way matches: {len(common)}")
    for e in common:
        print(f"  [common] {e['paperNplus1_section_name']} <-> {e['paperA_section_name']} / {e['paperB_section_name']} ({e['pairing_status']})")
    print(f"Leftover entries: {len(leftovers)}")
    for e in leftovers:
        print(f"  [leftover:{e['diff_type']}/{e['reason']}, ancestor={e['ancestor_pairing_status']}, {e['direction']}] {e['paperNplus1_section_name']} <-> {e['paperA_section_name']} / {e['paperB_section_name']}")
    if warnings:
        print(f"\n{len(warnings)} WARNING(S) -- ancestor_questions lookup gap(s):")
        for w in warnings:
            print(f"  - {w}")
    print(f"\nWrote {common_path}")
    print(f"Wrote {leftover_path}")
    print(f"\nNOTE: question_the_sections_answer is not set on either file yet -- that's Step 3 of the skill. Entries with 2 or 3 sides present need a FRESH composed question; true single-sided (singleton) entries need their existing question PULLED FORWARD, not composed -- see Step 3. ancestor_questions IS already set by this script.")


if __name__ == "__main__":
    main()
```

The script infers `{prefix}` from the input filename automatically (stripping the known `-both-directions-section-mapping-by-paragraphs-and-questions.json` suffix) — you don't need to re-ask the user for paper names. If the input file doesn't follow that naming convention, the script falls back to the file's full stem; check both resulting output filenames look sensible before reporting it as done. If the script prints any `ancestor_questions` WARNING lines, that's a real data-integrity gap (stale pairing file, a section renamed between runs) — investigate before handing the output to the user, don't just note it and move on.

### Step 3: Set `question_the_sections_answer` for every entry in BOTH files — compose OR pull forward, depending on how many sides are present

This is a reasoning-and-lookup step, not something the script does, and it applies to every entry in both `{prefix}-papernplus1-common-section-structure.json` and `{prefix}-papernplus1-leftover-section-differences.json` — not just the common-structure file. This step only ever touches `question_the_sections_answer`; leave `ancestor_questions` exactly as Step 2's script set it — it's not something to recompute, reorder, or second-guess here.

**First, for every entry, count how many of `paperA_section_name`/`paperB_section_name`/`paperNplus1_section_name` are non-null.** This determines which of the two treatments below applies:

**Case A — 2 or 3 sides present (a real correlation exists to describe).** This covers every common-structure entry (which always has paperNplus1 plus at least one of paperA/paperB) and any leftover entry with two sides present (e.g. a matched two-paper pairing with no paperNplus1 counterpart, or a paperNplus1 section matched to only one of paperA/paperB but not confirmed). Compose a genuinely **new** question:

1. Look up the actual paragraph content for each side that's present on *that entry*: `paperNplus1_paragraphs` from file 3 (match by `paperNplus1_section_number`, falling back to exact `paperNplus1_section_name` for unnumbered sections — same join convention as everywhere else in this family) when `paperNplus1_section_name` isn't null; `paperA_paragraphs` from file 2's matching entry (via `paperA_section_number`/`paperA_section_name`) when `paperA_section_name` isn't null; `paperB_paragraphs` similarly when `paperB_section_name` isn't null.
2. **If every side you just looked up has zero paragraphs** — this happens when the underlying match came from the empty-content exact-title fallback (e.g. an empty "References" section matched purely because all present sides are literally titled "References," not because there's any content to compare) — leave `question_the_sections_answer` as `null` for that entry and move on to the next one. There's nothing to read, so don't force a question by paraphrasing the section name(s) or `basis` text instead of real content.
3. Otherwise, read every title and every paragraph you looked up for that entry's present sides, then compose **one new question** that the present sections together answer, written fresh from that content. Never copy, trim, or merge a directional pass's earlier `question_the_sections_answer` value, and never copy any entry from `ancestor_questions` either — that field intentionally preserves the ORIGINAL, broader question(s) unmodified, precisely so it can be compared against this entry's own (possibly narrower) composed question; don't collapse the two into each other.
4. Apply the same question-quality rules already established elsewhere in this family: keep it short — a question, not a question-plus-parenthetical-answer; and if the paragraphs mix different *kinds* of finding (e.g. one section reports a behavior, another reports an attitude/opinion about it), the question should be framed narrowly enough to reflect that, not just broad topic overlap.

**Case B — exactly 1 side present (a true singleton — fixed 2026-08-17).** This can only happen on a leftover entry (a common-structure entry always has 2+ sides by construction), where only one of `paperA_section_name`/`paperB_section_name`/`paperNplus1_section_name` is non-null. There is nothing here to correlate against — the section already has its own question, and composing a "new" one would just be redundant, needless rework with a real chance of drifting from the already-correct original. **Don't compose. Pull the existing question forward, verbatim, from wherever it already lives:**

- **If the lone present side is `paperNplus1`:** copy that section's own `question_this_section_answers` value from file 3 (the third paper's own `sections-with-paragraphs-and-questions.json`), matched by `paperNplus1_section_number`/`paperNplus1_section_name`, byte-for-byte. Don't reword or "clean up" it.
- **If the lone present side is `paperA` or `paperB`:** copy the last (most recent) entry in that entry's own `ancestor_questions` list, byte-for-byte. This works because, after the 2026-08-17 fix to `directional-section-mapping-by-paragraphs-and-questions`, a paperA-only or paperB-only pairing entry's own question is *itself* already a pulled-forward singleton question (not composed, not null) — `ancestor_questions` already holds exactly the right value; there's no need to go looking anywhere else. If `ancestor_questions` is unexpectedly empty here, treat it as a real data-integrity gap (flag it, don't fall back to composing something new to paper over it) — see Step 4, which will also catch this.

Add the resulting string — composed (Case A) or pulled forward (Case B) — as `question_the_sections_answer` on that entry, alongside the `ancestor_questions` field Step 2 already set. Every other field on the entry stays exactly as Step 2 produced it.

Once every entry in both files has been processed, rewrite both `{prefix}-papernplus1-common-section-structure.json` and `{prefix}-papernplus1-leftover-section-differences.json` with their full, updated arrays (all entries, in the same order Step 2 produced).

### Step 4: Validate Step 3 is complete (hard gate — do not proceed until this passes)

Step 3 is a reasoning-and-lookup step, and steps like that are the ones that get skipped or left half-done, especially under time pressure or across a long batch of entries — real corpus runs of this family have produced files where a chunk of entries were simply never composed (or, now, never pulled forward), and the gap wasn't caught until a much later fold-in generation stumbled on it. This step exists to catch that mechanically, every single run, rather than trusting that Step 3 actually finished. **Do not report this skill's output as done, and do not let a downstream skill (a 4th-paper fold-in, a paragraph-level drill-down, anything) consume these files, until this step passes clean.**

Copy the script below byte-for-byte into a local file (e.g. `validate_papernplus1_step3_complete.py`) — this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant. Then run it with the two files Step 2/3 just wrote plus the same two paragraph-source files (2 and 3) already used in Step 3:

```bash
python3 validate_papernplus1_step3_complete.py {prefix}-papernplus1-common-section-structure.json {prefix}-papernplus1-leftover-section-differences.json {paperA-name}-{paperB-name}-sections-with-paragraphs-and-questions.json {paperNplus1-name}-sections-with-paragraphs-and-questions.json
```

```python
#!/usr/bin/env python3
"""
Validates that {prefix}-papernplus1-common-section-structure.json and
{prefix}-papernplus1-leftover-section-differences.json satisfy Step 3's completeness rule:
EVERY entry in both files (this generation composes or pulls forward a question for all of
them, not just a subset) has a real question_the_sections_answer -- UNLESS every side
actually present on that entry has zero paragraphs (the one legitimate empty-content case
Step 3 itself allows, e.g. an empty References section matched purely on title).

Paragraph counts are looked up from the same two paragraph-source files Step 2/3 already
require (the two-paper pairing file for paperA/paperB paragraphs, paperNplus1's own
sections-with-paragraphs-and-questions.json for paperNplus1 paragraphs) -- never re-derived
or assumed from the entry's own fields, and never trusted just because a later generation
happened to carry the value forward.

Exit 0: every entry either has a real question or is verified legitimately empty -- Step 3 is
genuinely complete, safe to report this skill's output as done.
Exit 1: one or more entries are missing a question with real content present -- Step 3 is
NOT complete. Do not report success. Go back, compose (2-3 sides present) or pull forward
(1 side present) a real question for every entry listed below, rewrite both files, and
re-run this validator.

Usage:
    python3 validate_papernplus1_step3_complete.py common.json leftover.json pairing-file.json paperNplus1-file.json
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
    common_path, leftover_path, pairing_path, paperNplus1_path = (Path(a) for a in sys.argv[1:5])
    common = json.load(open(common_path, encoding="utf-8"))
    leftover = json.load(open(leftover_path, encoding="utf-8"))
    pairing_entries = json.load(open(pairing_path, encoding="utf-8"))
    paperNplus1_sections = json.load(open(paperNplus1_path, encoding="utf-8"))

    lookups = {
        "A": build_pairing_side_lookup(pairing_entries, "A"),
        "B": build_pairing_side_lookup(pairing_entries, "B"),
        "Nplus1": build_flat_lookup(paperNplus1_sections),
    }
    sides = ["A", "B", "Nplus1"]
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
              f"that is NOT legitimately empty-content. Step 3 is incomplete -- do not report "
              f"this skill's output as done. Compose (2-3 sides) or pull forward (1 side) a "
              f"real question for each entry below, rewrite both files, and re-run this validator.")
        for kind, e, counts in violations:
            sides_desc = ", ".join(f"{s}={name!r}({c} paragraphs)" for s, name, c in counts)
            print(f"  [{kind}] {sides_desc}")
        if missing_lookups:
            print(f"\n{len(missing_lookups)} paragraph lookup(s) could not be resolved against "
                  f"the pairing/paperNplus1 files -- these count as unverified, not empty:")
            for name, num in missing_lookups:
                print(f"  - {name!r} ({num!r})")
        sys.exit(1)

    print(f"Step 3 validation passed: {len(common)} common-structure + {len(leftover)} leftover "
          f"entries all have a real question or are verified legitimately empty. Safe to report.")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

If the script exits 0, move on to Step 5. **If it exits 1**, it lists every entry with a missing `question_the_sections_answer` that isn't legitimately empty-content — go back to Step 3, compose (2-3 sides present) or pull forward (exactly 1 side present) a real question for each entry listed, rewrite both files, and re-run this validator. Repeat until it passes clean before moving on.

### Step 5: Report to the user

State both counts (e.g. "13 confirmed three-way matches; 12 leftover entries, all non-alignable — none of AbstractExplorer's appendix-only sections found any counterpart in the third paper"), and don't just dump the JSON. Distinguish `diff_type` when you summarize, same as the base skill. If any entry in either file ended up with a `null` question (the empty-content exact-title fallback case), call that out too. Mention how many leftover entries were true singletons (question pulled forward) vs. multi-sided (question freshly composed) if it's a meaningful fraction. If the user asks about a specific entry, or if an entry's `question_the_sections_answer` looks notably narrower than its most recent `ancestor_questions` entry, proactively point out the gap — that's exactly the signal this field exists to surface. Confirm Step 4's validator exited 0 before reporting anything as done.

## Output

Two files, both saved in the same directory as the input unless the user specifies otherwise:

| File | Contents |
|---|---|
| `{prefix}-papernplus1-common-section-structure.json` | Three-way correspondences both directional passes independently agree on, each with one freshly-composed question and (when a real pairing is involved) an `ancestor_questions` list pointing back to that pairing's prior question(s) |
| `{prefix}-papernplus1-leftover-section-differences.json` | Every remaining entry from either pass, each tagged `alignable` or `non-alignable`, each also with a question describing whichever 1, 2, or 3 sides that entry has — freshly composed if 2+ sides are present, pulled forward verbatim if only 1 is — plus the same `ancestor_questions` list when applicable |

`{prefix}` is the input filename with `-both-directions-section-mapping-by-paragraphs-and-questions.json` stripped (typically `{paperA-name}-{paperB-name}-{paperNplus1-name}`). Every entry in the input's `papernplus1-to-pairing` and `pairing-to-papernplus1` arrays ends up in exactly one of these two files — nothing is silently dropped. Both files are only considered finished once Step 4's validator has exited 0 against them.

### Output schema (strict)

**`{prefix}-papernplus1-common-section-structure.json`** — a JSON array:

```json
{
  "paperNplus1_section_name": "string",
  "paperNplus1_section_number": "string or null",
  "paperA_section_name": "string or null",
  "paperA_section_number": "string or null",
  "paperB_section_name": "string or null",
  "paperB_section_number": "string or null",
  "pairing_status": "string -- freshly computed for THIS confirmed match (not carried over): common-structure only if the ancestor two-paper pairing was ALSO common-structure; alignable-diff otherwise, including when the ancestor was non-alignable-diff (a bidirectional confirmation just happened, so it can't still be non-alignable)",
  "basis_papernplus1_to_pairing": "string -- the basis text from the papernplus1-to-pairing pass's version of this match",
  "basis_pairing_to_papernplus1": "string -- the basis text from the pairing-to-papernplus1 pass's independently-derived version of the same match",
  "ancestor_questions": "array of strings (0 or 1 entries at this stage), oldest first -- the underlying pairing's own original question(s), copied verbatim from the pairing file's question_p1_p2 (or question_p2_p1 if that's null), never re-derived or paraphrased. Empty list if there's no pairing to point back to, or if the pairing's own question was itself null. Set by Step 2's script, not Step 3. Future paper fold-ins append to this list rather than replacing it.",
  "question_the_sections_answer": "string composed fresh in Step 3 from the actual matched sections' titles and paragraphs (a common-structure entry always has 2-3 sides present, so it's always Case A, never a singleton pull-forward), verified non-null (or legitimately null on empty content) by Step 4"
}
```

`paperNplus1_section_name` is always non-null (a confirmed match always has a real paperNplus1 section). At least one of `paperA_section_name`/`paperB_section_name` is always non-null, but — unlike the base skill — **both are not guaranteed to be non-null**; see "What this is and isn't" above for why a confirmed match to an `alignable-diff`/`non-alignable-diff` pairing is legitimate here. Since at least one of paperA/paperB is always present on a common-structure entry, `ancestor_questions` is essentially always non-empty here too, except in the rare case where the pairing file's own question was itself null.

**`{prefix}-papernplus1-leftover-section-differences.json`** — a JSON array:

```json
{
  "direction": "\"papernplus1-to-pairing\" or \"pairing-to-papernplus1\" -- which pass produced this entry",
  "reason": "\"no_counterpart_found\" (nothing matched at all in this pass) or \"matched_one_direction_only\" (a match was found, but the other pass didn't independently confirm it) -- a RAW fact about this one pass, independent of diff_type",
  "diff_type": "freshly computed, NOT derived from reason: \"alignable\" if this pass found a real unidirectional match; if this pass found nothing, \"non-alignable\" only if ancestor_pairing_status was ALREADY non-alignable-diff, otherwise \"alignable\" (the earlier papers still align with each other even though paperNplus1 doesn't participate)",
  "paperNplus1_section_name": "string, or null if this entry came from pairing-to-papernplus1 and no paperNplus1 section was found",
  "paperNplus1_section_number": "string or null",
  "paperA_section_name": "string, or null if this entry came from papernplus1-to-pairing and no matched pairing was found, or if the underlying pairing itself had no paperA side",
  "paperA_section_number": "string or null",
  "paperB_section_name": "string, or null (same conditions as paperA_section_name, paperB side)",
  "paperB_section_number": "string or null",
  "ancestor_pairing_status": "string, or null only when direction is papernplus1-to-pairing and reason is no_counterpart_found (no pairing was matched at all, so there's no ancestor status to report) -- the underlying pairing's own PRIOR status, preserved verbatim, NOT this entry's own current classification (that's diff_type)",
  "basis": "string, carried over unchanged from the source entry",
  "ancestor_questions": "array of strings (0 or 1 entries at this stage), oldest first -- the underlying pairing's own original question(s), copied verbatim from the pairing file's question_p1_p2 (or question_p2_p1). Empty when this entry has no paperA/paperB side at all (a papernplus1-to-pairing entry where no pairing was matched), or when the underlying pairing's own question was itself null. Set by Step 2's script, not Step 3.",
  "question_the_sections_answer": "string. If 2 sides are present on this entry (e.g. a matched pairing with no paperNplus1 counterpart, or a one-sided-only paperNplus1 candidate), composed fresh from those sides' paragraphs in Step 3. If exactly 1 side is present (a true singleton), pulled forward verbatim in Step 3 -- from paperNplus1's own question_this_section_answers (file 3) if paperNplus1 is the lone side, or from the last entry in ancestor_questions if paperA or paperB is the lone side. Verified non-null (or legitimately null on empty content) by Step 4."
}
```

`reason` and `diff_type` are two SEPARATE facts here (fixed 2026-08-16), not two vocabularies for the same thing the way the base skill's are — `reason` is a raw description of whether this specific pass found a match; `diff_type` is the alignment classification, which additionally consults `ancestor_pairing_status` when this pass found nothing. They usually agree but are computed independently and can diverge: a `no_counterpart_found` entry can still be `diff_type: "alignable"` if the ancestor pairing was already valid. `ancestor_questions` is empty more often here than in the common-structure file: any `papernplus1-to-pairing` entry with `reason: "no_counterpart_found"` has no paperA/paperB side at all (paperNplus1 matched nothing), so there's no pairing to point back to — that's also always a true singleton (Case B), so its question comes straight from file 3. Don't add extra fields to either file beyond what's listed here.

## Common mistakes to avoid

- **Looking for or requiring a normalize step first.** There isn't one in this family — see "What this is and isn't" above for why. Feed this skill the raw both-directions combined file directly.
- **Requiring both `paperA_section_name` and `paperB_section_name` to be non-null in the common-structure file.** That's the base skill's rule, not this one's — a confirmed match to an `alignable-diff`/`non-alignable-diff` pairing is legitimate and expected here.
- **Treating a match found in only one pass as confirmed.** If paperNplus1's best guess and the pairing's best guess don't land on the same three-way key, it's a leftover with `reason: "matched_one_direction_only"`, never in the common file.
- **Dropping "no counterpart found" entries instead of putting them in the leftover file.** Every entry from both `papernplus1-to-pairing` and `pairing-to-papernplus1` must land in exactly one of the two output files.
- **Computing `diff_type` from `reason` (or vice versa).** Fixed 2026-08-16: these are no longer guaranteed to agree. `reason` is a raw fact about whether this pass found a match; `diff_type` also consults `ancestor_pairing_status` when the pass found nothing. A `no_counterpart_found` entry can legitimately be `diff_type: "alignable"`.
- **Treating "the newest paper found no match" as automatically non-alignable.** This was the actual bug, caught 2026-08-16: `diff_type_reverse`'s "no match" branch must check `ancestor_pairing_status` first — only non-alignable if the ancestor pairing was ALREADY non-alignable-diff. If paperA and paperB already validly align with each other, paperNplus1 simply not participating doesn't make that alignment disappear.
- **Assuming a confirmed (common-structure file) entry's `pairing_status` always equals the ancestor pairing's status.** It's freshly computed via `common_pairing_status`: common-structure only if the ancestor was ALSO common-structure; a bidirectional confirmation against a previously alignable-diff OR non-alignable-diff ancestor becomes alignable-diff, never automatically promoted back to common-structure.
- **Using the wrong null-check for each direction.** In `papernplus1-to-pairing`, "no match at all" means both `matched_pairing_paperA_section_name` and `matched_pairing_paperB_section_name` are empty. In `pairing-to-papernplus1`, it means `paperNplus1_section_name` is empty. These are different checks for a reason — don't apply one direction's rule to the other's entries.
- **Matching only on section number and missing Abstract/References/Acknowledgments-style confirmations.** Same exact-name fallback as every join in this family.
- **Opening a PDF at any point.**
- **Discarding either pass's `basis` field on the common file, or merging the two into one field.** Both are still required, kept separately — only the question fields were collapsed, not the basis fields; don't extend that collapse to basis by mistake.
- **Composing a brand-new question for a true singleton (exactly 1 side present) instead of pulling the existing one forward — fixed 2026-08-17.** A singleton has nothing to correlate against; its section already has a perfectly good question sitting in file 3 (if paperNplus1 is the lone side) or in `ancestor_questions` (if paperA/paperB is the lone side). Recomposing it is wasted work with a real risk of drifting from the already-correct text — see Step 3's Case B.
- **Copying one of the two directional passes' `question_the_sections_answer` values straight through as the new single question on a MULTI-sided (2-3 side) entry, instead of composing it fresh in Step 3.** This rule still applies to Case A entries — only true singletons (Case B) get a pulled-forward value; a 2- or 3-sided entry always needs a genuinely new question written from its own paragraph content.
- **Rewording, paraphrasing, or "improving" a pulled-forward singleton question.** Copy it byte-for-byte from file 3 or from `ancestor_questions`, same discipline as every other pull-forward in this family.
- **Running Step 3 without files 2 and 3 (the pairing file and the paperNplus1 sections file).** The combined both-directions file alone doesn't carry paragraph text or file-3's own precomputed questions — Step 3 needs the two extra inputs whether it's composing (Case A) or pulling forward (Case B).
- **Assuming `question_the_sections_answer` is null whenever an entry only has 1 or 2 of the 3 possible sides present.** It's null in one specific, narrow case only: every side that *is* present has zero paragraphs (the empty-content exact-title fallback). A leftover entry with just a single paperA-only appendix section, and real paragraph content on that side, still gets a real question — pulled forward from `ancestor_questions`, per Case B.
- **Running Step 2's script without the pairing file as its second argument.** `ancestor_questions` can't be populated without it, and the script will fail outright (or, if called wrong, simply not have the data) rather than silently skip the field.
- **Composing `ancestor_questions` in Step 3, or overwriting/reordering/truncating it there.** It's a literal copy from the pairing file, set mechanically in Step 2 — Step 3 only ever sets `question_the_sections_answer`, never touches `ancestor_questions`.
- **Treating `ancestor_questions` as a single string instead of a list, or replacing its contents instead of (in future extensions of this family) appending to them.** It's a list from the start, even though today it only ever holds 0 or 1 entries — that shape exists specifically so a later fold-in of a 4th or 5th paper can grow it without a schema change.
- **Confusing any entry in `ancestor_questions` with `question_the_sections_answer`, or treating a difference between them as an error to fix.** They're deliberately allowed to diverge for Case A (multi-sided) entries — `ancestor_questions` holds the original, un-narrowed question(s) from earlier generations, oldest first; `question_the_sections_answer` is this specific entry's own (possibly narrower) current question. For Case B (singleton) entries, by contrast, they're deliberately supposed to MATCH (the last entry in `ancestor_questions` IS `question_the_sections_answer`, verbatim) — don't "fix" that agreement either.
- **Assuming this skill's corrected `pairing_status` automatically survives into a 4th-paper fold-in without checking the downstream merge skill.** `papernplus1-pairings-with-paragraphs-and-questions` (which builds the three-paper pairing file this skill's output feeds into) had its own matching bug — it hardcoded every confirmed entry's `pairing_status` to `"common-structure"` regardless of what this skill's file said, silently discarding an `alignable-diff` confirmed match. Fixed in lockstep, 2026-08-16 — but if this skill is ever copied or forked again, check that whatever consumes its output reads `pairing_status` rather than assuming a constant.
- **Assuming a thin or all-`non-alignable` leftover file proves the source papers really have nothing else in common.** This skill's Step 2/3 only reorganize and describe whatever entries the upstream `directional-section-mapping-paragraphs-and-questions-papernplus1`/`pairing-to-papernplus1-mapping-by-paragraphs-and-questions` passes already produced — see the "buried narrow role" awareness note above for the risk that a narrow role was folded into a denser section upstream and never split out at all.
- **Skipping Step 4, or treating it as optional/a nice-to-have.** It's a hard gate, added 2026-08-16 specifically because a real corpus run had entries where Step 3 was silently incomplete and the gap only surfaced generations later. Report success only after Step 4 exits 0.
- **Treating Step 4 as read-only / advisory and moving on anyway when it exits 1.** Exit 1 means go back to Step 3, compose or pull forward the missing questions it lists, rewrite both files, and re-run the validator — not "note the warning and continue."
- **Writing a custom variant of either Step 2's or Step 4's bundled script instead of copying it verbatim, or "fixing" its behavior for a specific entry.** Both scripts are mechanical and fixed — if either flags or produces something that looks wrong, that's a signal to check the underlying data (the both-directions file, the pairing file), not to rewrite the script.
