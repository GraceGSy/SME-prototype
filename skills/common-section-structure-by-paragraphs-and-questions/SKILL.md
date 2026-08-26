---
name: "common-section-structure-by-paragraphs-and-questions"
description: "Given the NORMALIZED combined JSON output of \"normalize-section-mapping-both-directions\" (a *-normalized.json file, \"p1-p2\"/\"p2-p1\" keys, both arrays using consistent paperA_*/paperB_* fields) plus each paper's own sections-with-paragraphs-and-questions.json, writes {paperA-name}-{paperB-name}-common-section-structure.json (confirmed matches) and {paperA-name}-{paperB-name}-leftover-section-differences.json (everything else, tagged alignable/non-alignable). A hard Step 3 validator now blocks completion until every entry has a real question or is verified legitimately empty. No PDF opened. Run \"normalize-section-mapping-both-directions\" first if only the raw combined file exists. Use for confirmed common structure and/or leftover differences between two papers' sections."
---

# Common Section Structure (by Paragraphs and Questions)

## What this is (and isn't)

This is a small, mechanical downstream step on top of `normalize-section-mapping-both-directions`'s output: given that skill's normalized combined JSON (the `*-normalized.json` file with `p1-p2` and `p2-p1` keys, both already using consistent `paperA_*`/`paperB_*` fields), it splits every entry into two files -- the pairings both directional passes independently agree on, and everything else. It does not run any new matching itself and does not open a PDF.

Unlike `paper-section-alignment`'s PDF-based equivalent, which splits its non-confirmed entries into two separate files (`alignable-section-diffs.json` and `non-alignable-section-diffs.json`), this skill puts everything that isn't a confirmed match into a single `leftover-section-differences.json` file, distinguished by `reason` and `diff_type` fields rather than by filename -- that's what was asked for here, not a design accident.

### History

Originally, `section-mapping-by-paragraphs-and-questions-both-directions`'s combined output had an asymmetry: in its `p1-p2` array, `paper1_*` fields described `fileA` and `paper2_*` described `fileB`; in its `p2-p1` array, it was reversed. This skill originally normalized that asymmetry internally; that normalization has since been pulled out into its own standalone skill, `normalize-section-mapping-both-directions`, and this skill now requires its `-normalized.json` output as input rather than doing that fix itself.

This skill also originally produced only the confirmed-matches file, explicitly leaving the leftover/diff entries out of scope. That's no longer true -- the leftover output described below, including the `diff_type` field, was added afterward, on request.

**Why this skill now has a hard completeness gate (Step 3).** This skill's own output -- `question_p1_p2`/`question_p2_p1` on common entries, `question_the_sections_both_answer` on leftover entries -- is the base-generation foundation every downstream fold-in skill in this project reads: `directional-section-mapping-paragraphs-and-questions-papernplus1` and its reverse-direction sibling both treat this file's question field as first-class evidence for role correspondence when folding in a third paper, not just a hint. A real 5-paper corpus run surfaced that a downstream generation's own question-composition step can be silently skipped with nothing catching it at the time -- and when that was traced back, the root turned out to originate here, at the very first pairwise comparison, several matching stages before the gap became visible. This step exists to catch that here, at the source, every run -- mirroring the same hard-gate pattern already used by the papernplus1/2/3 common-section-structure family's own Step 4.

