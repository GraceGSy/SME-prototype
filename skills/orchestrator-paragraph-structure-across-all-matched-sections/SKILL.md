---
name: "orchestrator-paragraph-structure-across-all-matched-sections"
description: "Given a corpus's common-section-structure.json + leftover-section-differences.json (any generation, 2-5 papers) plus each paper's sections-with-paragraph-content(-no-appendices).json, runs orchestrator-paragraph-structure-within-matched-section on every usable row, dispatched as isolated subagents in checked-in batches, then merges every row's paragraph-level outputs into one flat combined JSON, and as a final clean-up step re-nests those results under each row's section-level match info into a second, section-grouped deliverable, with real paragraph text now inlined for every paper side (pulled from that row's Stage-0 pseudo-section files, joined by paper name + abbreviation + role_slug). Predicts each row's output filenames using the same per-row paper-name-abbreviation algorithm extract-paragraphs-as-pseudo-sections uses. Use to drill every matched section down to paragraph level across a whole corpus in one request."
---

# Paragraph Structure Across All Matched Sections (Orchestrator)

## What this is (and isn't)

This is the whole-corpus batch sibling of `orchestrator-paragraph-structure-within-matched-section`. That skill drills one specific row of a section-level comparison down to paragraph-level correspondence; this skill runs it on **every usable row** of a corpus's section-level comparison — every `common-section-structure.json` row plus every `"alignable"` `leftover-section-differences.json` row — and merges all of their outputs into a single combined file, then produces a second, section-grouped deliverable as a final clean-up pass.

It has no matching logic of its own. Every row is still handled entirely by `orchestrator-paragraph-structure-within-matched-section` (which in turn defers to `extract-paragraphs-as-pseudo-sections` and the existing N-paper section-structure chains) — this skill's own job is purely mechanical: merge the two input files into one row list, filter out rows with nothing to compare, assign each row a collision-free role-slug, predict each row's exact output filenames (paper-abbreviation-aware, see below), resolve each row's paper specs, dispatch each row as an isolated subagent so one row's context never bleeds into another's, verify what came back, merge the results into one flat file, and finally re-nest those same results under each row's section-level context for a second, more legible deliverable.

**Each row is run in its own subagent** so that a role like "Introduction" and a role like "Experiment 3" don't share any reasoning context — the whole point of doing this per-row rather than in one long pass is that paragraph-level composition (gists, questions) for one section shouldn't be influenced by having just read a completely different section's paragraphs. Rows are dispatched in small batches (not all at once) so problems in an early batch can be caught and fixed before burning through the rest.

**If the section-level comparison hasn't been run yet**, this is the wrong starting point — run `orchestrator-common-section-structure-with-differences` / `orchestrator-papernplus1/2/3-common-section-structure` / `orchestrator-five-paper-common-section-structure-from-pdfs` (or its no-appendices variant) first.

