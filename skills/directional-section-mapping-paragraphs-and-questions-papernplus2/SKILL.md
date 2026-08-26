---
name: "directional-section-mapping-paragraphs-and-questions-papernplus2"
description: "The papernplus2-family analog of \"directional-section-mapping-paragraphs-and-questions-papernplus1\", one generation further. Given the output of \"papernplus1-pairings-with-paragraphs-and-questions\" (a three-paper file, one entry per section pairing with paperA/paperB/paperNplus1 paragraphs and a single question_the_sections_answer) and the output of \"orchestrator-extract-sections-paragraphs-and-questions\" on a fourth paper's PDF, maps every section of that fourth paper onto its closest existing three-way pairing using paragraphs and the question field as joint, co-equal evidence. No PDF opened. Use when the user wants to fold a fourth paper into an existing three-paper section comparison, \"add another paper to this comparison\" when three papers are already merged, \"map this new paper onto the three-paper pairings I already have.\" Outputs {paperNplus2-name}-onto-{paperA-name}-{paperB-name}-{paperNplus1-name}-section-mapping-by-paragraphs-and-questions.json."
---

---
name: "directional-section-mapping-paragraphs-and-questions-papernplus2"
description: "The papernplus2-family analog of \"directional-section-mapping-paragraphs-and-questions-papernplus1\", one generation further. Given the output of \"papernplus1-pairings-with-paragraphs-and-questions\" (a three-paper file, one entry per section pairing with paperA/paperB/paperNplus1 paragraphs and a single question_the_sections_answer) and the output of \"orchestrator-extract-sections-paragraphs-and-questions\" on a fourth paper's PDF, maps every section of that fourth paper onto its closest existing three-way pairing using paragraphs and the question field as joint, co-equal evidence. No PDF opened. Use when the user wants to fold a fourth paper into an existing three-paper section comparison, \"add another paper to this comparison\" when three papers are already merged, \"map this new paper onto the three-paper pairings I already have.\" Outputs {paperNplus2-name}-onto-{paperA-name}-{paperB-name}-{paperNplus1-name}-section-mapping-by-paragraphs-and-questions.json."
---

# Directional Section Mapping (By Paragraphs and Questions) — Paper N+2

## What this is (and isn't)

This is the papernplus2-family analog of `directional-section-mapping-paragraphs-and-questions-papernplus1`, one generation further along the same pattern: that skill maps a third paper's sections onto an existing **two**-sided pairing file; this skill maps a **fourth** paper's sections onto an existing **three**-sided pairing file (the output of `papernplus1-pairings-with-paragraphs-and-questions`, where each entry already carries paperA/paperB/paperNplus1 identity and paragraphs). Same role-based matching approach, extended by one more named side.

Like its predecessor, this is a **single-direction** pass: paperNplus2's sections are mapped onto the three-way pairings, not the other way around. It does not re-judge or alter the paperA/paperB/paperNplus1 correspondence it's given — that structure is fixed input. For the reverse pass, use `pairing-to-papernplus2-mapping-by-paragraphs-and-questions` instead.

**Field-name growth, deliberate.** This skill hardcodes `paperNplus2`/`matched_pairing_paperA`/`matched_pairing_paperB`/`matched_pairing_paperNplus1` rather than reusing a generic schema, per the explicit short-term design decision to accept bespoke, growing field names at each generation of this family (capped at 5 papers total) rather than the more general `sides`-array redesign considered and deferred for later. If a sixth paper is ever needed beyond the planned 5, this skill is not the template to extend blindly — see the memory note on the deferred generalized-schema option first.

No PDF is opened at any point.

## Inputs

Two files:

1. `{paperA-name}-{paperB-name}-{paperNplus1-name}-sections-with-paragraphs-and-questions.json` — the output of `papernplus1-pairings-with-paragraphs-and-questions`. A JSON array where each entry has `paperA_section_name`/`_number`/`_paragraphs`, `paperB_section_name`/`_number`/`_paragraphs`, `paperNplus1_section_name`/`_number`/`_paragraphs`, `pairing_status` (`"common-structure"`, `"alignable-diff"`, or `"non-alignable-diff"`), `basis_papernplus1_to_pairing`, `basis_pairing_to_papernplus1`, `ancestor_questions`, and a single `question_the_sections_answer`.
2. `{paperNplus2-name}-sections-with-paragraphs-and-questions.json` — the output of `orchestrator-extract-sections-paragraphs-and-questions` run on the fourth paper's PDF. A JSON array where each entry has `section_name`, `section_number`, `paragraphs`, and `question_this_section_answers`.

`{paperA-name}`, `{paperB-name}`, `{paperNplus1-name}`, `{paperNplus2-name}` must be the literal PDF filenames (minus `.pdf`) already used as prefixes on the input files — don't guess or reformat. If it's unclear which paper is being folded in versus which three-paper structure is already established, ask.