**Any script in this skill's Workflow is given verbatim and must be copied byte-for-byte, never authored or modified.** Wherever a step says "write the script," that means transcribe the exact code shown into a file -- not compose a variant, not add a flag, not adjust behavior for a specific case. If a script's documented behavior seems wrong for what you're trying to do, that's a stop-and-ask-the-user moment, not a reason to write custom logic (see `extract-paragraphs-as-pseudo-sections`'s "Stage 0 is strictly mechanical" section for the real incident this rule generalizes from).

**Awareness note: this skill can't recover a role that was never split out upstream.** It only reorganizes and confirms correspondences the two `directional-section-mapping-by-paragraphs-and-questions` passes already produced -- it does no paragraph-level reading of its own. If a source paper folds a narrow role (e.g. verbatim materials, a methodology-only aside) into a much broader, denser section without giving it its own heading, and the upstream directional-mapping pass failed to split that role into its own entry, there's nothing for this skill to notice or fix after the fact -- it only ever sees whatever entries that pass already produced. See `directional-section-mapping-by-paragraphs-and-questions`'s "A role doesn't need its own container to be worth splitting out" guidance for the full explanation of this risk.

## Inputs

Three files:

1. The **normalized** combined output of `normalize-section-mapping-both-directions`, named `{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions-normalized.json` -- a JSON object with exactly two keys, `p1-p2` and `p2-p1`, each a plain array of six-field entries already using consistent identity: `paperA_section_name`, `paperA_section_number`, `paperB_section_name`, `paperB_section_number`, `basis`, `question_the_sections_both_answer`, with `paperA_*` meaning `fileA` and `paperB_*` meaning `fileB` in *both* arrays.
2. `{paperA-name}-sections-with-paragraphs-and-questions.json` -- paperA's own extracted file, from `annotate-section-questions-given-paragraphs` (or `orchestrator-extract-sections-paragraphs-and-questions`). Used only by Step 3's validator, to look up paragraph counts per matched section for the empty-content check.
3. `{paperB-name}-sections-with-paragraphs-and-questions.json` -- same, for paperB.

**Do not accept the raw both-directions combined file as input 1** (the one still using `paper1_*`/`paper2_*` field names, with identity reversed between `p1-p2` and `p2-p1`). If that's all the user has, run `normalize-section-mapping-both-directions` on it first and use *its* output as this skill's input. The bundled script below will fail with a clear error if given the raw file by mistake, rather than silently producing wrong results -- but don't rely on that as the first line of defense; check the filename and a sample entry's field names before running it.

## Workflow

### Step 1: Confirm the input is the normalized combined file

Check the filename ends in `-normalized.json` and that a sample entry in `p1-p2` (or `p2-p1`) has `paperA_section_name`/`paperB_section_name` fields, not `paper1_section_name`/`paper2_section_name`. If it's the raw combined file instead, point the user to `normalize-section-mapping-both-directions` (or run it yourself first) before continuing here. Also confirm inputs 2 and 3 (each paper's own extracted file) are present -- Step 3 can't verify completeness without them.

### Step 2: Run the matching script

Don't do this by hand -- it's a mechanical exact-match comparison across potentially dozens of entries in two arrays, and a script won't misremember an entry, forget which array it came from, or misclassify why a pairing didn't confirm, the way re-deriving it by eye can.

Copy the script below byte-for-byte into a local file (e.g. `find_bidirectional_matches.py`, in the same directory as the input file) -- this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant. Then run it:

```bash
python3 find_bidirectional_matches.py {paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions-normalized.json
```