**Relationship to the papernplus1/2/3 family's Step 4 validation gate.** If the input `common-section-structure.json`/`leftover-section-differences.json` came from the papernplus1/2/3 family, that family's Step 4 gate (added 2026-08-16) checks `question_the_sections_answer` completeness — a *section-level* field this skill never reads. A row missing that field can still be processed here without error. Still, recommend (don't require) confirming Step 4 passed on the input files first: a section-level row whose own question was never composed is a mild signal the row itself may be less trustworthy, even though nothing here depends on that field directly.

**Every script in this skill's Workflow (Steps 1-4, 6, 7, 8) is given verbatim and must be copied byte-for-byte, never authored or modified.** Wherever a step says "write the script," that means transcribe the exact code shown into a file — not compose a variant, not add a flag, not adjust behavior for a specific row or case. If a script's documented behavior seems wrong for a specific situation, that's a stop-and-ask-the-user moment, not a reason to write custom logic — see "Step 5 must never authorize a custom Stage-0 script" below for the real incident this rule generalizes from.

## Step 5 prompts must copy row facts verbatim from dispatch-plan.json -- never restate from memory (bug fixed 2026-08-18, real incident)

**Steps 1-4's `build_dispatch_plan.py` script already mechanically derives every fact about which papers participate in a row.** `present_slots_of(row)` checks non-null `paperX_section_name` fields directly off the section-level JSON -- there is no LLM judgment involved in computing a row's `n`, `present_slots`, or `paper_specs`. By the time `dispatch-plan.json` exists, these fields are ground truth, not a draft to be redescribed.

**The bug:** during a real 5-paper corpus run (2026-08-18), the orchestrating model wrote a batch of Step 5 subagent prompts by summarizing each row's content from memory of earlier turns in the conversation, instead of re-reading `dispatch-plan.json`'s own entry for that row at prompt-composition time. For one row (a "Discussion vs. Limitations and Future Work" pairing, `n: 5`, all five papers correctly present per the mechanical Steps 1-4 computation), the prose summary confused it with a *different*, unrelated pairing and told the subagent the fifth paper had no counterpart and should be excluded. The subagent had no way to catch this -- it was told what the row was, rather than being pointed at the row to read for itself -- and dutifully produced an incorrect `n: 4` result. The row had to be redone and the merged deliverables regenerated.

**Two concrete rules fix this, not just "be careful":**

1. **When writing each subagent's prompt in Step 5, copy `n`, `present_slots`, and `paper_specs` verbatim from that row's own `dispatch-plan.json` entry -- and nothing else.** Do not restate, paraphrase, or describe these facts from memory of an earlier read, an earlier row, or an earlier turn in the conversation -- copy the literal values. **Do not add any prose context about another row to a subagent's prompt, not even labeled as "unverified"** (for example, a guess about which sibling row a paragraph "really" belongs to, because a section got split across multiple rows at the section level). An earlier version of this rule allowed such context as long as it was flagged unverified; that carve-out is what let the second incident below happen — the orchestrating agent believed it had a legitimate reason to reason across rows, and that belief was the seed of the custom-script bug, not merely its symptom. See "Rows never need to know about each other" below for why this kind of context is never actually necessary.
2. **Never edit `dispatch-plan.json`'s row-level facts (`n`, `present_slots`, `paper_specs`, `expected_common_structure_file`, `expected_leftover_file`) to match what a subagent actually produced.** These fields are mechanically correct from the moment Steps 1-4 finish running. If Step 6 (verification) reports `missing_files` for a row -- meaning the actual output doesn't match the already-correct predicted filename -- that is strong evidence the Step 5 prompt itself was wrong (most likely: restated from memory instead of copied verbatim), not evidence that the plan's prediction needs correcting. Investigate the Step 5 prompt that was actually sent for that row, fix it, and re-dispatch so the row produces output matching the *original* prediction. Retroactively patching `dispatch-plan.json` to match a suspicious result silently destroys the very check that would have caught the bug.

## Step 5 must never authorize a custom Stage-0 script (bug fixed 2026-08-18, real second incident)

This is a sibling failure mode to the one above -- same root cause (an unverified guess treated as settled fact), different mechanism (baked into code instead of a prompt).

**The bug:** on the same run, when dispatching Stage 0 for a row whose mesotext side was that paper's whole "Discussion" section, the orchestrating agent wrote and ran a custom, one-off variant of `extract-paragraphs-as-pseudo-sections`' standard script instead of the standard script itself, adding a filter to drop one specific paragraph based on a guess that it "belongs to a different row." That guess was made before any matching had run, was never checked against anything, and turned out to be wrong -- the paragraph actually belonged to a third row, not the one named in the guess. The final result happened to still be correct, but only by luck: `extract-paragraphs-as-pseudo-sections`' own Step 1 script is explicitly documented as making "no judgment calls about paragraph content" for exactly this reason -- Stage 0 is supposed to be too dumb to get this wrong, and the downstream matching skills are explicitly designed to output "no match" for a paragraph that doesn't belong anywhere in a row's context, which is the correct, evidence-based way to reach the same answer.

**The rule this establishes:** when a Step 5 subagent prompt instructs a row's Stage 0, it must always point at `extract-paragraphs-as-pseudo-sections`' own standard script, run unmodified, with no added filtering, exclusion, or merging logic of any kind -- never author, request, or silently accept a custom variant for a specific row. If a row seems to raise a genuine question about paragraph overlap with a sibling row, or seems to need special handling for some other content-based reason, that is a stop-and-ask moment for the user, not something to resolve by writing bespoke extraction code. See `extract-paragraphs-as-pseudo-sections`' own "Stage 0 is strictly mechanical" section for the full incident writeup and the same rule stated from that skill's side.

## Rows never need to know about each other (root-cause fix, extends the two bugs above)

Both bugs above trace back to the same underlying belief: that a Step 5 subagent sometimes needs to be told something about a *different* row's content in order to do its own row correctly. That belief is false, and removing it — not just banning what it leads to — is what actually closes the gap. The custom-script rule above bans *acting* on a cross-row guess; an earlier version of this skill still explicitly permitted *making* one in a Step 5 prompt, as long as it was labeled "unverified context." That permission is what made the guess in the real incident feel legitimate enough to write code against in the first place — once the orchestrating agent believed cross-row reasoning was a normal, sanctioned part of Step 5, treating a specific guess as actionable was a small step away. This skill no longer permits it in any form.

**When one physical section in one paper legitimately corresponds to several different rows** — the real case that motivated the old carve-out: mesotext's whole "Discussion" section mapped to three separate rows (`discussion`, `discussion-2`, `discussion-3`), because other papers in that corpus split that same content into three distinct roles at the section level — the correct behavior is for Stage 0 to independently extract **all** of that section's paragraphs into **every** row that names it. The same paragraph legitimately showing up as a Stage-0 candidate in more than one sibling row is normal and expected, not a conflict to pre-resolve. Each row's own downstream matching skill then evaluates its own candidates purely on that row's own evidence and correctly outputs "no match" for a paragraph that doesn't actually belong to that row's role — which is exactly how a paragraph ends up correctly assigned to exactly one row, evidence-first, without any row ever needing to know what any other row saw or contains.

**A Step 5 subagent's prompt must therefore never contain anything about another row — verified, unverified, or otherwise.** If a row's own content genuinely seems ambiguous or ill-formed before dispatch, that's a stop-and-ask-the-user moment, same as the custom-script case above — not a reason to hand a subagent a cross-row hint, however carefully hedged.

(This is unrelated to, and does not change, Steps 1-4's role-slug collision pass — see "Why 25" and the script's own "Slugging" note below. That pass compares section *names* across the whole row list purely to keep output *filenames* from colliding; it never touches paragraph content or influences which paragraphs get matched to which row, so it isn't the kind of cross-row reasoning this section is about.)

## Predicted filenames now use per-row paper-name abbreviations, not literal names (fixed 2026-08-16)

`extract-paragraphs-as-pseudo-sections` (Stage 0 of `orchestrator-paragraph-structure-within-matched-section`, run inside every subagent this skill dispatches) computes a short, deterministic abbreviation for each paper's literal name and uses `{abbreviation}--{role-slug}` as that paper's filename identifier, instead of `{full-literal-name}--{role-slug}` — this is what keeps output filenames under the OS's ~255-character limit at N=4/5 (see that skill's own "Why output filenames use a short paper-name abbreviation" section for the full story, including the real `graphical-perception` incident that motivated it).

Because this skill's own Step 1-4 script has to *predict* each row's exact output filenames before any subagent runs (Step 6 checks the real files against that prediction), it now replicates the identical `unique_abbreviations()` algorithm, run over **exactly the same paper-name set Stage 0 will see for that row** — i.e. only the papers that row actually spans (its `present_slots`), not the whole corpus's paper list. This matters: `extract-paragraphs-as-pseudo-sections` computes its abbreviations fresh, per-invocation, over only the papers it's actually given for that one row — so a row spanning 2 papers and a row spanning 5 papers can, in principle, resolve the same paper's abbreviation to different lengths if a collision partner is present in one row's subset but absent from another's. Computing abbreviations once over the whole corpus and reusing them for every row would risk predicting the wrong filename in that edge case. Computing them fresh per row, exactly as Stage 0 does, avoids that risk entirely — the prediction is guaranteed correct regardless of any corpus-level naming coincidence.

**Role-slug length guidance changed too.** With paper names shortened at the source, `slugify()`'s cap was restored from an earlier ad hoc emergency value (15, set live mid-run before this fix existed) up to **25** — comfortably safe even at N=5 with the worst-case ~44-character `-papernplus3-leftover-section-differences.json` suffix and typical 4-character paper abbreviations (see the arithmetic in this skill's own script comments). Don't restore it all the way to the original 40; a role-slug that long combined with N=5 and a longer abbreviation (grown to resolve a collision) can still threaten the limit.

## A real schema difference between N=2 and N=3+ rows (relevant to Step 8)

The base (N=2) pipeline's `common-section-structure-by-paragraphs-and-questions` output uses a genuinely different, older field convention than the papernplus1/2/3 family: matched entries carry `basis_p1_p2`/`question_p1_p2`/`basis_p2_p1`/`question_p2_p1` (no `pairing_status`, no `ancestor_questions` field at all), and leftover entries carry `question_the_sections_both_answer` instead of `question_the_sections_answer`. This isn't staleness or a bug — it's simply how the base 2-paper skill has always shaped its output, predating the `pairing_status`/`ancestor_questions` fields the N+1 family later introduced. Every row with N>=3 uses the newer schema. Step 8 below normalizes both into one consistent shape rather than assuming every row shares one schema — don't "fix" a real N=2 row's fields to look like the newer schema; that would misrepresent what the base skill actually produced.

## Inputs

