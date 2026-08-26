---
name: "papernplus3-both-directions-mapping-by-paragraphs-and-questions"
description: "The papernplus3-family analog of \"papernplus2-both-directions-mapping-by-paragraphs-and-questions\". Given a four-paper \"papernplus2-pairings-with-paragraphs-and-questions\" file and the \"orchestrator-extract-sections-paragraphs-and-questions\" output for a fifth paper's PDF, runs BOTH \"directional-section-mapping-paragraphs-and-questions-papernplus3\" (paperNplus3 onto pairing) and \"pairing-to-papernplus3-mapping-by-paragraphs-and-questions\" (pairing onto paperNplus3), saving each pass as its own file plus a combined file keyed by direction. No PDF opened, no bidirectional confirmation/merge -- that's a separate downstream step. Use whenever the user wants both directions of folding a fifth paper into an existing four-paper section structure in one request, says \"map this new paper both ways\" when four papers are already merged, or wants the two independent passes ready for later comparison."
---

# PaperNplus3 Section Mapping by Paragraphs and Questions (Both Directions)

## What this is (and isn't)

This is the papernplus3-family analog of `papernplus2-both-directions-mapping-by-paragraphs-and-questions`, one generation further: a thin orchestrator that runs both papernplus3 mapping skills — `directional-section-mapping-paragraphs-and-questions-papernplus3` (paperNplus3's sections mapped onto the four-way pairing) and `pairing-to-papernplus3-mapping-by-paragraphs-and-questions` (the pairing mapped onto paperNplus3's sections) — on the same two inputs, saves each pass as its own file, and combines both into a single keyed file. No matching logic of its own, no comparison/confirmation/merging between the two passes.

**Same schema-asymmetry note as every earlier generation:** the two passes here do not share a schema. `directional-section-mapping-paragraphs-and-questions-papernplus3` outputs `paperNplus3_section_name` plus `matched_pairing_paperA_*`/`matched_pairing_paperB_*`/`matched_pairing_paperNplus1_*`/`matched_pairing_paperNplus2_*`/`matched_pairing_status`; `pairing-to-papernplus3-mapping-by-paragraphs-and-questions` outputs `pairing_paperA_*`/`pairing_paperB_*`/`pairing_paperNplus1_*`/`pairing_paperNplus2_*`/`pairing_status` plus `paperNplus3_section_name`. Don't try to force the two arrays into a shared shape when combining them.

If the user only wants one direction, point them to whichever single sub-skill matches what they asked for. Use this one when they want both passes in one request.

## Inputs

Two files, plus five literal paper-name strings — same inputs both sub-skills already require:

1. `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-sections-with-paragraphs-and-questions.json` — the output of `papernplus2-pairings-with-paragraphs-and-questions`.
2. `{paperNplus3-name}-sections-with-paragraphs-and-questions.json` — the output of `orchestrator-extract-sections-paragraphs-and-questions` on the fifth paper's PDF.

`{paperA-name}`, `{paperB-name}`, `{paperNplus1-name}`, `{paperNplus2-name}`, `{paperNplus3-name}` must be the literal PDF filenames (minus `.pdf`) already used as prefixes on the input files — character-for-character, no reformatting. If any isn't evident, ask before writing output.

No PDF is opened at any point for the matching itself.

## Workflow

### Step 1: Read both input files in full

Read every entry in both files — the pairing file's `paperA_paragraphs`/`paperB_paragraphs`/`paperNplus1_paragraphs`/`paperNplus2_paragraphs`/`question_the_sections_answer`/`pairing_status` per entry, and the paperNplus3 file's `paragraphs`/`question_this_section_answers` per section. Both passes below draw on this same fully-read content, but each applies its own matching logic fresh.

### Step 2: Run the first pass — paperNplus3 onto the pairing

Follow `directional-section-mapping-paragraphs-and-questions-papernplus3`'s full workflow. If you need its exact rules refreshed — the exact-title-only exception, the type-narrow override, the splitting rule, the null-consistency rule — consult that skill's own SKILL.md directly rather than working from memory.

Save this pass's result under its own default filename: `{paperNplus3-name}-onto-{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-section-mapping-by-paragraphs-and-questions.json`.

### Step 3: Run the second pass — the pairing onto paperNplus3

Follow `pairing-to-papernplus3-mapping-by-paragraphs-and-questions`'s full workflow, same two inputs. A fresh matching pass in the other direction, not a transformation of Step 2's output.