```python
#!/usr/bin/env python3
"""
Reads the NORMALIZED combined output of normalize-section-mapping-both-directions
(a JSON object with "p1-p2" and "p2-p1" keys, where every entry in BOTH arrays
already uses consistent paperA_*/paperB_* fields -- paperA always means fileA,
paperB always means fileB) and splits every entry into two files:

  - {prefix}-common-section-structure.json        confirmed bidirectional matches
  - {prefix}-leftover-section-differences.json     everything else

This assumes the paper1/paper2 identity swap between p1-p2 and p2-p1 has
already been fixed upstream by normalize-section-mapping-both-directions --
it does NOT do that normalization itself. If given the raw (un-normalized)
combined output of section-mapping-by-paragraphs-and-questions-both-directions
instead, this script will fail loudly rather than silently producing wrong
results -- normalize it first.

Matching is done on section NUMBER, falling back to exact section NAME only
for unnumbered sections (Abstract, References, Acknowledgments, etc.), since
two independently-derived passes may annotate the same section with slightly
different name text even when they agree on which section it is, and every
unnumbered section would otherwise collide into one false match.

A pairing where either side has no match at all is never treated as a
"confirmed match" -- it goes to the leftover file instead, along with any
pairing that matched in only one direction (found in p1-p2 but not
confirmed by p2-p1, or vice versa). Every leftover entry is additionally
tagged with a diff_type: "non-alignable" if either paper's section name is
null/empty (no counterpart at all), or "alignable" if both papers have a
named section but the pairing just wasn't bidirectionally confirmed --
mirroring paper-section-alignment's alignable/non-alignable vocabulary.

Usage:
    python3 find_bidirectional_matches.py combined-section-mapping-normalized.json [output_dir]

If output_dir isn't given, writes both files to the same directory as the
input, using <prefix> derived from the input filename with
"-section-mapping-by-paragraphs-and-questions-normalized.json" stripped (or
the full input stem if that suffix isn't present).
"""

import json
import sys
from collections import defaultdict
from pathlib import Path


def norm(value):
    """Normalize a value for comparison: None/empty-ish stays None, else stripped string."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def validate_normalized(entries: list, direction_label: str) -> None:
    """Fail loudly if the entries don't look like normalize-section-mapping-both-directions
    output -- i.e. catch the case where someone fed this the raw, un-normalized
    combined file (which uses paper1_*/paper2_* fields, not paperA_*/paperB_*)."""
    for e in entries:
        if "paperA_section_name" not in e or "paperB_section_name" not in e:
            raise ValueError(
                f"'{direction_label}' entries don't look normalized (missing "
                "paperA_section_name/paperB_section_name -- found "
                f"{sorted(e.keys())} instead). This script only accepts the "
                "*-normalized.json output of normalize-section-mapping-both-directions. "
                "Run that skill on the raw combined file first, then pass its "
                "-normalized.json output here."
            )


def side_key(number, name):
    """Join key for one side of a pairing: section number when the section is
    numbered, else the exact section name (unnumbered sections like Abstract,
    References, Acknowledgments are only ever matched by exact title, so name
    is the correct join key there -- falling back to number for those would
    collide every unnumbered section into one (None, None) bucket regardless
    of whether they're actually the same section). Returns None if the side
    has no section at all (name is also null/empty)."""
    num = norm(number)
    if num is not None:
        return ("num", num)
    name_norm = norm(name)
    return ("name", name_norm) if name_norm is not None else None


def key_of(entry: dict):
    """Composite key for a pairing, or None if this entry can never be part of
    a confirmed match (either side has no section at all)."""
    a_key = side_key(entry.get("paperA_section_number"), entry.get("paperA_section_name"))
    b_key = side_key(entry.get("paperB_section_number"), entry.get("paperB_section_name"))
    if a_key is None or b_key is None:
        return None
    return (a_key, b_key)


def diff_type_of(paperA_name, paperB_name) -> str:
    """'non-alignable' if either side has no section name at all (null or
    empty/whitespace); 'alignable' if both sides name an actual section but
    the pairing just wasn't confirmed from both directions."""
    if norm(paperA_name) is None or norm(paperB_name) is None:
        return "non-alignable"
    return "alignable"


def leftover_entry(entry: dict, direction: str, reason: str) -> dict:
    paperA_name = entry.get("paperA_section_name")
    paperB_name = entry.get("paperB_section_name")
    return {
        "direction": direction,
        "reason": reason,
        "diff_type": diff_type_of(paperA_name, paperB_name),
        "paperA_section_name": paperA_name,
        "paperA_section_number": entry.get("paperA_section_number"),
        "paperB_section_name": paperB_name,
        "paperB_section_number": entry.get("paperB_section_number"),
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

    if not isinstance(combined, dict) or "p1-p2" not in combined or "p2-p1" not in combined:
        raise ValueError(f"{input_path} must be a JSON object with 'p1-p2' and 'p2-p1' keys")

    p1_p2 = combined["p1-p2"]
    p2_p1 = combined["p2-p1"]
    validate_normalized(p1_p2, "p1-p2")
    validate_normalized(p2_p1, "p2-p1")

    p1_p2_by_key = defaultdict(list)
    for e in p1_p2:
        k = key_of(e)
        if k is not None:
            p1_p2_by_key[k].append(e)
    p2_p1_by_key = defaultdict(list)
    for e in p2_p1:
        k = key_of(e)
        if k is not None:
            p2_p1_by_key[k].append(e)

    common_keys = set(p1_p2_by_key.keys()) & set(p2_p1_by_key.keys())

    # --- Confirmed bidirectional matches ---
    common = []
    for key in common_keys:
        for fwd in p1_p2_by_key[key]:
            for rev in p2_p1_by_key[key]:
                common.append({
                    "paperA_section_name": fwd["paperA_section_name"],
                    "paperA_section_number": fwd["paperA_section_number"],
                    "paperB_section_name": fwd["paperB_section_name"],
                    "paperB_section_number": fwd["paperB_section_number"],
                    "basis_p1_p2": fwd.get("basis"),
                    "question_p1_p2": fwd.get("question_the_sections_both_answer"),
                    "basis_p2_p1": rev.get("basis"),
                    "question_p2_p1": rev.get("question_the_sections_both_answer"),
                })

    def common_sort_key(e):
        n = e["paperA_section_number"]
        return (n is None, n if n is not None else "")

    common.sort(key=common_sort_key)

    # --- Leftovers: everything not part of a confirmed match ---
    leftovers = []
    for e in p1_p2:
        k = key_of(e)
        if k is None:
            leftovers.append(leftover_entry(e, "p1-p2", "no_counterpart_found"))
        elif k not in common_keys:
            leftovers.append(leftover_entry(e, "p1-p2", "matched_one_direction_only"))
    for e in p2_p1:
        k = key_of(e)
        if k is None:
            leftovers.append(leftover_entry(e, "p2-p1", "no_counterpart_found"))
        elif k not in common_keys:
            leftovers.append(leftover_entry(e, "p2-p1", "matched_one_direction_only"))

    def leftover_sort_key(e):
        n = e["paperA_section_number"]
        return (e["direction"], n is None, n if n is not None else "")

    leftovers.sort(key=leftover_sort_key)

    # --- Derive output prefix/dir ---
    if len(sys.argv) >= 3:
        output_dir = Path(sys.argv[2])
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = input_path.parent

    stem = input_path.name
    suffix = "-section-mapping-by-paragraphs-and-questions-normalized.json"
    prefix = stem[: -len(suffix)] if stem.endswith(suffix) else input_path.stem

    common_path = output_dir / f"{prefix}-common-section-structure.json"
    leftover_path = output_dir / f"{prefix}-leftover-section-differences.json"

    with open(common_path, "w", encoding="utf-8") as f:
        json.dump(common, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(leftover_path, "w", encoding="utf-8") as f:
        json.dump(leftovers, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"p1-p2 pairings: {len(p1_p2)}")
    print(f"p2-p1 pairings: {len(p2_p1)}")
    print(f"Bidirectional (common) matches: {len(common)}")
    for e in common:
        print(f"  [common]   {e['paperA_section_name']} ({e['paperA_section_number']})  <->  {e['paperB_section_name']} ({e['paperB_section_number']})")
    print(f"Leftover (non-bidirectional) entries: {len(leftovers)}")
    for e in leftovers:
        print(f"  [leftover:{e['diff_type']}/{e['reason']}, {e['direction']}]  {e['paperA_section_name']} ({e['paperA_section_number']})  <->  {e['paperB_section_name']} ({e['paperB_section_number']})")
    print(f"\nWrote {common_path}")
    print(f"Wrote {leftover_path}")


if __name__ == "__main__":
    main()
```

