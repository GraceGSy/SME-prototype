---
name: "section-mapping-by-paragraphs-and-questions-both-directions"
description: "Given two sections-with-paragraphs-and-questions.json files (from \"annotate-section-questions-given-paragraphs\"), runs the directional-section-mapping-by-paragraphs-and-questions workflow twice — once with each paper as paper1 — saving each pass as its own intermediate file plus a combined JSON file (keyed \"p1-p2\" and \"p2-p1\"), all named using both papers' source PDF filenames, so everything is ready as input for downstream skills or later inspection. No PDF is opened for the matching itself. Use whenever the user wants both-direction section mapping between two papers without manually running the mapping skill twice, or explicitly says \"map both directions,\" \"run it both ways,\" \"give me both p1-p2 and p2-p1,\" using paragraphs and questions only. Does NOT do the bidirectional confirmation/common-structure comparison that \"paper-section-alignment\" does — it just produces the two raw directional passes (individually and combined) for something else to compare later."
---

# Section Mapping by Paragraphs and Questions (Both Directions)

## What this is (and isn't)

This is a thin orchestrator around `directional-section-mapping-by-paragraphs-and-questions`: it runs that skill's exact workflow **twice** — once with each input paper acting as `paper1` — saves each pass as its own intermediate file, and then combines both into a single JSON file with one key per direction. It does not do any comparison, confirmation, or "which matches hold up in both directions" analysis between the two passes; that's a separate downstream job (the kind of thing `paper-section-alignment` does for the PDF-based mapping skill, though no equivalent exists yet for this JSON-based one). This skill's entire job is producing both raw directional passes — saved individually for inspection, and combined for downstream use — clearly and consistently named.

If the user only wants one direction, they don't need this skill — point them to `directional-section-mapping-by-paragraphs-and-questions` directly. Use this one specifically when they want both passes in one request.

## Inputs