**Precondition: the question field is now guaranteed present.** `paperNplus2`'s own `question_this_section_answers` is enforced by `annotate-section-questions-given-paragraphs`'s hard gate; the three-paper pairing file's `question_the_sections_answer` is enforced by `papernplus1-common-section-structure-by-paragraphs-questions`'s own hard Step 4 gate and carried forward by `papernplus1-pairings-with-paragraphs-and-questions`. Every entry with real paragraph content on any present side is guaranteed a real, non-null question. Treat the fields as reliably present; a real counter-example is an input-integrity problem to flag, not a normal case.

## Workflow

### Step 1: Read both signals for every section, on both sides

For each `paperNplus2` entry, read `question_this_section_answers` and every paragraph in `paragraphs` — treat the question and the paragraphs as one joint body of evidence about the section's role, not a hypothesis to be confirmed by paragraphs alone.

For each pairing entry, the signal is the **union of whichever of the three sides are present**: read `paperA_paragraphs`, `paperB_paragraphs`, and `paperNplus1_paragraphs` (whichever are non-empty — a pairing can legitimately have only one or two sides populated, for an `alignable-diff`/`non-alignable-diff` entry), plus the single `question_the_sections_answer` field (unlike the papernplus1 skill, there is only ever one question field to read here, not two — the two-question collapse already happened upstream). Treat all present content together as what that pairing's role actually is.

**If a `paperNplus2` section's `paragraphs` is empty and `question_this_section_answers` is `null`, AND a pairing entry's present side(s) are similarly content-empty** (empty paragraphs on every present side, `question_the_sections_answer` null), fall back to exact section-title matching: does `paperNplus2`'s section name exactly match `paperA_section_name`, `paperB_section_name`, and/or `paperNplus1_section_name`? A match against *any one* present side is sufficient. If no title matches exactly, output no match with a basis explaining there was no content and no exact title match either — don't guess.

This exact-title exception applies only when every side actually being compared is content-empty. The moment any side has real paragraph content, match by role (Step 2) as usual.

### Step 2: Map each paperNplus2 section to its closest pairing

For each `paperNplus2` section, compare it against every pairing entry using the full signal (paragraphs from whichever of paperA/paperB/paperNplus1 are present, the one question field where non-null):

- **Judge role correspondence from the question field and the paragraphs together, as one joint body of evidence — never let the question pre-filter which candidates get their paragraphs read.** Read every present paragraph and the question field for every `paperNplus2`/pairing candidate pair before deciding whether it's a match.
- **Weigh the question field as reliable, primary evidence of role, not a hint the paragraphs merely confirm or overrule.** It's now guaranteed present wherever real content exists (see the Inputs section's precondition note) — treat it and the paragraphs as two witnesses to the same fact, not a filter-then-check pipeline.
- **Let the paragraphs override the question only on a genuine conflict**, not merely because it's phrased differently — same role-based test as the rest of this family: same job in the paper's arc from problem to contribution to evidence to reflection, not shared topic or vocabulary.
- **A null question on an entry with real paragraph content is an input-integrity problem, not a normal case.** Flag a real counter-example to the user explicitly rather than treating the question as merely optional.
- **Watch for a type-narrow question**, same pitfall as elsewhere: a pairing's own `question_the_sections_answer` can undersell content actually present in its paragraphs. Judge on the paragraphs; say so in `basis` if overriding the question's framing.
- **If a `paperNplus2` section legitimately corresponds to multiple pairings** (it covers two or more roles that were separately split at an earlier stage), create a **separate output entry for each**. Verify the split entries collectively cover the paperNplus2 section's full scope.
  - **A role doesn't need its own container to be worth splitting out.** A `paperNplus2` section can fold several distinct roles into one dense block of paragraphs even when the existing pairing structure keeps those same roles apart (e.g. a pairing that itself carries a narrow, appendix-sourced role like verbatim task/survey text or a methodology-only aside on one of its three sides). Find and split each role by its paragraph content, not by whether `paperNplus2` gave it a heading of its own — the correspondence is defined by what the paragraphs are doing, not by where they physically sit in the fourth paper.
- **If nothing among the pairings plays the same role, the honest answer is no match** (all `matched_pairing_*` fields `null`) — don't force the least-bad pairing. Expected and common, same as every earlier generation of this family.
- **A `paperNplus2` section can validly land on a pairing where only one or two of paperA/paperB/paperNplus1 are present** — that's a real correspondence, not a downgrade. Judge purely on role, using whatever content that pairing actually has.
- **The same `paperNplus2` section, or the same pairing, can appear in more than one output entry** — same expectation as every earlier generation, whenever roles split differently across papers.

Each entry needs these fields:

| Field | Description |
|---|---|
| `paperNplus2_section_name` | Section name/title from the fourth paper |
| `paperNplus2_section_number` | Section number from the fourth paper (as a string), or `null` |
| `matched_pairing_paperA_section_name` | The matched pairing's paperA section name, or `null` |
| `matched_pairing_paperA_section_number` | The matched pairing's paperA section number, or `null` |
| `matched_pairing_paperB_section_name` | The matched pairing's paperB section name, or `null` |
| `matched_pairing_paperB_section_number` | The matched pairing's paperB section number, or `null` |
| `matched_pairing_paperNplus1_section_name` | The matched pairing's paperNplus1 section name, or `null` |
| `matched_pairing_paperNplus1_section_number` | The matched pairing's paperNplus1 section number, or `null` |
| `matched_pairing_status` | The matched pairing entry's own `pairing_status`, copied verbatim, or `null` if no match |
| `basis` | Why this correspondence holds, grounded in the paragraphs actually present on every side compared. Never empty, even for a no-match or title-fallback entry. |
| `question_the_sections_answer` | One question all the matched sections are fundamentally trying to answer, framed around role. Short, genuinely open, no em-dash/parenthetical self-answering. `null` when there's no match, and also when the match came from the empty-content exact-title fallback. |