The script infers `{paperA-name}-{paperB-name}` from the input filename automatically (stripping the known `-section-mapping-by-paragraphs-and-questions-normalized.json` suffix) -- you don't need to re-ask the user for the paper names. If the input file doesn't follow that naming convention, the script falls back to the file's full stem; check both resulting output filenames look sensible before reporting it as done, and pass an explicit output directory as a second argument if you want the files elsewhere.

### Step 3: Validate completeness (hard gate — do not proceed until this passes)

Step 2 mechanically carries forward whatever `basis`/`question_the_sections_both_answer` values the upstream directional-mapping passes already produced -- but if one of those passes ever left an entry's question unfilled, this skill's own output would silently carry that gap forward as `question_p1_p2`/`question_p2_p1`/`question_the_sections_both_answer` being `null`, and every downstream skill in this project (starting with `section-pairings-with-paragraphs-and-questions` and continuing through the entire papernplus1/2/3 fold-in family) treats this file's question fields as first-class, trustworthy evidence. A real 5-paper corpus run traced exactly this kind of gap all the way back to this generation -- the very first pairwise comparison -- several matching stages before anyone noticed. This step exists to catch that here, mechanically, every run. **Do not report this skill's output as done, and do not let a downstream skill (`section-pairings-with-paragraphs-and-questions`, a third-paper fold-in, anything) consume these files until this step passes clean.**

Copy the script below byte-for-byte into a local file (e.g. `validate_common_structure_step2_complete.py`) -- this is a verbatim transcription, not an authoring step; do not add, remove, or modify anything, even a flag or comment. If a specific case seems to call for different script behavior, that's a stop-and-ask-the-user moment, not a reason to write a variant. Then run it with the two files Step 2 just wrote plus each paper's own extracted file (inputs 2 and 3):