1. **A `common-section-structure.json` file** (any generation, base 2-paper through papernplus3 5-paper).
2. **The matching `leftover-section-differences.json` file** — same generation, same paper set, produced alongside file 1.
3. **Paper specs in `paperA`/`paperB`/`paperNplus1`/`paperNplus2`/`paperNplus3` order** — the same fixed, corpus-wide identity order established when the section-level comparison was originally run (this is a whole-corpus order, not a per-row one; every row's `paperA_section_name` etc. refers back to the same paper throughout the file). For each slot the corpus's comparison spans, supply that paper's literal name and its own `{paper}-sections-with-paragraph-content.json` or `...-no-appendices.json` file.
4. **Optional batch size** for subagent dispatch (default 3).

## Workflow

### Step 0: Confirm inputs

Confirm files 1 and 2 are the same generation (same field names present) and that paper specs are supplied for every slot either file actually uses. If either file came from the papernplus1/2/3 family, recommend running that family's own Step 4 validator first (see "Relationship to the papernplus1/2/3 family's Step 4 validation gate" above) — not a hard blocker, but worth doing.

### Steps 1-4: Build the dispatch plan (mechanical script)

Merges the two input files, drops rows with nothing to compare, assigns every usable row a collision-free role-slug, resolves each row's paper specs, computes that row's per-row paper-name abbreviations (identical algorithm to, and thus predictive of, what `extract-paragraphs-as-pseudo-sections` will actually compute when the subagent runs it), and precomputes the exact output filenames `orchestrator-paragraph-structure-within-matched-section` will produce for it — all in one deterministic pass, so nothing here depends on judgment calls. **Every field this script writes into `dispatch-plan.json` is ground truth from this point forward — see "Step 5 prompts must copy row facts verbatim" above.**

Copy the script below byte-for-byte into a local file (e.g. `build_dispatch_plan.py`) — this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant. Then run it:

```bash
python3 build_dispatch_plan.py common-section-structure.json leftover-section-differences.json paperA_name:paperA_content.json paperB_name:paperB_content.json [paperNplus1_name:file ...]
```

```python
#!/usr/bin/env python3
"""
Steps 1-4 combined: merges a common-section-structure.json and its matching leftover-
section-differences.json into one list of usable "dispatch" rows -- one entry per
section-role worth drilling into at the paragraph level -- each carrying a precomputed,
collision-free role_slug, resolved per-paper specs, per-row paper-name abbreviations, and
the deterministically-expected output filenames orchestrator-paragraph-structure-within-
matched-section will produce.

Filtering: every common-section-structure.json row is kept (2+ papers by construction).
A leftover-section-differences.json row is kept only if diff_type == "alignable" (2+
non-null papers); "non-alignable" rows are skipped and logged, not errored.

Paper order: paperA/paperB/paperNplus1/paperNplus2/paperNplus3 are STABLE identity labels
across the whole corpus, established once when the section-level comparison was originally
run -- not per-row. Supply paper specs in that same fixed order; this script zips them
positionally against ROLE_SLOTS, then looks up whichever slots a given row actually has
non-null.

Slugging: one pass over the WHOLE usable-row list (not per-row), so cross-row FILENAME
collisions can be caught -- this compares section NAMES only, never paragraph content, and
has no bearing on which paragraphs get matched to which row (see this skill's own "Rows
never need to know about each other" section for that separate, unrelated topic). Anchor
name = first non-null paperX_section_name in paperA->paperB->paperNplus1->paperNplus2->
paperNplus3 priority order. Slugified (lowercase, non-alphanumeric runs collapsed to single
hyphens, stripped, capped at 25 chars -- see "Why 25" below). Duplicate base slugs get
-2, -3, ... appended, in list order.

Paper-name abbreviation (added 2026-08-16, matches extract-paragraphs-as-pseudo-sections'
own unique_abbreviations() byte-for-byte): computed FRESH PER ROW, over exactly that row's
present-slot paper names -- never once over the whole corpus. This is deliberate: Stage 0
(extract-paragraphs-as-pseudo-sections) itself only ever sees the paper names it's given
for one specific row's invocation, so it can only resolve collisions within that row's own
subset. Reusing one corpus-wide abbreviation set here could predict a different (wrong)
length than what a smaller row's subset would actually need, or vice versa. Computing fresh
per row guarantees this script's prediction always matches Stage 0's real output.

Why 25 (role_slug max_len): worst-case suffix is "-papernplus3-leftover-section-
differences.json" (47 chars). Budget remaining for N=5 papers' "{abbrev}--{role_slug}"
identifiers, joined by "-": 255 - 47 = 208. With typical 4-char abbreviations:
5*(4 + 2 + role_slug_len) + 4 <= 208  =>  role_slug_len <= ~34. 25 leaves comfortable
margin for a longer abbreviation (grown to resolve an in-row collision) without needing
to re-derive this arithmetic under time pressure again.

Expected output filenames mirror orchestrator-paragraph-structure-within-matched-section's
own documented naming: join each present paper's "{paper-abbreviation}--{role_slug}"
identifier with "-", then append "-common-section-structure.json"/"-leftover-section-
differences.json" (N=2) or "-papernplus{N-2}-common-section-structure.json"/"...-leftover-
section-differences.json" (N=3,4,5).

Usage:
    python3 build_dispatch_plan.py <common.json> <leftover.json> <paperA_name>:<paperA_file> <paperB_name>:<paperB_file> [<paperNplus1_name>:<file> ...]

Paper specs MUST be given in paperA/paperB/paperNplus1/paperNplus2/paperNplus3 order,
covering every paper the corpus's comparison spans (2 to 5) -- not just papers used by
any one row.

Output: dispatch-plan.json (kept rows), written next to the common-structure input.
"""
import json
import re
import sys
from pathlib import Path

ROLE_SLOTS = ["paperA", "paperB", "paperNplus1", "paperNplus2", "paperNplus3"]


def norm(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def slugify(text, max_len=25):
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return (s[:max_len].rstrip("-")) or "role"


def unique_abbreviations(paper_names, min_len=4):
    """Identical algorithm to extract-paragraphs-as-pseudo-sections' own
    unique_abbreviations() -- must stay byte-for-byte identical, since this script's whole
    job is to predict that script's real output filenames before it ever runs. Given a
    list of literal paper names, returns {paper_name: short_abbrev}, growing the shared
    prefix length only as far as needed to keep every abbreviation in THIS specific set
    unique. Called once per dispatch-plan row, over that row's own present-slot paper
    names only -- see the module docstring's "Paper-name abbreviation" note for why."""
    names = list(dict.fromkeys(paper_names))  # de-dup, preserve order
    length = min_len
    while True:
        abbrevs = {n: n[:length] for n in names}
        if len(set(abbrevs.values())) == len(names):
            return abbrevs
        length += 1
        if length > max(len(n) for n in names):
            return {n: f"{n[:length]}{i}" for i, n in enumerate(names)}


def present_slots_of(row):
    return [s for s in ROLE_SLOTS if norm(row.get(f"{s}_section_name")) is not None]


def expected_filenames(present_slots, paper_id_by_slot):
    ids = [paper_id_by_slot[slot] for slot in present_slots]
    prefix = "-".join(ids)
    n = len(ids)
    if n == 2:
        return f"{prefix}-common-section-structure.json", f"{prefix}-leftover-section-differences.json"
    gen = n - 2
    return (f"{prefix}-papernplus{gen}-common-section-structure.json",
            f"{prefix}-papernplus{gen}-leftover-section-differences.json")


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    common_path = Path(sys.argv[1])
    leftover_path = Path(sys.argv[2])
    paper_spec_args = sys.argv[3:]

    paper_by_slot = {}
    for slot, spec in zip(ROLE_SLOTS, paper_spec_args):
        if ":" not in spec:
            print(f"ERROR: paper spec {spec!r} must be NAME:FILE")
            sys.exit(1)
        name, file_path = spec.split(":", 1)
        paper_by_slot[slot] = {"name": name, "content_file": file_path}

    common_rows = json.load(open(common_path, encoding="utf-8"))
    leftover_rows = json.load(open(leftover_path, encoding="utf-8"))

    candidates = []
    skipped = []

    for idx, row in enumerate(common_rows):
        candidates.append({"row_source": "common", "row_index": idx, "row": row, "present_slots": present_slots_of(row)})

    for idx, row in enumerate(leftover_rows):
        present = present_slots_of(row)
        if len(present) < 2:
            skipped.append({
                "row_source": "leftover", "row_index": idx,
                "reason": f"diff_type={row.get('diff_type')!r}, only {len(present)} non-null paper(s) -- nothing to compare",
            })
            continue
        candidates.append({"row_source": "leftover", "row_index": idx, "row": row, "present_slots": present})

    # Slug pass: one pass over the whole usable list, so cross-row FILENAME collisions are
    # caught -- section NAMES only, never paragraph content.
    used_base_slugs = {}
    for entry in candidates:
        row = entry["row"]
        anchor = None
        for slot in entry["present_slots"]:
            name = norm(row.get(f"{slot}_section_name"))
            if name is not None:
                anchor = name
                break
        base_slug = slugify(anchor or "role")
        count = used_base_slugs.get(base_slug, 0) + 1
        used_base_slugs[base_slug] = count
        entry["role_slug"] = base_slug if count == 1 else f"{base_slug}-{count}"

    # Paper-spec resolution + per-row abbreviations + expected filenames.
    dispatch_plan = []
    for entry in candidates:
        present = entry["present_slots"]
        missing = [s for s in present if s not in paper_by_slot]
        if missing:
            print(f"ERROR: row (source={entry['row_source']}, index={entry['row_index']}) needs paper "
                  f"spec(s) for slot(s) {missing} but only {list(paper_by_slot.keys())} were supplied. "
                  f"Supply specs for every slot the corpus's comparison spans, in order.")
            sys.exit(1)
        role_slug = entry["role_slug"]
        # Fresh per-row, over exactly this row's present-slot paper names -- matches
        # Stage 0's own per-invocation scope exactly. Do NOT hoist this out of the loop.
        row_paper_names = [paper_by_slot[s]["name"] for s in present]
        abbrevs = unique_abbreviations(row_paper_names)
        paper_id_by_slot = {s: f"{abbrevs[paper_by_slot[s]['name']]}--{role_slug}" for s in present}
        expected_common, expected_leftover = expected_filenames(present, paper_id_by_slot)
        dispatch_plan.append({
            "row_source": entry["row_source"],
            "row_index": entry["row_index"],
            "role_slug": role_slug,
            "n": len(present),
            "present_slots": present,
            "paper_specs": [
                {"slot": s, "name": paper_by_slot[s]["name"], "content_file": paper_by_slot[s]["content_file"]}
                for s in present
            ],
            "paper_abbreviations": {paper_by_slot[s]["name"]: abbrevs[paper_by_slot[s]["name"]] for s in present},
            "expected_common_structure_file": expected_common,
            "expected_leftover_file": expected_leftover,
            "status": "pending",
        })

    out_path = common_path.parent / "dispatch-plan.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dispatch_plan, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Usable rows: {len(dispatch_plan)}")
    for e in dispatch_plan:
        abbrev_str = ", ".join(f"{name}->{ab}" for name, ab in e["paper_abbreviations"].items())
        print(f"  [{e['row_source']}#{e['row_index']}] role_slug={e['role_slug']!r} N={e['n']} slots={e['present_slots']} abbrevs=({abbrev_str})")
    print(f"Skipped (non-alignable, nothing to compare): {len(skipped)}")
    for s in skipped:
        print(f"  [{s['row_source']}#{s['row_index']}] {s['reason']}")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
```

Review the printed list before dispatching anything — confirm the row count, slugs, N values, and abbreviations look sensible. Pay particular attention to the `abbrevs=(...)` mapping for any row where two papers' names share an unusually long common prefix — that's the one case where a row's abbreviation length can legitimately grow past 4 characters, and it's worth a glance to confirm nothing looks wrong before dispatching subagents against these predicted filenames.

### Step 5: Dispatch each row as an isolated subagent, in checked-in batches

This step cannot be scripted — it requires actually invoking the Agent tool. Partition `dispatch-plan.json`'s entries into batches of the requested size (default 3), in list order.

For each batch:

1. **Immediately before writing each subagent's prompt, open `dispatch-plan.json` and copy that row's `n`, `present_slots`, and `paper_specs` verbatim** — do not restate, paraphrase, or recall these values from an earlier read, an earlier row's prompt, or an earlier turn in the conversation, even within the same session. These fields are mechanically correct as of Steps 1-4; the only way they end up wrong in a subagent's prompt is if they get redescribed by hand instead of copied. (See "Step 5 prompts must copy row facts verbatim from dispatch-plan.json" above for the real incident this rule exists to prevent.)
2. **Launch one subagent per row in that batch, in the same message** (so they run in parallel — never dispatch a batch's subagents one at a time across separate messages). Each subagent's prompt must be self-contained (it has no memory of this conversation) and must supply, for that one row only:
   - The row's source file (`common-section-structure.json` or `leftover-section-differences.json`) and its `row_index` within that file.
   - Its precomputed `role_slug`.
   - Its `n` and `present_slots`, copied verbatim from `dispatch-plan.json` per point 1 above.
   - Its `paper_specs` (name + content-file path per present slot, in `paperA`/`paperB`/... order), copied verbatim.
   - **Nothing else about the row's content, and nothing at all about any other row** — see "Rows never need to know about each other" above. A row's prompt is fully specified by the four bullets above; there is never a legitimate reason to add prose about a sibling row, even hedged as unverified.
   - An explicit instruction to run `orchestrator-paragraph-structure-within-matched-section`'s full workflow using exactly those inputs, **using `extract-paragraphs-as-pseudo-sections`' own standard Step 1 script for Stage 0 exactly as documented, with no custom variant, filter, exclusion, or merge logic of any kind** — including running that script's own `unique_abbreviations()` step itself, not being told what the abbreviation "should" be — and to report back: N, the paper-name → abbreviation mapping Stage 0 actually printed, per-paper pseudo-section paragraph counts, confirmed/leftover counts (split alignable/non-alignable), and the exact paths of its two final output files. If you (the orchestrating agent) find yourself wanting to tell a subagent to exclude, merge, or otherwise special-case a specific paragraph for a row — for any reason, including something you believe you know about a sibling row — that is a stop-and-ask-the-user moment — see "Step 5 must never authorize a custom Stage-0 script" and "Rows never need to know about each other" above — not something to resolve by writing or requesting bespoke extraction code, or by passing the belief along to the subagent as context.
3. **Wait for the whole batch to return**, then check in with the user: report each row's result (success with counts, or failure/error) before dispatching the next batch. Don't silently continue past a failed row — flag it and either retry that row or note it as excluded from the merge. If a subagent's actually-printed abbreviation mapping, or its actual `n`, differs from this skill's own `dispatch-plan.json` prediction for that row, treat that as a problem row, same as a missing file — see Step 6 below for what to do next. Do NOT resolve the discrepancy by editing `dispatch-plan.json` to match the subagent's output.
4. Move to the next batch only after the check-in.

### Step 6: Verify every row's outputs (mechanical script)

After all batches have returned, confirm each row actually produced its two expected files (a subagent can misreport, or write to a slightly wrong path) and record real entry counts. **The script below is given verbatim — copy it byte-for-byte, do not modify it, even to special-case a row that looks wrong; if it flags something unexpected, that's a signal to investigate the underlying data, not to alter the check.**

```bash
python3 verify_row_outputs.py dispatch-plan.json <directory containing the output files>
```

```python
#!/usr/bin/env python3
"""
Step 6: after all batches of subagent dispatch (Step 5) have returned, verifies that
every dispatch-plan.json row actually produced its two expected output files (as
computed by build_dispatch_plan.py, using per-row paper-name abbreviations that mirror
extract-paragraphs-as-pseudo-sections' own unique_abbreviations() exactly), that both are
valid JSON arrays, and records each row's actual common/leftover entry counts back into
the plan.

Does not re-run any matching or composition -- purely a file-existence + shape check, so
a subagent that silently failed (or wrote to the wrong filename -- including from an
abbreviation mismatch, OR from a Step 5 prompt that misdescribed the row's own n/
present_slots -- see this skill's own "Step 5 prompts must copy row facts verbatim" note)
is caught here rather than surfacing later as a confusing gap in the merged output.

A "missing_files" result here means the ACTUAL output diverged from an ALREADY-CORRECT
prediction (dispatch-plan.json's n/present_slots/expected filenames come straight from a
mechanical, non-judgment-based read of the section-level JSON in Steps 1-4). Treat that
divergence as evidence the Step 5 prompt itself was wrong -- most likely restated from
memory instead of copied verbatim -- and fix + re-dispatch that row's prompt so it
produces output matching the ORIGINAL prediction. Do NOT edit dispatch-plan.json's row-
level fields to match the wrong output; that destroys the very check that caught the bug.

Usage:
    python3 verify_row_outputs.py <dispatch-plan.json> <directory containing the output files>

Output: dispatch-plan-verified.json (same array, each entry now carrying status: "ok" |
"missing_files" | "invalid_json", plus common_count/leftover_count when ok).
"""
import json
import sys
from pathlib import Path


def main():
    plan_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    plan = json.load(open(plan_path, encoding="utf-8"))

    problems = []
    for entry in plan:
        common_file = out_dir / entry["expected_common_structure_file"]
        leftover_file = out_dir / entry["expected_leftover_file"]
        if not common_file.exists() or not leftover_file.exists():
            entry["status"] = "missing_files"
            missing = [str(p) for p in (common_file, leftover_file) if not p.exists()]
            problems.append((entry, f"missing file(s): {missing} -- if the row's subagent reported a "
                                     f"different paper-name abbreviation, n, or present_slots than "
                                     f"{entry.get('paper_abbreviations')} / n={entry.get('n')}, that's the "
                                     f"likely cause; re-check the Step 5 prompt that was actually sent for "
                                     f"this row (not dispatch-plan.json's own prediction) before re-dispatching"))
            continue
        try:
            common_data = json.load(open(common_file, encoding="utf-8"))
            leftover_data = json.load(open(leftover_file, encoding="utf-8"))
        except json.JSONDecodeError as e:
            entry["status"] = "invalid_json"
            problems.append((entry, f"invalid JSON: {e}"))
            continue
        entry["status"] = "ok"
        entry["common_count"] = len(common_data)
        entry["leftover_count"] = len(leftover_data)

    out_path = plan_path.parent / "dispatch-plan-verified.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
        f.write("\n")

    ok = [e for e in plan if e["status"] == "ok"]
    print(f"Verified {len(ok)}/{len(plan)} rows OK.")
    for e in ok:
        print(f"  [{e['row_source']}#{e['row_index']}] role_slug={e['role_slug']!r} "
              f"common={e['common_count']} leftover={e['leftover_count']}")
    if problems:
        print(f"\n{len(problems)} PROBLEM ROW(S) -- re-run the corresponding subagent:")
        for entry, msg in problems:
            print(f"  [{entry['row_source']}#{entry['row_index']}] role_slug={entry['role_slug']!r}: {msg}")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
```

If any row comes back `missing_files` or `invalid_json`, re-dispatch just that row as its own subagent (same prompt template as Step 5 — including re-copying `n`/`present_slots`/`paper_specs` verbatim from `dispatch-plan.json`, not from the previous, apparently-wrong prompt), then re-run this verify script before continuing — don't proceed to Step 7 with unresolved problem rows, and don't "resolve" a problem row by editing `dispatch-plan.json` to match whatever the subagent actually produced.

### Step 7: Merge every row's outputs into one flat combined file (mechanical script)

Collapses both the per-row file pairs and the common/leftover distinction into a single JSON array, per the original request — every entry keeps its own fields plus traceability back to which row and role it came from. **The script below is given verbatim — copy it byte-for-byte, do not modify it.**

```bash
python3 merge_row_outputs.py dispatch-plan-verified.json <directory containing the output files> <corpus-name>-all-matched-sections-paragraph-structure.json
```

```python
#!/usr/bin/env python3
"""
Step 7: reads dispatch-plan-verified.json (every row status "ok") and merges every row's
paragraph-level common-structure + leftover entries into ONE combined JSON array --
collapsing both the per-row file pairs AND the common/leftover distinction into a single
file. Each merged entry is annotated with role_slug, row_source, row_index (traceability
back to the section-level row it came from), and pairing_level ("paragraph-common-
structure" or "paragraph-leftover-diff") -- every other field is carried through
unchanged from that row's own output file.

Refuses to merge if any row's status isn't "ok" -- fix those rows (re-run the
corresponding subagent, re-verify) before merging, rather than silently omitting them.

Usage:
    python3 merge_row_outputs.py <dispatch-plan-verified.json> <directory containing the output files> <combined-output.json>
"""
import json
import sys
from pathlib import Path


def main():
    plan_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    combined_path = Path(sys.argv[3])
    plan = json.load(open(plan_path, encoding="utf-8"))

    not_ok = [e for e in plan if e["status"] != "ok"]
    if not_ok:
        print(f"ERROR: {len(not_ok)} row(s) are not status=ok -- fix these before merging:")
        for e in not_ok:
            print(f"  [{e['row_source']}#{e['row_index']}] role_slug={e['role_slug']!r} status={e['status']}")
        sys.exit(1)

    combined = []
    for entry in plan:
        common_data = json.load(open(out_dir / entry["expected_common_structure_file"], encoding="utf-8"))
        leftover_data = json.load(open(out_dir / entry["expected_leftover_file"], encoding="utf-8"))
        for item in common_data:
            merged = dict(item)
            merged["role_slug"] = entry["role_slug"]
            merged["row_source"] = entry["row_source"]
            merged["row_index"] = entry["row_index"]
            merged["pairing_level"] = "paragraph-common-structure"
            combined.append(merged)
        for item in leftover_data:
            merged = dict(item)
            merged["role_slug"] = entry["role_slug"]
            merged["row_source"] = entry["row_source"]
            merged["row_index"] = entry["row_index"]
            merged["pairing_level"] = "paragraph-leftover-diff"
            combined.append(merged)

    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)
        f.write("\n")

    n_common = sum(1 for e in combined if e["pairing_level"] == "paragraph-common-structure")
    n_leftover = len(combined) - n_common
    print(f"Merged {len(plan)} rows into {combined_path}: {n_common} paragraph-common-structure entries, {n_leftover} paragraph-leftover-diff entries.")


if __name__ == "__main__":
    main()
```

### Step 8: Nest the merged output under each row's section-level match (final output clean-up)

Step 7's flat file is easy to filter/scan across all paragraphs at once, but it separates each paragraph-level result from the section-level context that `orchestrator-paragraph-structure-within-matched-section` was originally invoked with for that row (which paper sections were matched, why, and what question that match answers). This step produces a second, complementary deliverable: one entry per section-level row, with that row's own section-level match info at the top and its Step 7 paragraph-level results nested inside it — so a reader can see "this is what these sections were matched on, and here's how their paragraphs further break down" without cross-referencing two files. Each paper-side entry in the nested output also carries real paragraph text (a `paragraphs` array), inlined by looking up each row's Stage-0 pseudo-section files (the same files `extract-paragraphs-as-pseudo-sections` already writes to `out_dir` during Step 5, named `{paper-abbreviation}--{role_slug}-sections-with-paragraphs-and-questions.json`, using that row's own `paper_abbreviations` mapping from `dispatch-plan-verified.json` to build the filename) — not by relying on a `paperX_paragraphs` field on the paragraph-level common-structure/leftover entry itself, since that field is generally absent.

This is additive, not a replacement — keep Step 7's flat file too; they serve different reading patterns (flat = scan/filter every paragraph pairing at once; nested = read one matched section's full story top to bottom). **The script below is given verbatim — copy it byte-for-byte, do not modify it.**