Null-consistency: the three `matched_pairing_paper*_section_name`/`_number` pairs move independently of each other — a matched pairing can have any subset of the three present, reflecting whatever the source pairing entry itself looked like. What *does* have to move together: if there's a match at all, at least one of the three sides must be non-null and `matched_pairing_status` must be non-null. If there's no match, all `matched_pairing_*` fields (all eight of them) are `null` together, and `question_the_sections_answer` is `null`. `question_the_sections_answer` being `null` does not always mean no match — see the exact-title-fallback exception.

### Output

Save as a JSON array. Default filename: `{paperNplus2-name}-onto-{paperA-name}-{paperB-name}-{paperNplus1-name}-section-mapping-by-paragraphs-and-questions.json`.

Briefly tell the user how many `paperNplus2` sections got a match vs. none, how many entries came from a split, and flag any case where a question's framing was overridden by the paragraphs.

### Output schema (strict)

ALWAYS use this exact shape for every entry — exactly these eleven keys, no additions, no renaming, no reordering:

```json
{
  "paperNplus2_section_name": "string",
  "paperNplus2_section_number": "string or null",
  "matched_pairing_paperA_section_name": "string or null",
  "matched_pairing_paperA_section_number": "string or null",
  "matched_pairing_paperB_section_name": "string or null",
  "matched_pairing_paperB_section_number": "string or null",
  "matched_pairing_paperNplus1_section_name": "string or null",
  "matched_pairing_paperNplus1_section_number": "string or null",
  "matched_pairing_status": "string or null",
  "basis": "string, explains the match or why it's null -- never null or empty itself",
  "question_the_sections_answer": "string, or null if there's no match, or if the match came from the empty-content exact-title fallback"
}
```

`basis` is always a non-empty string, including for the exact-title-fallback and no-match cases. Don't add extra fields — no `confidence`, no `paragraphs`, no `ancestor_questions` (that field belongs to the pairing entry, not this mapping pass — it gets carried forward correctly in the downstream common-structure step, not reproduced here).

## Common mistakes to avoid

- **Opening a PDF, or asking for one.** Everything needed is already in the two JSON inputs.
- **Reading only one or two sides of a pairing instead of the union of everything present, OR reading only the paragraphs and demoting the question field to a mere afterthought.** Both signals are co-equal, joint evidence.
- **Looking for two question fields on the pairing side (`question_p1_p2`/`question_p2_p1`) the way the base and papernplus1 skills have.** The three-paper pairing file already collapsed to one `question_the_sections_answer` field upstream — there's only one to read here.
- **Requiring all three `matched_pairing_paper*` groups to move together as a single null-or-not unit.** They don't — a matched pairing can have any subset of the three sides present, and that's expected, not an error.
- **Assuming `question_the_sections_answer: null` always means no match.** Check `matched_pairing_status`, not the question field — the exact-title-fallback case is a real match with a still-null question.
- **Treating a null question as merely optional and quietly proceeding on paragraphs alone.** It's now a guaranteed precondition (see Inputs). A real counter-example is an input-integrity problem to flag explicitly.
- **Forcing a match onto the least-bad pairing when nothing actually plays the same role.** `null` is the honest, common, expected answer when nothing corresponds.
- **Trusting a type-narrow question at face value**, or **matching on shared vocabulary instead of shared role.**
- **Combining a multi-role correspondence into one entry instead of splitting**, or **letting a sub-role fall out of scope when splitting.**
- **Assuming a dense `paperNplus2` section's most prominent role is its only role, and stopping there.** A section that folds several jobs into one place (say, a broad "User Study" section covering procedure, verbatim materials, and methodology all at once) can still contain a narrower stretch of paragraphs that deserves its own separate match to a pairing entry whose own side keeps that role in its own subsection or appendix — a missing heading in `paperNplus2` is not evidence the role isn't there.
- **Applying the exact-title fallback when any side being compared has real paragraph content.**
- **Copying `pairing_status`'s value into `matched_pairing_status` incorrectly, or making it up.** Must be the matched pairing entry's own value, copied verbatim.
- **Writing a long, self-answering `question_the_sections_answer`.** Same rule as every question field in this family.
- **Treating this skill as doing anything to the paperA/paperB/paperNplus1 pairing structure itself, or reproducing/altering its `ancestor_questions` field.** This skill only decides where paperNplus2's sections land relative to the existing structure — `ancestor_questions` handling happens downstream in `papernplus2-common-section-structure-by-paragraphs-questions`, not here.