Save this pass's result under its own default filename: `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-onto-{paperNplus3-name}-section-mapping-by-paragraphs-and-questions.json`.

### Step 4: Combine both passes into one file

Build a single JSON object with exactly two keys — `papernplus3-to-pairing` holding Step 2's array verbatim, and `pairing-to-papernplus3` holding Step 3's array verbatim — and save it as its own third file. All three files persist.

## Output

Three files, all in the same directory as the inputs unless the user specifies otherwise:

| File | Contents |
|---|---|
| `{paperNplus3-name}-onto-{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-section-mapping-by-paragraphs-and-questions.json` | Step 2's result alone |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-onto-{paperNplus3-name}-section-mapping-by-paragraphs-and-questions.json` | Step 3's result alone |
| `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-{paperNplus3-name}-both-directions-section-mapping-by-paragraphs-and-questions.json` | Both passes combined, keyed `papernplus3-to-pairing` and `pairing-to-papernplus3` |

Briefly tell the user how many entries each pass produced and how many were matches vs. `null` in each direction, and flag anything that stands out — especially a sharp asymmetry between the two passes' null rates (expected and informative here, same as every earlier generation).

### Output schema (strict)

**The two intermediate files** are each a plain JSON array, using their producing skill's own per-entry schema exactly as documented there — no wrapping object:

```json
// {paperNplus3-name}-onto-{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-...json
[
  { "paperNplus3_section_name": "...", "paperNplus3_section_number": "...", "matched_pairing_paperA_section_name": "...", "matched_pairing_paperA_section_number": "...", "matched_pairing_paperB_section_name": "...", "matched_pairing_paperB_section_number": "...", "matched_pairing_paperNplus1_section_name": "...", "matched_pairing_paperNplus1_section_number": "...", "matched_pairing_paperNplus2_section_name": "...", "matched_pairing_paperNplus2_section_number": "...", "matched_pairing_status": "...", "basis": "...", "question_the_sections_answer": "..." }
]
```

```json
// {paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-onto-{paperNplus3-name}-...json
[
  { "pairing_paperA_section_name": "...", "pairing_paperA_section_number": "...", "pairing_paperB_section_name": "...", "pairing_paperB_section_number": "...", "pairing_paperNplus1_section_name": "...", "pairing_paperNplus1_section_number": "...", "pairing_paperNplus2_section_name": "...", "pairing_paperNplus2_section_number": "...", "pairing_status": "...", "paperNplus3_section_name": "...", "paperNplus3_section_number": "...", "basis": "...", "question_the_sections_answer": "..." }
]
```

**The combined file** is a single JSON object with exactly two top-level keys, `papernplus3-to-pairing` and `pairing-to-papernplus3`, in that order — each identical, entry-for-entry, to the corresponding intermediate file's array:

```json
{
  "papernplus3-to-pairing": [ /* identical to Step 2's intermediate file's array */ ],
  "pairing-to-papernplus3": [ /* identical to Step 3's intermediate file's array */ ]
}
```

The two arrays inside the combined file do not use the same per-entry schema as each other. Don't add extra top-level keys, and don't add extra fields inside any entry. The two arrays are fully independent — don't align entries positionally or by count.

## Common mistakes to avoid

- **Deriving the second pass's entries from the first pass instead of running the actual matching logic in `pairing-to-papernplus3-mapping-by-paragraphs-and-questions`.**
- **Forcing the two combined-file arrays into a shared per-entry schema.**
- **Opening a PDF at any point.**
- **Skipping either sub-skill's own exact-title exception, type-narrow override, splitting rule, or null-consistency rule on the assumption that "the wrapper handles that."** It doesn't — every rule in each sub-skill's own SKILL.md still applies in full.
- **Also computing which pairings/sections a fifth paper "really" belongs with, or attempting any confirmation/merge between the two passes.** Out of scope — that's `papernplus3-common-section-structure-by-paragraphs-questions`'s job.
- **Writing only the combined file and skipping the two intermediates, or vice versa.**
- **Re-deriving the combined file's two arrays instead of reusing the intermediate files' content verbatim.**
- **Altering any paper-name string when substituting it into a filename.**
- **Getting the paper-name order wrong in a filename.** `{paperNplus3-name}-onto-{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}` for Step 2's file; `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-onto-{paperNplus3-name}` for Step 3's.
- **Adding extra top-level keys to the combined file, or wrapping an intermediate file's array in an object.**

