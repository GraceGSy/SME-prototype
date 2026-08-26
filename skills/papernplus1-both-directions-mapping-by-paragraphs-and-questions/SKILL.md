---
name: "papernplus1-both-directions-mapping-by-paragraphs-and-questions"
description: "The papernplus1-family analog of \"section-mapping-by-paragraphs-and-questions-both-directions\". Given a two-paper \"section-pairings-with-paragraphs-and-questions\" file and the \"orchestrator-extract-sections-paragraphs-and-questions\" output for a third paper's PDF, runs BOTH \"directional-section-mapping-paragraphs-and-questions-papernplus1\" (paperNplus1 onto pairing) and \"pairing-to-papernplus1-mapping-by-paragraphs-and-questions\" (pairing onto paperNplus1), saving each pass as its own file plus a combined file keyed by direction. No PDF opened, no bidirectional confirmation/merge -- that's a separate downstream step. Use whenever the user wants both directions of folding a third paper into an existing two-paper section structure in one request, says \"map this new paper both ways,\" \"run both papernplus1 directions,\" or wants the two independent passes ready for later comparison."
---

# PaperNplus1 Section Mapping by Paragraphs and Questions (Both Directions)

## What this is (and isn't)

This is the papernplus1-family analog of `section-mapping-by-paragraphs-and-questions-both-directions`: a thin orchestrator that runs both of the papernplus1 mapping skills — `directional-section-mapping-paragraphs-and-questions-papernplus1` (paperNplus1's sections mapped onto the pairing) and `pairing-to-papernplus1-mapping-by-paragraphs-and-questions` (the pairing mapped onto paperNplus1's sections) — on the same two inputs, saves each pass as its own file, and combines both into a single keyed file. It performs no matching logic of its own and does no comparison, confirmation, or merging between the two passes; that's a separate step (`papernplus1-common-section-structure-by-paragraphs-questions`).

**Important difference from the base `...-both-directions` skill this is modeled on:** in the base skill, both directional passes share one identical schema (`paper1_*`/`paper2_*`), because paper1 and paper2 are the same kind of object. Here, the two passes do **not** share a schema — `directional-section-mapping-paragraphs-and-questions-papernplus1` outputs `paperNplus1_section_name` plus `matched_pairing_paperA_*`/`matched_pairing_paperB_*`/`matched_pairing_status`, while `pairing-to-papernplus1-mapping-by-paragraphs-and-questions` outputs `pairing_paperA_*`/`pairing_paperB_*`/`pairing_status` plus `paperNplus1_section_name`. That's expected — see each sub-skill's own SKILL.md for why they're separate skills with separate schemas, not one skill run twice. Don't try to force the two arrays into a shared shape when combining them.

If the user only wants one direction, they don't need this skill — point them to whichever single sub-skill matches what they asked for. Use this one specifically when they want both passes in one request.

## Inputs

Two files, plus three literal paper-name strings — same inputs both sub-skills already require:

1. `{paperA-name}-{paperB-name}-sections-with-paragraphs-and-questions.json` — the output of `section-pairings-with-paragraphs-and-questions`.
2. `{paperNplus1-name}-sections-with-paragraphs-and-questions.json` — the output of `orchestrator-extract-sections-paragraphs-and-questions` on the third paper's PDF.

`{paperA-name}`, `{paperB-name}`, `{paperNplus1-name}` must be the literal PDF filenames (minus `.pdf`) already used as prefixes on the input files — character-for-character, no reformatting, no lowercasing, no shortening. If any isn't evident, ask before writing output — don't guess or derive one from a section/publication title.

No PDF is opened at any point for the matching itself.

## Workflow

### Step 1: Read both input files in full

Read every entry in both files — the pairing file's `paperA_paragraphs`/`paperB_paragraphs`/both question fields/`pairing_status` per entry, and the paperNplus1 file's `paragraphs`/`question_this_section_answers` per section. Both passes below draw on this same fully-read content, but each pass applies its own matching logic fresh — the two directions are genuinely different questions ("for each paperNplus1 section, what pairing plays the same role?" is not the mirror of "for each pairing, what paperNplus1 section plays the same role?"), so don't derive one pass from the other.