```bash
python3 validate_common_structure_step2_complete.py {paperA-name}-{paperB-name}-common-section-structure.json {paperA-name}-{paperB-name}-leftover-section-differences.json {paperA-name}-sections-with-paragraphs-and-questions.json {paperB-name}-sections-with-paragraphs-and-questions.json
```

```python
#!/usr/bin/env python3
"""
Step 3 (hard gate): validates that {prefix}-common-section-structure.json and
{prefix}-leftover-section-differences.json satisfy this skill's own completeness rule:
every entry has a real question (question_p1_p2 AND question_p2_p1 for common entries;
question_the_sections_both_answer for leftover entries), UNLESS every side actually
present on that entry has zero paragraphs (the one legitimate empty-content case, e.g.
a References section matched purely on title) -- same convention as every completeness
gate elsewhere in this project (the papernplus1/2/3 family's own Step 4 gates).

Paragraph counts are looked up from each paper's own sections-with-paragraphs-and-questions.json
(or sections-with-paragraph-content.json) file, never assumed from the entry's own fields.

Exit 0: every entry either has a real question or is verified legitimately empty -- Step 2
is genuinely complete, safe to report this skill's output as done.
Exit 1: one or more entries are missing a question with real content present. Do not report
success. Go back to Step 2's directional-mapping passes, compose a real question for each
entry listed below, rewrite both files, and re-run this validator.

Usage:
    python3 validate_common_structure_step2_complete.py common.json leftover.json paperA-sections-with-paragraphs-and-questions.json paperB-sections-with-paragraphs-and-questions.json
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


def build_lookup(sections):
    lookup = {}
    for e in sections:
        key = side_key(e.get("section_number"), e.get("section_name"))
        if key is not None:
            lookup[key] = e.get("paragraphs", [])
    return lookup


def present_and_count(lookup, number, name, missing_lookups, label):
    """Returns (is_present, paragraph_count_or_None). is_present is False only when
    this side has no section at all (name is null/empty) -- the normal, expected case
    for a leftover entry's absent side."""
    if norm(name) is None:
        return False, None
    key = side_key(number, name)
    if key is None or key not in lookup:
        missing_lookups.append((label, name, number))
        return True, None  # present but unverifiable -- do NOT treat as legitimately empty
    return True, len(lookup[key])


def main():
    common_path, leftover_path, paperA_path, paperB_path = (Path(a) for a in sys.argv[1:5])
    common = json.load(open(common_path, encoding="utf-8"))
    leftover = json.load(open(leftover_path, encoding="utf-8"))
    paperA_sections = json.load(open(paperA_path, encoding="utf-8"))
    paperB_sections = json.load(open(paperB_path, encoding="utf-8"))

    lookup_A = build_lookup(paperA_sections)
    lookup_B = build_lookup(paperB_sections)
    missing_lookups = []
    violations = []

    # Common entries always have both sides present (per this skill's own schema guarantee).
    for e in common:
        _, countA = present_and_count(lookup_A, e.get("paperA_section_number"), e.get("paperA_section_name"), missing_lookups, "paperA")
        _, countB = present_and_count(lookup_B, e.get("paperB_section_number"), e.get("paperB_section_name"), missing_lookups, "paperB")
        both_empty = (countA == 0) and (countB == 0)
        q1 = e.get("question_p1_p2")
        q2 = e.get("question_p2_p1")
        if (q1 is None or q2 is None) and not both_empty:
            violations.append(("common", e, countA, countB))

    # Leftover entries may have only one side present.
    for e in leftover:
        presentA, countA = present_and_count(lookup_A, e.get("paperA_section_number"), e.get("paperA_section_name"), missing_lookups, "paperA")
        presentB, countB = present_and_count(lookup_B, e.get("paperB_section_number"), e.get("paperB_section_name"), missing_lookups, "paperB")
        present_counts = [c for present, c in ((presentA, countA), (presentB, countB)) if present]
        legit_empty = bool(present_counts) and all(c == 0 for c in present_counts)
        q = e.get("question_the_sections_both_answer")
        if q is None and not legit_empty:
            violations.append(("leftover", e, countA, countB))

    if violations:
        print(f"BLOCKED: {len(violations)} entries have a missing question that is NOT "
              f"legitimately empty-content. Step 2 is incomplete -- do not report this "
              f"skill's output as done.")
        for kind, e, countA, countB in violations:
            print(f"  [{kind}] paperA={e.get('paperA_section_name')!r}({countA} paragraphs), "
                  f"paperB={e.get('paperB_section_name')!r}({countB} paragraphs)")
        if missing_lookups:
            print(f"\n{len(missing_lookups)} paragraph lookup(s) could not be resolved against "
                  f"the paperA/paperB files -- these count as unverified, not empty:")
            for label, name, num in missing_lookups:
                print(f"  - {label}: {name!r} ({num!r})")
        sys.exit(1)

    print(f"Validation passed: {len(common)} common-structure + {len(leftover)} leftover "
          f"entries all have real question(s) or are verified legitimately empty. Safe to report.")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

If the script exits 0, move on to Step 4. **If it exits 1**, it lists every entry with a missing question that isn't legitimately empty-content -- go back to Step 2's own upstream inputs (the `p1-p2`/`p2-p1` directional-mapping passes), compose a real question for each entry listed, rewrite both output files, and re-run this validator. Repeat until it passes clean before moving on.

### Step 4: Report to the user

State both counts (e.g. "8 confirmed matches; 13 leftover entries -- 11 non-alignable (no counterpart at all) and 2 alignable (matched from only one direction)"), and don't just dump the JSON. Distinguish `diff_type` when you summarize -- `non-alignable` is a real structural difference between the papers, while `alignable` is more often a genuine-but-weaker or ambiguous correspondence worth a second look, and conflating the two in your summary loses exactly the distinction the field exists to preserve. Confirm Step 3's validator exited 0 before reporting anything as done -- if it caught and you had to fix a gap, mention that explicitly rather than folding it silently into the final counts.

## Output

Two files, both saved in the same directory as the input unless the user specifies otherwise:

| File | Contents |
|---|---|
| `{paperA-name}-{paperB-name}-common-section-structure.json` | Pairings both directional passes independently agree on |
| `{paperA-name}-{paperB-name}-leftover-section-differences.json` | Every remaining entry from either pass, each tagged `alignable` or `non-alignable` |

Every entry in the input's `p1-p2` and `p2-p1` arrays ends up in exactly one of these two files -- nothing is silently dropped.

### Output schema (strict)

**`common-section-structure.json`** -- a JSON array:

```json
{
  "paperA_section_name": "string",
  "paperA_section_number": "string or null (null only for inherently unnumbered sections, e.g. Abstract)",
  "paperB_section_name": "string",
  "paperB_section_number": "string or null, same rule as paperA_section_number",
  "basis_p1_p2": "string -- the basis text from the p1-p2 pass's version of this pairing",
  "question_p1_p2": "string -- the question_the_sections_both_answer text from the p1-p2 pass. Non-null unless both sides have zero paragraphs -- Step 3 enforces this",
  "basis_p2_p1": "string -- the basis text from the p2-p1 pass's independently-derived version of the same pairing",
  "question_p2_p1": "string -- the question_the_sections_both_answer text from the p2-p1 pass. Non-null unless both sides have zero paragraphs -- Step 3 enforces this"
}
```

Every entry here has both `paperA_section_name`/`paperA_section_number` and `paperB_section_name`/`paperB_section_number` non-null -- a pairing where one side had no match at all can never appear here.

**`leftover-section-differences.json`** -- a JSON array:

```json
{
  "direction": "\"p1-p2\" or \"p2-p1\" -- which directional pass produced this entry",
  "reason": "\"no_counterpart_found\" (the other paper's section field is null) or \"matched_one_direction_only\" (both sides are named, but the other pass didn't independently confirm this pairing)",
  "diff_type": "\"non-alignable\" if paperA_section_name or paperB_section_name is null/empty; \"alignable\" if both are named (always in lockstep with reason -- non-alignable exactly when reason is no_counterpart_found)",
  "paperA_section_name": "string, or null if this entry's owning section was on paperB's side (i.e. direction is p2-p1 and no paperA counterpart was found)",
  "paperA_section_number": "string or null",
  "paperB_section_name": "string, or null if this entry's owning section was on paperA's side (i.e. direction is p1-p2 and no paperB counterpart was found)",
  "paperB_section_number": "string or null",
  "basis": "string, carried over unchanged from the source entry",
  "question_the_sections_both_answer": "string or null -- null only when every present side has zero paragraphs. Step 3 enforces this"
}
```

`reason` and `diff_type` are intentionally two different vocabularies for the same underlying distinction -- `reason` is this skill's own terminology, `diff_type` mirrors `paper-section-alignment`'s `alignable`/`non-alignable` filenames so the two skills' outputs are easy to reason about together. Keep both; don't drop either. Don't add extra fields to either file beyond what's listed here (no `confidence`, no `match_type` on the common file; nothing beyond `direction`/`reason`/`diff_type` plus the six shared fields on the leftover file).

## Common mistakes to avoid

- **Running this against the raw both-directions combined file instead of the normalized one.** The raw file still has `paper1_*`/`paper2_*` fields with reversed identity between `p1-p2` and `p2-p1` -- run `normalize-section-mapping-both-directions` on it first. The bundled script will refuse to run rather than silently mis-match, but check the filename and field names yourself before even trying, per Step 1.
- **Treating two independent nulls as a confirmed match.** If `paperA`'s section has no match in one pass, that's not "confirmed" anything -- it belongs in the leftover file with `reason: "no_counterpart_found"` and `diff_type: "non-alignable"`, never in the common file.
- **Dropping "no counterpart found" entries instead of putting them in the leftover file.** Every entry from both `p1-p2` and `p2-p1` must land in exactly one of the two output files -- a section with genuinely no counterpart anywhere is still a leftover entry, not something to silently omit.
- **Computing `diff_type` from `reason` (or vice versa) instead of directly checking for a null/empty section name.** They should always agree in practice, but `diff_type` is defined independently, straight from whether `paperA_section_name`/`paperB_section_name` is null or empty -- see `diff_type_of` in the script. If the two ever disagree on a real run, that's a bug to investigate, not something to paper over by deriving one from the other after the fact.
- **Using inconsistent value strings for `diff_type`** (e.g. `"non_alignable"` with an underscore, or different casing). Use exactly `"alignable"` and `"non-alignable"`, hyphenated and lowercase, matching `paper-section-alignment`'s existing vocabulary.
- **Matching only on section number and missing Abstract/References/Acknowledgments-style confirmations.** Unnumbered sections all share a `null` number, so a pure number-match would either miss every one of them or (worse) wrongly treat every unrelated pair of unnumbered sections as "matching." The script falls back to exact section name specifically for these, mirroring the upstream skill's exact-title-only exception -- don't "simplify" this to number-only matching.
- **Opening a PDF at any point.** This skill only ever reads the normalized JSON file plus each paper's own extracted file (for Step 3's paragraph-count lookup); if something looks wrong, that's a signal to check `normalize-section-mapping-both-directions`'s or `annotate-section-questions-given-paragraphs`'s output, not to go verify against the source paper.
- **Splitting leftovers into separate alignable/non-alignable files like `paper-section-alignment` does.** That's a different, older design used by a different skill -- this skill was explicitly asked to put everything into one `leftover-section-differences.json` file, distinguished by the `reason`/`diff_type` fields instead.
- **Discarding `basis_p2_p1`/`question_p2_p1` in favor of just the `p1-p2` version on the common file, or merging the two into one field.** Both are required outputs, kept separately.
- **Treating a thin or missing leftover file as proof the upstream directional-mapping pass never buries a narrow role inside a denser section.** That's a separate risk this skill has no visibility into at all -- see the "buried narrow role" awareness note above.
- **Skipping Step 3, or treating it as optional busywork.** This is the exact step whose absence let a real corpus's very first pairwise comparison ship with unfilled questions that propagated through every subsequent fold-in generation before anyone noticed. Run it every time, on the actual files Step 2 just wrote, and do not report done until it exits 0.
- **Assuming the upstream directional-mapping passes always finish their own question composition correctly, and skipping Step 3 on that assumption.** That assumption is exactly what failed in the real corpus run that motivated this gate -- verify mechanically, every time, rather than trusting it.
- **Writing a custom variant of either bundled script instead of the one shown, or "fixing" its behavior for a specific pair of papers.** Both scripts are mechanical and fixed -- if either flags something that seems wrong, that's a signal to check the underlying data, not to rewrite the check.
