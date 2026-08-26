---
name: "extract-paragraphs-as-pseudo-sections"
description: "Given a row from a common-section-structure.json (any generation) OR an \"alignable\" leftover-section-differences.json row (2+ non-null paperX_section_name fields), a row index, a role-slug, and each paper's sections-with-paragraph-content(-no-appendices).json, converts that role's paragraphs into pseudo-section entries -- one per paragraph, compound-ID section_number (full paper name), freshly composed gist/question. Output filenames use a short, deterministic, unique-within-this-row paper-name abbreviation instead of the literal PDF name, to stay under OS filename-length limits at N=4/5. No PDF access. Rejects rows with fewer than 2 non-null papers. Use for paragraph-level breakdown within one matched or partially-matched section-role, or as Stage 0 of orchestrator-paragraph-structure-within-matched-section."
---

# Extract Paragraphs as Pseudo-Sections

## What this is (and isn't)

This is the bridge that lets the entire existing paragraph-and-questions section-comparison machinery (`directional-section-mapping-by-paragraphs-and-questions`, `section-mapping-by-paragraphs-and-questions-both-directions`, `normalize-section-mapping-both-directions`, `common-section-structure-by-paragraphs-and-questions`, `section-pairings-with-paragraphs-and-questions`, and the whole papernplus1/2/3 family and their orchestrators) run **one level down in granularity**, completely unmodified, by disguising paragraphs as sections.

Every one of those skills expects input shaped like `sections-with-paragraphs-and-questions.json`: an array of objects with `section_name`, `section_number`, a `paragraphs` array, and `question_this_section_answers`. This skill produces exactly that shape, except each "section" it emits is really just one paragraph, wrapped in a singleton `paragraphs` array. Nothing downstream needs to know the difference.

This skill does no cross-paper matching or comparison of its own — it only prepares one paper's paragraphs, from one already-identified section, into the pseudo-section shape. Matching happens afterward, using the existing skills, unmodified.

**This operates on exactly one row of an existing `common-section-structure.json` or `leftover-section-differences.json` file** — i.e. one section-role that's already been established to correspond across some specific set of papers, whether that correspondence is a full confirmed match or a partial (alignable) one. If no comparison has been run yet at all, run the appropriate section-level orchestrator first (`orchestrator-common-section-structure-with-differences` / `orchestrator-papernplus1/2/3-common-section-structure` / `orchestrator-five-paper-common-section-structure-from-pdfs` or its no-appendices variant).

## Leftover rows are supported for alignable entries (fixed 2026-08-16)

This skill and its caller, `orchestrator-paragraph-structure-within-matched-section`, used to blanket-forbid any row sourced from a `leftover-section-differences.json` file, reasoning that "a row in a genuine `common-section-structure.json` should never have a null side" and treating any null side as evidence of the wrong file. That blanket rule was too broad. A leftover file has two structurally different kinds of row:

- **`diff_type: "non-alignable"`** — exactly one paper has a real, non-null section; every other paper is null. There is genuinely nothing to compare here — this kind of row is correctly rejected.
- **`diff_type: "alignable"`** — two or more (but not all) papers share a real, non-null section for this role; it just wasn't bidirectionally confirmed all the way up to the full paper count. This is a real, if partial, cross-paper correspondence — mechanically no different from a `common-section-structure.json` row that happens to span fewer than the full paper count (e.g. a `papernplus1-common-section-structure.json` row spanning only paperA/paperB/paperNplus1). There is no reason this skill can't drill into it.

The underlying script already determines which papers a row spans by checking which `paperX_section_name` fields are non-null (`present_slots`), independent of which file the row came from — `leftover-section-differences.json` rows use the exact same `paperA_section_name`/`paperB_section_name`/`paperNplus1_section_name`/`paperNplus2_section_name`/`paperNplus3_section_name` field names as `common-section-structure.json` rows, just with more papers left null. So the real, precise rule is: **a row is usable if it has 2 or more non-null papers, regardless of which file it came from.** The script now enforces exactly that (see Step 1), rather than the file-based proxy rule that used to stand in for it.