**Future consideration — context isolation between passes:** both passes here are done by the same reasoning process, one after the other, in the same session. A real test run against three actual papers (AbstractExplorer, CorpusStudio, Examplore) found the two directions agreeing perfectly on every single match — zero one-directional disagreements at all. That's plausible on its own merits (Examplore has a conventional, unambiguous section structure, and the pairing side of the comparison carries richer combined signal than a lone paper would), but it's also the kind of result that could partly reflect the second pass being unconsciously anchored by the first, since both were reasoned about by the same process back to back rather than genuinely independently. A stronger form of isolation — running each pass in a separate context (e.g. a separate subagent with no visibility into the other pass's output or reasoning) — hasn't been tried yet. Worth testing on a messier or more idiosyncratically structured third paper, where some one-directional disagreement would plausibly be expected, to see whether isolation changes the result.

### Step 2: Run the first pass — paperNplus1 onto the pairing

Follow `directional-section-mapping-paragraphs-and-questions-papernplus1`'s full workflow. If you need its exact rules refreshed — the exact-title-only exception, the type-narrow override, the splitting rule, the null-consistency rule for `matched_pairing_status`/`question_the_sections_answer` — consult that skill's own SKILL.md directly rather than working from memory.

Save this pass's result under its own default filename: `{paperNplus1-name}-onto-{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions.json`.

### Step 3: Run the second pass — the pairing onto paperNplus1

Follow `pairing-to-papernplus1-mapping-by-paragraphs-and-questions`'s full workflow, same two inputs. This is a fresh matching pass in the other direction, not a transformation of Step 2's output.

Save this pass's result under its own default filename: `{paperA-name}-{paperB-name}-onto-{paperNplus1-name}-section-mapping-by-paragraphs-and-questions.json`.

### Step 4: Combine both passes into one file

Build a single JSON object with exactly two keys — `papernplus1-to-pairing` holding Step 2's array verbatim, and `pairing-to-papernplus1` holding Step 3's array verbatim (not re-derived) — and save it as its own third file (see Output). All three files persist; the combined file doesn't replace the two intermediates.

## Output

Three files, all in the same directory as the inputs unless the user specifies otherwise:

| File | Contents |
|---|---|
| `{paperNplus1-name}-onto-{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions.json` | Step 2's result alone: a plain JSON array, `directional-section-mapping-paragraphs-and-questions-papernplus1`'s own schema |
| `{paperA-name}-{paperB-name}-onto-{paperNplus1-name}-section-mapping-by-paragraphs-and-questions.json` | Step 3's result alone: a plain JSON array, `pairing-to-papernplus1-mapping-by-paragraphs-and-questions`'s own schema |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-both-directions-section-mapping-by-paragraphs-and-questions.json` | Both passes combined into one object, keyed `papernplus1-to-pairing` and `pairing-to-papernplus1` |

For example, with the pairing file prefixed `abstractexplorer-corpusstudio` and the third paper `examplore_chi18`, the three files are `examplore_chi18-onto-abstractexplorer-corpusstudio-section-mapping-by-paragraphs-and-questions.json`, `abstractexplorer-corpusstudio-onto-examplore_chi18-section-mapping-by-paragraphs-and-questions.json`, and `abstractexplorer-corpusstudio-examplore_chi18-both-directions-section-mapping-by-paragraphs-and-questions.json`.

Briefly tell the user how many entries each pass produced and how many were matches vs. `null` in each direction, and flag anything that stands out — especially a sharp asymmetry between the two passes' null rates (expected and informative here, unlike in the base skill, since the two directions aren't matching the same *kind* of thing on both sides — see "What this is" above).

### Output schema (strict)

**The two intermediate files** are each a plain JSON array, using their producing skill's own per-entry schema exactly as documented there — no wrapping object, no combined-file key:

```json
// {paperNplus1-name}-onto-{paperA-name}-{paperB-name}-...json
[
  { "paperNplus1_section_name": "...", "paperNplus1_section_number": "...", "matched_pairing_paperA_section_name": "...", "matched_pairing_paperA_section_number": "...", "matched_pairing_paperB_section_name": "...", "matched_pairing_paperB_section_number": "...", "matched_pairing_status": "...", "basis": "...", "question_the_sections_answer": "..." }
]
```

```json
// {paperA-name}-{paperB-name}-onto-{paperNplus1-name}-...json
[
  { "pairing_paperA_section_name": "...", "pairing_paperA_section_number": "...", "pairing_paperB_section_name": "...", "pairing_paperB_section_number": "...", "pairing_status": "...", "paperNplus1_section_name": "...", "paperNplus1_section_number": "...", "basis": "...", "question_the_sections_answer": "..." }
]
```

**The combined file** is a single JSON object with exactly two top-level keys, `papernplus1-to-pairing` and `pairing-to-papernplus1`, no others, in that order — each key's value identical, entry-for-entry, to the corresponding intermediate file's array:

```json
{
  "papernplus1-to-pairing": [ /* identical to Step 2's intermediate file's array */ ],
  "pairing-to-papernplus1": [ /* identical to Step 3's intermediate file's array */ ]
}
```

Unlike the base `...-both-directions` skill, the two arrays inside the combined file do **not** use the same per-entry schema as each other — each retains its own producing skill's schema. Don't add extra top-level keys (no `metadata`, no `paper_names`), and don't add extra fields inside any entry. The two arrays are fully independent — don't try to align entries positionally or by count between them.

## Common mistakes to avoid

- **Deriving the second pass's entries from the first pass instead of running the actual matching logic in `pairing-to-papernplus1-mapping-by-paragraphs-and-questions`.** The two directions are separate questions with structurally different output shapes, not a mechanical flip of one another — see Step 3.
- **Forcing the two combined-file arrays into a shared per-entry schema.** They're legitimately different (see "What this is and isn't" above) — resist the urge to "normalize" them here; that's out of scope for this orchestrator.
- **Opening a PDF at any point.** Neither pass needs one; the PDF filename strings are used only as literal text for output filenames.
- **Skipping either sub-skill's own exact-title exception, type-narrow override, splitting rule, or null-consistency rule on the assumption that "the wrapper handles that."** This skill doesn't reimplement either sub-skill's logic — it just runs each one's real workflow once. Every rule documented in each sub-skill's own SKILL.md still applies in full.
- **Also computing which pairings/sections a third paper "really" belongs with, or attempting any confirmation/merge between the two passes.** Out of scope on purpose, same as the base skill — that's `papernplus1-common-section-structure-by-paragraphs-questions`'s job. Don't drift into doing it here.
- **Writing only the combined file and skipping the two intermediates, or vice versa.** All three files are required outputs — the intermediates exist for standalone inspection, the combined file for downstream consumption.
- **Re-deriving the combined file's two arrays instead of reusing the intermediate files' content verbatim.** Must match exactly, entry-for-entry — not a fresh third pass.
- **Altering any paper-name string when substituting it into a filename.** No capitalizing, lowercasing, trimming, or "cleaning up" — must be byte-for-byte the PDF filename minus `.pdf`, consistent across all three output filenames.
- **Getting the paper-name order wrong in a filename.** `{paperNplus1-name}-onto-{paperA-name}-{paperB-name}` for Step 2's file, `{paperA-name}-{paperB-name}-onto-{paperNplus1-name}` for Step 3's — the direction word ("onto") always points from whichever side is being enumerated toward whichever side is being matched against, same order as each sub-skill's own default filename.
- **Adding extra top-level keys to the combined file, or wrapping an intermediate file's array in an object.**