**Joins paragraph-level entries back to real paper names by parsing each compound `section_number`** (format `"<paper_name>::<role_slug>::<paragraph_number>"`), **not by slot letter** (`paperA`/`paperB`/`paperNplus1`/...) — `extract-paragraphs-as-pseudo-sections` reassigns those letters fresh per row (sequential by presence order), so for any row spanning fewer than 5 papers they do not line up with the section-level file's own corpus-wide slot letters. This is the same reasoning as Step 1-4's per-row abbreviation computation — don't assume slot-letter identity carries across levels.

**Handles the N=2 vs. N=3+ schema difference** described above ("A real schema difference between N=2 and N=3+ rows") by branching on each row's own `n` (already recorded in `dispatch-plan-verified.json`), rather than assuming one schema for every row.

```bash
python3 nest_paragraph_results_under_sections.py dispatch-plan-verified.json <directory containing the output files> <section-level-common-structure.json> <section-level-leftover-differences.json> <corpus-name>-all-matched-sections-paragraph-structure-nested.json
```

```python
#!/usr/bin/env python3
"""
Step 8 (final output clean-up): re-nests the flat, row-by-row paragraph-level output
files (the same ones Step 7 merges) under each row's own SECTION-LEVEL match info -- the
section-level entry (per-paper section name/number, pairing_status, ancestor_questions,
and the question_the_sections_answer that section-level row answers) that
orchestrator-paragraph-structure-within-matched-section was originally invoked against for
that row in the first place. These are the same two files supplied as this whole skill's
own Inputs #1 and #2 at Step 0.

This is a distinct, ADDITIONAL deliverable from Step 7's flat merge -- Step 7 produces one
flat array of paragraph-level entries tagged by role_slug/row_source/row_index; this step
instead groups by row and nests each row's paragraph-level results inside that row's
section-level context, so a reader can see "this is what section X was originally matched
on, and here's how its paragraphs further break down" in one place without
cross-referencing two separate files.

Joins paragraph-level entries back to real paper names by parsing each compound
section_number (format "<paper_name>::<role_slug>::<paragraph_number>"), NOT by
paperA/paperB/paperNplus1/... slot letter -- those letters are reassigned fresh per row
(sequential by presence order) by extract-paragraphs-as-pseudo-sections, so for any row
spanning fewer than 5 papers they do NOT line up with the section-level file's own
corpus-wide slot letters.

Real paragraph text is now inlined for every paper side of every entry (added 2026-08-17),
pulled from that row's own Stage-0 pseudo-section files in out_dir (the same directory
Step 5's subagents wrote everything to). Each Stage-0 file is named
"{abbreviation}--{role_slug}-sections-with-paragraphs-and-questions.json", where
abbreviation comes from that row's own paper_abbreviations dict in
dispatch-plan-verified.json (NOT a full paper name -- Stage-0 filenames use the row-scoped
abbreviation, unlike a hypothetical full-name convention). Each Stage-0 file is
one-entry-per-paragraph (a pseudo-section per paragraph), keyed by a unique compound
section_number (format "<paper_name>::<role_slug>::<paragraph_number>"), so the join from
a paragraph-level entry's section_number into its row's Stage-0 lookup is a direct 1:1
lookup, not an aggregation. A missing Stage-0 file or a lookup miss is recorded as a
warning (the script still completes, paragraphs is left [] for that side) rather than a
hard error, matching this script's own established warning-not-error convention for
out-of-range rows.

Schema quirk handled explicitly (see this skill's own "A real schema difference between
N=2 and N=3+ rows" section): the base (N=2) pipeline's common-section-structure-by-
paragraphs-and-questions output uses an older field convention than the papernplus1/2/3
family -- basis_p1_p2/question_p1_p2/basis_p2_p1/question_p2_p1 for matches (no
pairing_status, no ancestor_questions field at all), and question_the_sections_both_answer
for leftovers, instead of pairing_status/basis_paperNplusK_to_pairing/ancestor_questions/
question_the_sections_answer. This script normalizes both into one consistent output shape
based on each row's own `n` (from dispatch-plan-verified.json), rather than assuming every
row shares one schema.

Refuses to nest if any row's status isn't "ok" -- same guard as Step 7, for the same
reason: fix or explicitly exclude a problem row rather than let its absence go unnoticed.

Usage:
    python3 nest_paragraph_results_under_sections.py <dispatch-plan-verified.json> <directory containing the output files> <section-level-common-structure.json> <section-level-leftover-differences.json> <combined-output.json>
"""
import json
import sys
from pathlib import Path

SLOT_LETTERS = ["paperA", "paperB", "paperNplus1", "paperNplus2", "paperNplus3"]
BASIS_SUFFIX_BY_N = {3: "papernplus1", 4: "papernplus2", 5: "papernplus3"}


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def paper_name_from_section_number(section_number):
    """Compound IDs look like '<paper_name>::<role_slug>::<paragraph_number>'.
    Returns None if section_number is missing or not in that shape."""
    if not section_number:
        return None
    parts = str(section_number).split("::")
    return parts[0] if parts else None


def build_stage0_paragraph_lookup(out_dir: Path, abbreviation: str, role_slug: str, warnings: list) -> dict:
    """Loads this row's Stage-0 pseudo-section file for one paper --
    {out_dir}/{abbreviation}--{role_slug}-sections-with-paragraphs-and-questions.json --
    and returns {compound_section_number: paragraphs}. Each Stage-0 entry is one
    paragraph's own pseudo-section (compound section_number is unique), so this is a
    direct 1:1 lookup, not an aggregation. `abbreviation` must come from this row's own
    paper_abbreviations dict in dispatch-plan-verified.json, NOT the paper's full name --
    Stage-0 filenames use the row-scoped abbreviation Stage 0 itself computed."""
    path = out_dir / f"{abbreviation}--{role_slug}-sections-with-paragraphs-and-questions.json"
    if not path.exists():
        warnings.append(f"Stage-0 file not found for role_slug={role_slug!r} abbreviation={abbreviation!r}: {path.name}")
        return {}
    lookup = {}
    for e in load_json(path):
        number = e.get("section_number")
        if number:
            lookup[number] = e.get("paragraphs", [])
    return lookup


def paragraphs_for(stage0_lookups: dict, paper_name: str, number, warnings: list):
    if number is None:
        return []
    lookup = stage0_lookups.get(paper_name)
    if lookup is None:
        warnings.append(f"No Stage-0 lookup loaded for paper {paper_name!r} (section_number={number!r})")
        return []
    if number not in lookup:
        warnings.append(f"Stage-0 lookup miss: paper={paper_name!r} section_number={number!r} not found in its Stage-0 file")
        return []
    return lookup[number]


def rekey_by_paper_name(entry: dict, stage0_lookups: dict, warnings: list) -> dict:
    """Returns {paper_name: {"section_name":..., "section_number":..., "paragraphs":[...]}}
    for one paragraph-level common-structure or leftover entry, keyed by real paper name
    instead of that row's own fresh slot-letter convention. Slots whose section_name and
    section_number are both null are omitted. paragraphs is now always populated via a
    Stage-0 lookup (stage0_lookups), not via a paperX_paragraphs field on the entry itself
    (which is generally absent on these files)."""
    by_paper = {}
    for slot in SLOT_LETTERS:
        name_field = f"{slot}_section_name"
        num_field = f"{slot}_section_number"
        if name_field not in entry:
            continue
        name = entry.get(name_field)
        number = entry.get(num_field)
        if name is None and number is None:
            continue
        paper_name = paper_name_from_section_number(number)
        if paper_name is None:
            continue
        by_paper[paper_name] = {
            "section_name": name,
            "section_number": number,
            "paragraphs": paragraphs_for(stage0_lookups, paper_name, number, warnings),
        }
    return by_paper


def normalize_common_entry(entry: dict, n: int) -> dict:
    if n == 2:
        basis = entry.get("basis_p1_p2") or entry.get("basis_p2_p1")
        question = entry.get("question_p1_p2") or entry.get("question_p2_p1")
        return {
            "basis": basis,
            "question_the_sections_answer": question,
            "pairing_status": None,  # not computed at n=2; predates this field
            "ancestor_questions": [],
        }
    suffix = BASIS_SUFFIX_BY_N.get(n)
    basis = entry.get(f"basis_{suffix}_to_pairing") or entry.get(f"basis_pairing_to_{suffix}")
    return {
        "basis": basis,
        "question_the_sections_answer": entry.get("question_the_sections_answer"),
        "pairing_status": entry.get("pairing_status"),
        "ancestor_questions": entry.get("ancestor_questions", []),
    }


def normalize_leftover_entry(entry: dict, n: int) -> dict:
    if n == 2:
        return {
            "direction": entry.get("direction"),
            "diff_type": entry.get("diff_type"),
            "basis": entry.get("basis"),
            "question_the_sections_answer": entry.get("question_the_sections_both_answer"),
            "ancestor_questions": [],
        }
    return {
        "direction": entry.get("direction"),
        "diff_type": entry.get("diff_type"),
        "basis": entry.get("basis"),
        "question_the_sections_answer": entry.get("question_the_sections_answer"),
        "ancestor_questions": entry.get("ancestor_questions", []),
    }


def section_level_papers_dict(section_entry: dict, paper_specs: list) -> dict:
    """Builds {paper_name: {"section_name":..., "section_number":...}} for the
    section-level row entry, using dispatch-plan's paper_specs to know which slot
    letters are present and which real paper name each maps to at the SECTION level
    (a different, corpus-wide letter convention from the paragraph-level files)."""
    out = {}
    for spec in paper_specs:
        slot = spec["slot"]
        paper_name = spec["name"]
        out[paper_name] = {
            "section_name": section_entry.get(f"{slot}_section_name"),
            "section_number": section_entry.get(f"{slot}_section_number"),
        }
    return out


def main() -> None:
    if len(sys.argv) < 6:
        print(__doc__)
        sys.exit(1)

    plan_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    section_common_path = Path(sys.argv[3])
    section_leftover_path = Path(sys.argv[4])
    combined_path = Path(sys.argv[5])

    plan = load_json(plan_path)
    section_common = load_json(section_common_path)
    section_leftover = load_json(section_leftover_path)

    not_ok = [e for e in plan if e.get("status") != "ok"]
    if not_ok:
        print(f"ERROR: {len(not_ok)} row(s) are not status=ok -- fix these before nesting:")
        for e in not_ok:
            print(f"  [{e['row_source']}#{e['row_index']}] role_slug={e['role_slug']!r} status={e.get('status')}")
        sys.exit(1)

    nested = []
    warnings = []

    for row in plan:
        row_source = row["row_source"]
        row_index = row["row_index"]
        role_slug = row["role_slug"]
        n = row["n"]
        paper_specs = row["paper_specs"]

        source_array = section_common if row_source == "common" else section_leftover
        if row_index >= len(source_array):
            warnings.append(f"{role_slug}: row_index {row_index} out of range in section-level {row_source} file")
            continue
        section_entry = source_array[row_index]

        section_level_match = {
            "papers": section_level_papers_dict(section_entry, paper_specs),
            "pairing_status": section_entry.get("pairing_status"),
            "ancestor_questions": section_entry.get("ancestor_questions", []),
            "question_the_sections_answer": section_entry.get("question_the_sections_answer"),
        }

        stage0_lookups = {
            spec["name"]: build_stage0_paragraph_lookup(
                out_dir, row["paper_abbreviations"][spec["name"]], role_slug, warnings
            )
            for spec in paper_specs
        }

        common_data = load_json(out_dir / row["expected_common_structure_file"])
        leftover_data = load_json(out_dir / row["expected_leftover_file"])

        para_common = [
            {"papers": rekey_by_paper_name(e, stage0_lookups, warnings), **normalize_common_entry(e, n)}
            for e in common_data
        ]
        para_leftover = [
            {"papers": rekey_by_paper_name(e, stage0_lookups, warnings), **normalize_leftover_entry(e, n)}
            for e in leftover_data
        ]

        nested.append({
            "role_slug": role_slug,
            "row_source": row_source,
            "row_index": row_index,
            "n": n,
            "section_level_match": section_level_match,
            "paragraph_level_common_structure": para_common,
            "paragraph_level_leftovers": para_leftover,
        })

    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(nested, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Nested {len(nested)}/{len(plan)} rows.")
    if warnings:
        print(f"\n{len(warnings)} WARNING(S):")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("No warnings.")
    print(f"\nWrote {combined_path}")


if __name__ == "__main__":
    main()
```