## Stage 0 is strictly mechanical — never write a custom filtering variant (real incident, 2026-08-18)

The Step 1 script below states in its own docstring: "This script makes no judgment calls about paragraph content." That's not incidental — it's the contract the rest of this skill family depends on. Every role-based decision (which paragraphs correspond across papers, including "this paragraph doesn't correspond to anything in this row") belongs to the matching skills downstream, which read real paragraph text and question fields as evidence. Stage 0's only job is: look up the row's target section by name/number in each paper's own extracted file, and emit one pseudo-section entry per paragraph that section actually has. Nothing more, nothing filtered, nothing excluded.

**The incident:** during the 5-paper "SME IUI27 paper corpus" batch run (2026-08-18), the orchestrating agent, dispatching Stage 0 for a row whose mesotext side was that paper's whole "Discussion" section, wrote a custom one-off script instead of running the standard one below, adding an ad hoc filter to drop mesotext's paragraph 0 based on a guess that "it belongs to a different row." That guess was made before any matching had run, was never checked against anything, and turned out to be wrong — paragraph 0 actually corresponded to a third, different row entirely, not the one the guess named. The final output happened to still be correct (paragraph 0 genuinely doesn't belong in this row) — but only by luck. The standard, unmodified script would have included it, and the downstream matching step — which is explicitly designed to output "no match" for a paragraph that doesn't correspond to anything in a row's context (a normal, common, expected outcome throughout this family) — would have reached the identical answer honestly, from evidence, instead of from an unverified guess baked into code before any evidence was even read.

**The rule this establishes: Stage 0 always runs the standard script from Step 1 below, unmodified, for every row, every paper, every time.** If a row's papers include a paragraph that seems to overlap in subject matter with a sibling row, or seems like it "should" be excluded for some other row-specific reason:

- **Let it through, and let the downstream role-matching step decide honestly from the paragraph's actual content.** "No match" is not a failure state in this family — it's the correct, expected answer for a paragraph that doesn't belong, and it's reached with real evidence instead of a pre-emptive guess.
- **If there's a genuine structural reason a row needs different handling** (for example, a paper's row-relevant content is split across two separately-named sections that both legitimately need to feed one row — unlike excluding a single paragraph by guess, this is a real, verifiable structural fact) **stop and flag it explicitly to the user before writing any custom script**, rather than silently implementing judgment-laden logic and treating it as routine.

Never add a filter, exclusion, merge, or any other content-based judgment call into the Stage 0 script. If a custom script for a specific row seems necessary, that need itself is the signal to stop and ask — not a green light to write one.

## Why a compound ID instead of a real section number

Paragraphs don't have a section number's cross-paper positional meaning — paragraph 3 of one paper's Introduction has no inherent relationship to paragraph 3 of another's. Leaving `section_number` null for every entry would force every downstream join to fall back to matching by `section_name` alone, which is fragile here: two different paragraphs in the same paper could easily end up with similar or even identical synthetic gists.

Instead, this skill populates `section_number` with a compound, guaranteed-unique, guaranteed-deterministic ID: `"{paper-name}::{real-section-name}::{paragraph_number}"` (e.g. `"illusionofcausality::Introduction::2"`) — **using the paper's full, literal name here, never the abbreviation described below.** This lets every downstream script's existing join-key logic (`side_key`: prefer number, else exact name) work correctly with zero code changes, since it now always has a non-null, always-unique number to key on.

**This ID is opaque bookkeeping, never a signal to reason from.** It has no numeric or positional meaning across papers — nothing should ever compare two of these ID strings to each other as evidence of correspondence. Every downstream skill's job is to copy it through byte-for-byte from input to output, never to invent, reformat, reparse, or shorten it. All actual matching reasoning must come from `section_name` (the gist) and the paragraph text itself, exactly as those skills already do for any other unnumbered section.

## Why output filenames use a short paper-name abbreviation, not the literal name (added 2026-08-16)