Two files, each a `sections-with-paragraphs-and-questions.json` (or equivalent — any file with `section_name`, `section_number`, `paragraphs`, and `question_this_section_answers` per section, per the sub-skill's own Inputs section). Call them `fileA` and `fileB` in the order the user gives them — `fileA` becomes `paper1` in the first pass (the `p1-p2` entry), `fileB` becomes `paper1` in the second (the `p2-p1` entry).

**You also need each paper's source PDF filename, with the `.pdf` extension removed — this is required, not optional.** This exact string is what gets used, verbatim, wherever this SKILL.md writes `{paperA-name}` or `{paperB-name}` below (see Output): character-for-character identical to the PDF's filename minus `.pdf`, with no reformatting, no lowercasing, no punctuation cleanup, no shortening, and no paraphrasing. `abstractexplorer.pdf` means the literal string used is `abstractexplorer` — not "AbstractExplorer," not "Abstract Explorer," not a section title, not the paper's publication title, not a placeholder like `paper1`/`paper2`. If the user hasn't stated a paper's PDF filename and it isn't otherwise evident (e.g. from earlier conversation context, or a filename embedded in the input JSON's path), ask for it before writing any output file — don't invent or infer a name from the paper's content.

No PDF is opened at any point for the actual matching work — the PDF filename is used purely as a literal string for output filenames, not as a file to read.

## Workflow

### Step 1: Read both input files in full

Read every entry in both `fileA` and `fileB`, including every paragraph and the precomputed question for each section. Both passes below draw on this same fully-read content — don't re-read from scratch between passes, but do re-apply the matching logic fresh each time rather than assuming the first pass's judgments automatically transfer to the second (the reverse direction is a genuinely separate matching problem, not just a mechanical flip of the first pass's entries).

**Future consideration — context isolation between passes:** an earlier internal test compared re-reading the input files from scratch before the second pass against not re-reading, and found no measurable difference (kept the "don't re-read, but reason fresh" wording above as a result). That test only isolated the *file-reading* step, though — it didn't isolate the *reasoning* itself. Both passes here are still done by the same reasoning process in the same session, one after the other, which carries some risk of the second pass being unconsciously anchored by the first even when explicitly instructed to judge it fresh. A stronger form of isolation — running each directional pass in a genuinely separate context (e.g. a separate subagent with no visibility into the other pass's output) — hasn't been tried yet and could be worth testing if a future run's two passes agree suspiciously perfectly (or disagree in a way that looks like anchoring rather than genuine independent judgment) on a paper pair where more disagreement would be expected.

### Step 2: Run the first pass — `fileA` as paper1

Follow `directional-section-mapping-by-paragraphs-and-questions`'s full workflow (Steps 1-2 of that skill: read both signals, watch for type-narrow questions, apply the exact-title-only exception for empty sections, split multi-section correspondences, use `null` only when genuinely nothing matches) with `fileA` as `paper1` and `fileB` as `paper2`. If you need the exact rules refreshed, consult that skill's SKILL.md directly rather than working from a vague memory of it — the exact-title exception and type-narrow override are easy to get subtly wrong from recall alone.

Save this pass's result as its own intermediate file (a plain JSON array, per that skill's schema — see "Output schema (strict)" below): `{paperA-name}-{paperB-name}-p1-p2-section-mapping-by-paragraphs-and-questions.json`.

### Step 3: Run the second pass — `fileB` as paper1

Run the same workflow again, this time with `fileB` as `paper1` and `fileA` as `paper2`. This is a fresh matching pass, not a transformation of Step 2's output — a section that got a strong match in one direction can legitimately get a weaker match, a split, or a `null` in the other direction, since the two directions are independent questions ("for each of fileB's sections, what in fileA plays the same role?" is not the same task as its mirror).

Save this pass's result as its own intermediate file: `{paperA-name}-{paperB-name}-p2-p1-section-mapping-by-paragraphs-and-questions.json`.

### Step 4: Combine both passes into one file

Build a single JSON object with exactly two keys — `p1-p2` holding Step 2's array and `p2-p1` holding Step 3's array (the same content just written to the two intermediate files, not re-derived) — and save it as its own file (see Output). All three files persist; the combined file is not a replacement for the two intermediate ones.

## Output

Three files, all in the same directory as the inputs unless the user specifies otherwise, all sharing the same `{paperA-name}-{paperB-name}` prefix (the exact, unaltered PDF-filename strings from Inputs, `fileA`'s first, `fileB`'s second, joined with a single hyphen):

| File | Contents |
|---|---|
| `{paperA-name}-{paperB-name}-p1-p2-section-mapping-by-paragraphs-and-questions.json` | Step 2's result alone: a plain JSON array, `fileA` as paper1 |
| `{paperA-name}-{paperB-name}-p2-p1-section-mapping-by-paragraphs-and-questions.json` | Step 3's result alone: a plain JSON array, `fileB` as paper1 |
| `{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions.json` | Both passes combined into one object, keyed `p1-p2` and `p2-p1` |

For example, if `fileA` came from `abstractexplorer.pdf` and `fileB` from `corpusstudio.pdf`, the three files are `abstractexplorer-corpusstudio-p1-p2-section-mapping-by-paragraphs-and-questions.json`, `abstractexplorer-corpusstudio-p2-p1-section-mapping-by-paragraphs-and-questions.json`, and `abstractexplorer-corpusstudio-section-mapping-by-paragraphs-and-questions.json`. Nothing about either paper's filename string is altered in any of the three — not case, not spacing, not punctuation.

Briefly tell the user how many sections got matched vs. `null` in each direction, and flag anything that stands out — especially any section whose match status differs meaningfully between the two passes (e.g. a strong match one way but `null` the other), since that's exactly the kind of signal a future confirmation step would want surfaced.

### Output schema (strict)

**The two intermediate files** are each a plain JSON array — no wrapping object, no `p1-p2`/`p2-p1` key, just the array itself:

```json
[
  { "paper1_section_name": "...", "paper1_section_number": "...", "paper2_section_name": "...", "paper2_section_number": "...", "basis": "...", "question_the_sections_both_answer": "..." }
]
```

**The combined file** is a single JSON object with exactly two top-level keys, `p1-p2` and `p2-p1`, no others, in that order — and each key's value is identical, entry-for-entry, to the corresponding intermediate file's array:

```json
{
  "p1-p2": [ /* identical to the p1-p2 intermediate file's array */ ],
  "p2-p1": [ /* identical to the p2-p1 intermediate file's array */ ]
}
```

Each entry in every array (intermediate or combined) uses the identical per-entry schema as `directional-section-mapping-by-paragraphs-and-questions` — exactly these six keys, no additions, no renaming, no reordering:

```json
{
  "paper1_section_name": "string",
  "paper1_section_number": "string or null",
  "paper2_section_name": "string, or null if no match",
  "paper2_section_number": "string or null, matches paper2_section_name's null-ness",
  "basis": "string, explains the match or why it's null — never null or empty itself",
  "question_the_sections_both_answer": "string, or null if paper2_section_name is null, or if the match came from the empty-content exact-title fallback"
}
```

Within `p1-p2` (both the intermediate file and the combined file's `p1-p2` key), `paper1_*` fields describe `fileA` and `paper2_*` fields describe `fileB`. Within `p2-p1`, it's reversed. Don't add extra top-level keys to the combined file beyond `p1-p2` and `p2-p1` (no `metadata`, no `paper_names`, nothing else), and don't add extra fields inside any entry object. The two arrays are independent of each other — don't try to align entries positionally between `p1-p2` and `p2-p1` (they can have different lengths, different orders, and different `null` patterns, since each is its own independent matching pass).

## Common mistakes to avoid

- **Deriving the second pass's entries by flipping or relabeling the first pass's entries instead of re-running the matching logic.** The two directions are separate questions with potentially different answers (splits, nulls, and match strength can all differ) — see Step 3.
- **Opening a PDF at any point.** Neither pass needs one; if a section's paragraphs or question are missing, that's an extraction gap to flag, not a reason to go find the source PDF. (The PDF *filename string* is still required, per Inputs — just not the file itself.)
- **Skipping the exact-title-only exception, the type-narrow override check, or the splitting rule on the assumption that "the wrapper handles that."** This skill doesn't reimplement those rules — it just runs the real skill's workflow twice. Every rule in `directional-section-mapping-by-paragraphs-and-questions` still applies fully to each pass.
- **Also computing which matches "hold up" in both directions, or producing a common/alignable/non-alignable structure.** That's out of scope for this skill on purpose — it only produces the two raw passes (individually and combined). Don't drift into doing `paper-section-alignment`-style confirmation work unless the user explicitly asks for that (in which case, do it as a visibly separate step, or point them to `paper-section-alignment` if they'd rather work from PDFs directly).
- **Writing only the combined file and skipping the two intermediate files, or vice versa.** All three files are required outputs now — the intermediates exist so each pass can be inspected on its own, the combined file exists for downstream consumption. Don't treat either as optional or as a replacement for the other.
- **Re-deriving the combined file's `p1-p2`/`p2-p1` arrays instead of reusing the intermediate files' content verbatim.** The combined file must match the two intermediate files exactly, entry-for-entry — not a fresh third pass, not a summarized or edited version.
- **Altering the PDF filename string in any way when substituting it into `{paperA-name}`/`{paperB-name}`.** No capitalizing, no lowercasing, no inserting spaces, no trimming, no "cleaning up" — the substituted string must be byte-for-byte the PDF filename with only `.pdf` removed, and it must be the same across all three output filenames. If you don't actually know a paper's PDF filename, ask — don't guess, paraphrase, or substitute a section/publication title instead.
- **Putting the paper names in the wrong order in any of the three filenames.** It's always `fileA`'s PDF name first, then `fileB`'s, in every filename — the same order as the `p1-p2` key, not alphabetical or any other ordering.
- **Adding extra top-level keys or metadata to the combined file, or wrapping an intermediate file's array in an object.** Intermediates are plain arrays; only the combined file is an object with `p1-p2`/`p2-p1` keys — see "Output schema (strict)" above.