If this script reports any warnings (a row's `row_index` out of range in the section-level file, or a Stage-0 file not found / lookup miss), stop and investigate before treating the nested file as complete — a row-index warning means `dispatch-plan-verified.json` and the section-level input files have drifted out of sync (for example, the section-level comparison was re-run after the dispatch plan was built, changing row counts or ordering); a Stage-0 warning means either that row's Stage-0 files never got written correctly in Step 5, or the abbreviation used to build the lookup filename doesn't match what's actually on disk. Also watch for duplicate output files under slightly different filenames for the same row (e.g. an abbreviated-paper-name filename alongside a literal-paper-name filename) — if the section-level comparison for a row was ever re-run after an earlier pass, both an old and a current file can end up coexisting on disk; always resolve which is current (compare modification times, and spot-check paragraph text/counts against the paper's own current `sections-with-paragraph-content(-no-appendices).json`) before pointing this step at one of them.

### Step 9: Report to the user

State: how many section-level rows were processed vs. skipped (non-alignable, nothing to compare), how many subagent batches ran and at what size, any rows that needed a re-dispatch in Step 6 (and why — including any abbreviation-mismatch or n/present_slots-mismatch cases), the final flat-merge counts from Step 7 (paragraph-common-structure vs. paragraph-leftover-diff), and the final nested-merge row count from Step 8. Point out anything that stands out — a role with an unusually high leftover rate at the paragraph level, a row that spanned far fewer papers than the corpus total, any repeated Step 6 failures for the same row, or any Step 8 warnings.

## Output

- `dispatch-plan.json` / `dispatch-plan-verified.json` — the per-row working plan and its post-verification state, including each row's predicted `paper_abbreviations` (kept for traceability, not meant as a user-facing deliverable). **Never edited to match a subagent's output** — see "Step 5 prompts must copy row facts verbatim" above.
- Every intermediate and final file each per-row `orchestrator-paragraph-structure-within-matched-section` run produces (pseudo-section files named with their own Stage-0-computed abbreviations, both-directions passes, pairing files, that row's own two final files) — kept, same convention as every orchestrator in this family.
- **`{corpus-name}-all-matched-sections-paragraph-structure.json`** — Step 7's flat deliverable: one array, every entry carrying `role_slug`, `row_source`, `row_index`, `pairing_level`, plus whatever fields that row's own paragraph-level common-structure/leftover entry already had.
- **`{corpus-name}-all-matched-sections-paragraph-structure-nested.json`** — Step 8's section-grouped deliverable: one array, one entry per section-level row, each carrying `role_slug`, `row_source`, `row_index`, `n`, `section_level_match` (that row's section-level per-paper section name/number, `pairing_status`, `ancestor_questions`, `question_the_sections_answer`), `paragraph_level_common_structure`, and `paragraph_level_leftovers`. Every paper-side entry under `papers` in the latter two now also carries a `paragraphs` array with real inlined paragraph text (pulled from that row's Stage-0 files), not just `section_name`/`section_number`.

## Common mistakes to avoid

- **Describing a row's `n`, `present_slots`, `paper_specs`, or which papers participate from memory when writing a Step 5 subagent prompt, instead of copying those fields verbatim from that row's `dispatch-plan.json` entry.** This is the exact mistake that caused a real incident (2026-08-18): a row was briefed as excluding a paper that, per the row's own already-correct `dispatch-plan.json` entry, genuinely participated — the subagent had no way to catch a wrong instruction it was never in a position to verify. See "Step 5 prompts must copy row facts verbatim" above.
- **Writing, authorizing, or silently accepting a custom one-off variant of the Stage-0 extraction script for a specific row** (e.g. excluding a paragraph because it "probably" belongs to a sibling row, or merging sections based on an unverified guess) instead of running `extract-paragraphs-as-pseudo-sections`' own standard script unmodified. This is a real incident (2026-08-18), documented in both this skill's own "Step 5 must never authorize a custom Stage-0 script" section above and in `extract-paragraphs-as-pseudo-sections`' own "Stage 0 is strictly mechanical" section. If a row seems to need special handling, that's a stop-and-ask-the-user moment, not a reason to write bespoke extraction code — the downstream matching skills already handle "no correspondence found" as a normal, expected, evidence-based outcome.
- **Including any information about a sibling row in a Step 5 subagent's prompt, even hedged as "unverified context."** See "Rows never need to know about each other" above — this carve-out used to exist and is what let the custom-script incident happen; it's been removed. If a section maps to multiple rows, every row's Stage 0 independently extracts that section's full paragraph set on its own; downstream matching's legitimate "no match" outcome is what correctly excludes a paragraph from a row it doesn't belong to, not anything the orchestrator tells a subagent in advance.
- **Writing a custom variant of ANY of this skill's own bundled scripts (Steps 1-4, 6, 7, 8)** instead of copying them verbatim — same principle as the Stage-0 rule, applied to this skill's own mechanical steps. If one of these scripts flags or produces something unexpected, investigate the underlying data, don't rewrite the script.
- **Editing `dispatch-plan.json`'s row-level facts (`n`, `present_slots`, `paper_specs`, `expected_*_file`) to match what a subagent actually produced, after Step 6 reports a mismatch.** These fields are mechanically derived and correct from the moment Steps 1-4 finish — a mismatch is evidence the Step 5 prompt was wrong, not evidence the plan needs correcting. Fix the prompt and re-dispatch; never retcon the plan.
- **Dispatching all rows in one giant batch instead of small checked-in batches.** The whole point of batching is to catch a systemic problem (bad paper spec, wrong file) after a few rows rather than after all of them.
- **Dispatching a batch's subagents across separate messages instead of together in one message.** They need to run in parallel, not sequentially — sequential dispatch defeats the purpose of isolating context per row while still being fast.
- **Skipping Step 6 and merging directly from what each subagent claims it wrote.** Subagent self-reports can be wrong (wrong path, partial failure) — always verify against the actual files on disk before merging.
- **Assuming role-slug is derived per-row independently.** It's computed in one pass over the *entire* usable row list specifically so cross-row FILENAME collisions (two different rows both anchored on a section named "Introduction," for instance) get caught and disambiguated — don't slugify rows one at a time in isolation. This is a purely mechanical, name-based bookkeeping pass; it is unrelated to, and must not be confused with, the (now-removed) cross-row *content* reasoning described in "Rows never need to know about each other" above.
- **Computing paper-name abbreviations once over the whole corpus instead of fresh per row.** This was the exact mistake this fix corrects: `extract-paragraphs-as-pseudo-sections` only ever sees one row's present-slot papers per invocation, so its abbreviation lengths are scoped to that row's own subset, not the corpus. Predicting filenames with a corpus-wide abbreviation set can silently diverge from what Stage 0 actually produces. Always recompute `unique_abbreviations()` per row, over exactly that row's paper names.
- **Passing paper specs in the wrong order, or a different order than the one used when the section-level comparison was originally run.** `paperA`/`paperB`/etc. are fixed corpus-wide identity labels; get the order wrong and every row's paper resolution will point at the wrong file.
- **Treating a `"non-alignable"` leftover row as a bug in this skill.** It's correctly and silently skipped — there's only one real paper, nothing to drill into. Only `"alignable"` leftover rows are included.
- **Re-deriving `orchestrator-paragraph-structure-within-matched-section`'s own stage-dispatch logic here.** This skill never reasons about N-dependent stages itself — that's entirely delegated to the per-row skill, run unmodified inside each subagent.
- **Merging or nesting rows whose status isn't `"ok"`.** Steps 7 and 8 both refuse this on purpose — fix or explicitly exclude a problem row rather than let its absence go unnoticed in either combined file.
- **Restoring `slugify()`'s `max_len` back to its original 40, now that paper names are abbreviated.** Even with 4-character abbreviations, a 40-character role-slug at N=5 can still exceed the OS filename limit — see the script's own "Why 25" comment for the arithmetic. 25 is the deliberately-recomputed safe value, not an arbitrary leftover from the earlier ad hoc fix.
- **Assuming a paragraph-level entry's `paperA`/`paperB`/`paperNplus1`/... slot letters mean the same paper as the section-level file's same-named slots.** They don't, for any row spanning fewer than 5 papers — see "Predicted filenames now use per-row paper-name abbreviations" above and Step 8's own paper-name-parsing approach. Always join by parsing the real paper name out of a compound `section_number`, never by assuming slot-letter identity carries across levels.
- **In Step 8, assuming every row shares one schema for its basis/question fields.** N=2 rows genuinely use a different, older field convention than N=3+ rows (see "A real schema difference between N=2 and N=3+ rows" above) — this is a real, permanent difference between the base skill and the papernplus1/2/3 family, not staleness to paper over. Branch on each row's own `n`.
- **In Step 8, trusting `dispatch-plan.json`'s `expected_common_structure_file`/`expected_leftover_file` without checking for a stale duplicate on disk.** If a row's section-level comparison was ever re-run after the dispatch plan was originally built (e.g. after fixing an upstream extraction bug and redoing that row), the old pre-redo output file can still exist under a slightly different filename (e.g. an earlier paper-name-abbreviation convention) alongside the current one, and the dispatch plan may still point at the stale one. Spot-check modification times and paragraph content/counts against the paper's current extracted data before trusting Step 8's output as final — this is exactly what a real run of this skill surfaced.
- **Building a Stage-0 filename from a paper's full literal name instead of that row's own abbreviation.** Stage-0 pseudo-section filenames use `{abbreviation}--{role_slug}`, where the abbreviation is computed fresh per row by `extract-paragraphs-as-pseudo-sections` and recorded in `dispatch-plan-verified.json`'s own `paper_abbreviations` — always look it up from there rather than assuming the full paper name or a corpus-wide abbreviation.
- **Opening a PDF at any point.** Everything needed already exists in the per-paper paragraph-content files and the section-level comparison files.