Every downstream stage of `orchestrator-paragraph-structure-within-matched-section` names its own output files by concatenating each paper's identifier (as this skill hands it off) once per paper, joined with `-`. At N=4 or N=5 papers, with literal PDF names that can themselves run 15-25 characters plus a role-slug, the concatenated filename can exceed the operating system's ~255-character filename limit — this actually happened on a real run (a 5-paper row named `graphical-perception` produced an over-length filename and had to be rescued with an ad hoc, inconsistent abbreviation invented on the spot).

To fix this at the source rather than patching it downstream every time, this skill now computes a **short, deterministic, unique-within-this-invocation abbreviation** for each paper it's given, and uses `{abbreviation}--{role-slug}` (not `{full-paper-name}--{role-slug}`) as that paper's identifier for **filenames only** — every other use of the paper's identity (the compound `section_number` ID above, and any `paperX_name` field inside the JSON content itself) still uses the full literal name. Only filenames get shortened; no data field loses information.

**The algorithm** (deterministic — the same set of paper names always produces the same abbreviations, in this script or in any other script that implements it identically, e.g. `orchestrator-paragraph-structure-across-all-matched-sections`'s dispatch-plan builder, which must precompute the same filenames before this skill ever runs):

1. Start with a 4-character prefix of each paper's literal name (lowercased, since paper names in this family are already simple lowercase identifiers).
2. If any two papers in the current set collide at that length, grow the prefix length by 1 for the whole set and check again.
3. Repeat until every paper's abbreviation is unique within this specific set of papers. In the extremely unlikely case two distinct literal paper names are identical all the way to the longer one's full length (impossible for two different real PDFs, but guarded anyway), fall back to appending each paper's position index.

Because this only needs to be unique **within the specific set of papers a given row spans** (a subset of the corpus's full paper list), and prefix-uniqueness is preserved under taking subsets, a paper's abbreviation will be identical across every row in a corpus as long as its literal name is already prefix-unique against the corpus's full paper list — which is the common case. Still, **always print the full paper-name → abbreviation mapping in Step 1's report**, so nothing is ever ambiguous to a human reading the output filenames later, even in the rare case a row's local abbreviation happens to differ from another row's.

**Never abbreviate anything except output filenames.** The compound `section_number` ID, and any place a paper's name is stored as JSON content rather than used to build a filename, always uses the full literal name — abbreviation is purely a filesystem workaround, not a data-model change.

## Inputs

1. **A `common-section-structure.json` file (any generation) or a `leftover-section-differences.json` file (any generation).** Either way, read the row's own field names to see which generation it is — the base file has only `paperA_*`/`paperB_*` fields; each later generation adds one more `paperNplus{k}_*` pair. If sourcing from a leftover file, confirm the target row has `diff_type: "alignable"` (or, for the base 2-paper family, that it has both papers non-null) before proceeding — a `"non-alignable"` row has only one real paper and there is nothing to drill into.
2. **A 0-based row index** into that file's array, selecting one section-role with 2 or more non-null papers. If not given, ask which row before proceeding — don't guess or default to row 0.
3. **A role-slug** — a short, human-readable, filesystem-safe label for the selected role (e.g. `introduction`, `experiment-1`), supplied by whoever is invoking this skill. Used only for output filenames, alongside each paper's abbreviation. Ask for one if not supplied. If it's unusually long (over ~25 characters) and the row spans 4-5 papers, consider asking the caller for a shorter one up front — the paper-abbreviation fix below buys back most of the filename budget, but an extremely long slug can still threaten the limit at N=5.
4. **For every paper the row spans** (i.e. every `paperX_section_name` that's non-null in the target row): its literal PDF filename minus `.pdf` (the same literal-name convention used throughout this family — never guess or reformat it), and its own `{paper}-sections-with-paragraph-content.json` or `{paper}-sections-with-paragraph-content-no-appendices.json` file (from `extract-section-paragraphs` or `strip-appendices-from-extracted-sections`/the no-appendices orchestrator).

If a supplied row has a null `paperX_section_name` for some paper you were explicitly told to include as a spec, stop and flag it — that's a real mismatch between the caller's paper list and what the row actually spans (wrong row, wrong file, or a typo), not a legitimate case. This is different from a leftover row's *other* papers being null, which is expected and fine — only pass specs for the papers the row actually has a real section for (see "present_slots" in Step 1).

## Workflow

### Step 1: Write and run the skeleton-extraction script

The mechanical part — reading the target row, locating that section in each paper's own extracted file via the family's standard join key, computing each paper's filename abbreviation, and constructing the compound IDs — has no judgment calls in it and should be done by script, not freehand, to avoid paragraph-numbering slips or an inconsistent abbreviation. **This script must be run exactly as written below, unmodified, for every row — see "Stage 0 is strictly mechanical" above.**

Write this script (e.g. `extract_row_paragraphs_as_pseudo_sections.py`):

```python
#!/usr/bin/env python3
"""
Given a common-section-structure.json OR a leftover-section-differences.json file, a
0-based row index, and a role-slug, plus one or more paper specs (paper name + that
paper's own sections-with-paragraph-content(.json) file), locates the target row's
section in each paper and emits one "skeleton" pseudo-section file per paper: one entry
per paragraph, with section_number set to a compound unique ID using the paper's FULL
literal name ("{paper-name}::{real-section-name}::{paragraph_number}"), paragraphs set
to a singleton list holding that one paragraph, and section_name / question_this_section_
answers left as null placeholders for a later content-reading step to fill in. This
script makes no judgment calls about paragraph content -- every paragraph the target
section actually has is included, full stop. It must always be run as-is; do not write a
custom variant that filters, excludes, or merges paragraphs based on a guess about where
they "belong" -- see this skill's own "Stage 0 is strictly mechanical" section for a real
incident this rule exists to prevent.

Output FILENAMES use a short, deterministic, unique-within-this-invocation abbreviation
of each paper's name instead of the literal name, to avoid exceeding the OS filename-
length limit when many papers and a role-slug are concatenated (this matters at N=4/5).
The compound section_number ID inside the file content always keeps the full literal
name -- only filenames are shortened. See unique_abbreviations() below; this exact
algorithm must be replicated identically by any other script that needs to predict these
filenames before this script runs (e.g. a batch dispatcher operating on many rows).

Works on rows from either file type: a row is usable as long as it has 2 or more
non-null paperX_section_name fields. This covers full common-section-structure.json
matches (which span every paper in that generation) and "alignable" leftover-section-
differences.json rows (which span some but not all papers). A row with fewer than 2
non-null papers -- i.e. a "non-alignable" leftover entry, where only one paper has real
content -- is rejected: there is nothing to compare.

Usage:
    python3 extract_row_paragraphs_as_pseudo_sections.py <structure-or-leftover.json> <row_index> <role_slug> <paperA_name>:<paperA_paragraph_content.json> [<paperB_name>:<file> ...]

Paper specs must be given in the same paperA/paperB/paperNplus1/paperNplus2/paperNplus3
order the row itself uses, including only slots the row actually has a non-null section
for. Output: one file per paper spec, "<paper-abbreviation>--<role_slug>-sections-with-
paragraphs-and-questions.json", written to the same directory as the input file.
"""
import json
import sys
from pathlib import Path

ROLE_SLOTS = ["paperA", "paperB", "paperNplus1", "paperNplus2", "paperNplus3"]


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


def build_paragraph_lookup(sections):
    lookup = {}
    for e in sections:
        key = side_key(e.get("section_number"), e.get("section_name"))
        if key is not None:
            lookup[key] = e.get("paragraphs", [])
    return lookup


def unique_abbreviations(paper_names, min_len=4):
    """Deterministic: given a list of literal paper names, returns {paper_name:
    short_abbrev}, growing the shared prefix length only as far as needed to keep
    every abbreviation in THIS specific set unique. Same input list -> same output,
    in this script or any other script implementing this identical algorithm.
    Because uniqueness only needs to hold within the given set (a subset of the
    corpus's full paper list, in normal use), a paper's abbreviation is stable across
    every row in a corpus as long as its name is already prefix-unique against the
    corpus's full paper list -- the common case."""
    names = list(dict.fromkeys(paper_names))  # de-dup, preserve order
    length = min_len
    while True:
        abbrevs = {n: n[:length] for n in names}
        if len(set(abbrevs.values())) == len(names):
            return abbrevs
        length += 1
        if length > max(len(n) for n in names):
            # Guarded fallback -- unreachable for genuinely distinct real paper names.
            return {n: f"{n[:length]}{i}" for i, n in enumerate(names)}


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    structure_path = Path(sys.argv[1])
    row_index = int(sys.argv[2])
    role_slug = sys.argv[3]
    paper_specs = sys.argv[4:]

    with open(structure_path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    if row_index < 0 or row_index >= len(rows):
        print(f"ERROR: row_index {row_index} out of range (file has {len(rows)} rows)")
        sys.exit(1)
    row = rows[row_index]

    # Which role slots this row actually has a non-null section for. Works identically
    # whether this came from a common-section-structure.json or a leftover-section-
    # differences.json file -- both use the same paperX_section_name field names.
    present_slots = [s for s in ROLE_SLOTS if norm(row.get(f"{s}_section_name")) is not None]

    if len(present_slots) < 2:
        diff_type = row.get("diff_type")
        print(
            f"ERROR: row {row_index} has only {len(present_slots)} non-null paper(s) "
            f"({', '.join(present_slots) or 'none'})"
            + (f" -- diff_type is {diff_type!r}, i.e. a non-alignable leftover entry" if diff_type else "")
            + ". There is nothing to compare -- this skill requires at least 2 papers "
            "with a real section for this role. Pick a different row (a common-section-"
            "structure.json row, or an \"alignable\" leftover row)."
        )
        sys.exit(1)

    parsed_specs = []
    for spec in paper_specs:
        if ":" not in spec:
            print(f"ERROR: paper spec {spec!r} must be NAME:FILE")
            sys.exit(1)
        name, file_path = spec.split(":", 1)
        parsed_specs.append((name, Path(file_path)))

    if len(parsed_specs) != len(present_slots):
        print(
            f"ERROR: row {row_index} spans {len(present_slots)} papers "
            f"({', '.join(present_slots)}) but {len(parsed_specs)} paper specs were given. "
            f"Supply exactly one spec per non-null slot, in paperA/paperB/paperNplus1/"
            f"paperNplus2/paperNplus3 order."
        )
        sys.exit(1)

    abbrevs = unique_abbreviations([name for name, _ in parsed_specs])

    warnings = []
    written = []
    for slot, (paper_name, content_path) in zip(present_slots, parsed_specs):
        target_name = row.get(f"{slot}_section_name")
        target_number = row.get(f"{slot}_section_number")

        with open(content_path, "r", encoding="utf-8") as f:
            paper_sections = json.load(f)
        lookup = build_paragraph_lookup(paper_sections)

        key = side_key(target_number, target_name)
        if key is None or key not in lookup:
            warnings.append(
                f"{paper_name} ({slot}): target section {target_name!r} ({target_number!r}) "
                f"not found in {content_path} -- check the row and file match this paper."
            )
            paragraphs = []
        else:
            paragraphs = lookup[key]

        skeleton = [
            {
                "section_name": None,
                # Compound ID: FULL literal paper name, never the abbreviation.
                "section_number": f"{paper_name}::{target_name}::{p.get('paragraph_number')}",
                "paragraphs": [p],
                "question_this_section_answers": None,
            }
            for p in paragraphs
        ]

        # Output FILENAME: short abbreviation, never the full literal name.
        out_path = structure_path.parent / f"{abbrevs[paper_name]}--{role_slug}-sections-with-paragraphs-and-questions.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(skeleton, f, indent=2, ensure_ascii=False)
            f.write("\n")
        written.append((paper_name, len(skeleton), out_path))

    print(f"Row {row_index} spans: {', '.join(present_slots)}")
    print("Paper-name abbreviations used for filenames (full names preserved in section_number IDs):")
    for paper_name, abbrev in abbrevs.items():
        print(f"  {paper_name} -> {abbrev}")
    for paper_name, n, out_path in written:
        print(f"  {paper_name}: {n} paragraph(s) -> {out_path}")
    if warnings:
        print(f"\n{len(warnings)} WARNING(S):")
        for w in warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
```

Run it:

```
python3 extract_row_paragraphs_as_pseudo_sections.py <common-section-structure-or-leftover.json> <row_index> <role_slug> paperA_name:paperA_content.json paperB_name:paperB_content.json [...]
```

If the row has fewer than 2 non-null papers, the script exits with a clear error instead of producing a degenerate one-paper "comparison" — pick a different row. If it prints any WARNING lines, a target section wasn't found in that paper's own extracted file — stop and investigate (wrong file, stale extraction, mismatched paper) before continuing; don't proceed with an empty paragraph list for a paper that should have real content. **Always read the printed paper-name → abbreviation mapping** and carry it forward when reporting results to a human — filenames alone won't be self-explanatory once abbreviated.

### Step 2: Fill in the gist and the per-paragraph question

The script above leaves `section_name` and `question_this_section_answers` as `null` in every entry — this is the one part of the job that requires actually reading the paragraph. For each paper's skeleton file, and for every entry in it:

1. **Read the paragraph's full text** (the single paragraph in that entry's `paragraphs` array).
2. **Write a short gist as `section_name`** — 4 to 10 words, describing this specific paragraph's own job within the section (not the section's overall role — that's already been established one level up). E.g. "States the research gap in prior belief-bias literature," not "Introduction" and not "Motivates the paper." Keep gists genuinely distinctive from each other within the same paper; if two paragraphs in the same section are doing visibly different things, their gists should read as visibly different too — a downstream role-matching step relies on this field as a real semantic signal, the same way it relies on a real section's title.
3. **Compose `question_this_section_answers`** as a per-paragraph role question, holding to the same discipline as `annotate-section-questions-given-paragraphs`: short, genuinely open, no em-dash or parenthetical self-answering, framed around what job this paragraph does in the section's argument. Go further than section-level questions on **type**, not just topic — at paragraph grain, this distinction is often the entire point of splitting into paragraphs at all. Two adjacent paragraphs about the same topic can still be doing different jobs (e.g. one paragraph reporting what a study *found* vs. the next paragraph explaining what that finding *implies*) — the question must capture that specific job, not just repeat the topic.
4. **Never leave either field `null`.** Unlike `annotate-section-questions-given-paragraphs`, there is no legitimate empty-paragraphs case here — this skill only ever emits one entry per paragraph that genuinely exists, so every entry has real content to read and both fields must get a real answer.

Overwrite each skeleton file in place with the completed version once all its entries have both fields filled.

## Output

One file per paper the target row spans: **`{paper-abbreviation}--{role-slug}-sections-with-paragraphs-and-questions.json`**, in the same directory as the input file. The double-dash separator is deliberate — it keeps these filenames visually and mechanically distinct from the real per-paper `{paper-name}-sections-with-paragraphs-and-questions.json` files already in that directory, and from every multi-paper file the section-level pipeline produces there. See "Why output filenames use a short paper-name abbreviation" above for how `{paper-abbreviation}` is computed and why it's safe to use in place of the literal name here.

### Output schema (strict)

Each file is a JSON array, one entry per paragraph, in the section's original paragraph order:

```json
[
  {
    "section_name": "States the research gap in prior belief-bias literature",
    "section_number": "illusionofcausality::Introduction::1",
    "paragraphs": [
      {"paragraph_number": 1, "text": "Prior work on..."}
    ],
    "question_this_section_answers": "What gap in prior belief-bias research motivates this study?"
  }
]
```

Exactly these four keys, in this shape, on every entry — this is deliberately the same schema `annotate-section-questions-given-paragraphs` produces, so every downstream skill in the family accepts it without modification. No extra fields (no `paper_name` as its own key, no `real_section_name` as its own key — both are already encoded inside `section_number`, which is the whole point of the compound ID). Note that `section_number` still uses the paper's FULL literal name even though the FILE it lives in is named with the paper's abbreviation — these are deliberately two different identifiers for two different purposes.

Report to the user, per paper: how many paragraphs were converted, and confirm zero lookup warnings from Step 1 (or explain any that occurred and how they were resolved). Always include the paper-name → abbreviation mapping in this report. If the source row came from a leftover-section-differences.json file, also state that explicitly (e.g. "this row spans 2 of the corpus's 5 papers, sourced from the leftover file's alignable entries") so the user knows the downstream comparison covers a subset of papers, not the full set.

## Common mistakes to avoid

- **Writing a custom, one-off variant of the Step 1 extraction script that adds filtering, exclusion, or merging logic** (e.g. dropping a specific paragraph because it "probably belongs" to another row, or because it seems to overlap with a sibling row's content). Stage 0 is contractually judgment-free — see "Stage 0 is strictly mechanical" above, which documents a real incident caused by exactly this. Always run the standard Step 1 script verbatim; if a row genuinely seems to need different handling, stop and ask rather than encode a guess in code.
- **Leaving `section_number` null instead of the compound ID.** That would force downstream joins onto the fragile synthetic-gist fallback this design specifically avoids — always populate it with `"{paper}::{real-section-name}::{paragraph_number}"`, using the FULL literal paper name.
- **Abbreviating the paper name inside `section_number`, or anywhere in JSON content.** Abbreviation is a filename-only workaround for the OS length limit — the compound ID, and any paper-name field inside the data itself, always use the full literal name. Only output filenames use `{paper-abbreviation}`.
- **Treating the compound ID as a signal to compare or reason from.** It's opaque bookkeeping for the join scripts only. All actual role-matching must come from `section_name` (the gist) and the paragraph text, exactly as with any other unnumbered real section elsewhere in this family.
- **Regenerating or reformatting the compound ID anywhere downstream.** Every skill that touches these files must copy `section_number` through byte-for-byte. If a later step's schema requires the ID to move to a different field name (e.g. `matched_pairing_paperA_section_number`), copy the string verbatim into the new field — never re-derive it.
- **Inventing an ad hoc abbreviation on the spot instead of running `unique_abbreviations()`.** A hand-picked abbreviation (e.g. shortening "graphical-perception" to "gp" because a filename got too long) breaks the guarantee that any other script predicting this skill's output filenames (like a batch dispatcher) will compute the same name. Always run the documented algorithm, never improvise, even under a length-limit error.
- **Recomputing paper abbreviations per downstream stage instead of once at Stage 0 and reusing them.** Every stage after Stage 0 must treat `{paper-abbreviation}--{role-slug}` as an opaque, already-decided identifier — copied through, never recomputed.
- **Writing a gist that describes the section's overall role instead of this specific paragraph's job.** The section-level role question already exists one level up (in the `common-section-structure.json` or leftover row) — this skill's whole value is capturing something narrower.
- **Writing near-identical gists for genuinely different paragraphs**, or vice versa splitting one paragraph's content across a compound gist. One entry is exactly one paragraph; the gist should read as specific to it.
- **Guessing a paragraph's content instead of reading its full text before writing the gist/question.** Same discipline as every content-reading skill in this family.
- **Leaving `section_name` or `question_this_section_answers` as `null` in the final output.** Unlike the section-level skill, there's no legitimate empty-content case here — fill both for every entry.
- **Blanket-refusing every row from a `leftover-section-differences.json` file.** This used to be the rule and was wrong — only a row with fewer than 2 non-null papers (a `"non-alignable"` entry) has nothing to compare. An `"alignable"` leftover row is a legitimate, if partial, cross-paper correspondence and this skill now handles it the same way it handles any `common-section-structure.json` row (see "Leftover rows are supported for alignable entries" above).
- **Running this on a row with fewer than 2 non-null papers.** The script now rejects this explicitly — don't work around the rejection by manually padding in a paper spec for a null slot, or by picking one paper's row and inventing a comparison against nothing.
- **Opening a PDF.** Everything needed is already in each paper's own extracted paragraph-content file.
- **Using a single-dash separator in output filenames**, colliding with the family's existing per-paper or multi-paper file naming. Always use the double-dash `{paper-abbreviation}--{role-slug}` form.
