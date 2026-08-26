---
name: "pairing-to-papernplus2-mapping-by-paragraphs-and-questions"
description: "The reverse-direction sibling of \"directional-section-mapping-paragraphs-and-questions-papernplus2\". Given the same two inputs (a three-paper \"papernplus1-pairings-with-paragraphs-and-questions\" file, and the \"orchestrator-extract-sections-paragraphs-and-questions\" output for a fourth paper's PDF), maps in the OTHER direction: for every three-way pairing entry, finds its closest section in the fourth paper using paragraphs and the question field as joint, co-equal evidence. No PDF opened. Use when the user wants to check which three-way pairings a new (fourth) paper actually covers, wants the reverse pass of the papernplus2 skill to catch forced/one-sided matches, or explicitly asks for \"the other direction\" of folding a fourth paper into an existing three-paper structure. Outputs {paperA-name}-{paperB-name}-{paperNplus1-name}-onto-{paperNplus2-name}-section-mapping-by-paragraphs-and-questions.json."
---

---
name: "pairing-to-papernplus2-mapping-by-paragraphs-and-questions"
description: "The reverse-direction sibling of \"directional-section-mapping-paragraphs-and-questions-papernplus2\". Given the same two inputs (a three-paper \"papernplus1-pairings-with-paragraphs-and-questions\" file, and the \"orchestrator-extract-sections-paragraphs-and-questions\" output for a fourth paper's PDF), maps in the OTHER direction: for every three-way pairing entry, finds its closest section in the fourth paper using paragraphs and the question field as joint, co-equal evidence. No PDF opened. Use when the user wants to check which three-way pairings a new (fourth) paper actually covers, wants the reverse pass of the papernplus2 skill to catch forced/one-sided matches, or explicitly asks for \"the other direction\" of folding a fourth paper into an existing three-paper structure. Outputs {paperA-name}-{paperB-name}-{paperNplus1-name}-onto-{paperNplus2-name}-section-mapping-by-paragraphs-and-questions.json."
---

# Pairing-to-PaperNplus2 Section Mapping (By Paragraphs and Questions)

## What this is (and isn't)

This is the reverse-direction sibling of `directional-section-mapping-paragraphs-and-questions-papernplus2`, one generation further along the same pattern as `pairing-to-papernplus1-mapping-by-paragraphs-and-questions`. That skill asks, for every section of a fourth paper (`paperNplus2`), which existing three-way pairing plays the same role. This skill asks the opposite question: for every existing three-way pairing (from `papernplus1-pairings-with-paragraphs-and-questions`), which section of `paperNplus2` plays the same role?

The two directions are separate skills, not one skill with swappable arguments, same rationale as every earlier generation of this family: a pairing entry (three-sided: paperA/paperB/paperNplus1 paragraphs, a `pairing_status`) is a structurally different object from a single paper's section entry. Running both directions and comparing them reveals where they agree.

This skill does not modify, re-judge, or re-confirm the paperA/paperB/paperNplus1 pairing structure it's given, and it does not touch `ancestor_questions` — it only decides which `paperNplus2` section (if any) each pairing corresponds to. No PDF is opened at any point.

## Inputs

Two files — the same two inputs as `directional-section-mapping-paragraphs-and-questions-papernplus2`, reasoned about in the other direction:

1. `{paperA-name}-{paperB-name}-{paperNplus1-name}-sections-with-paragraphs-and-questions.json` — the output of `papernplus1-pairings-with-paragraphs-and-questions`. A JSON array where each entry has `paperA_section_name`/`_number`/`_paragraphs`, `paperB_section_name`/`_number`/`_paragraphs`, `paperNplus1_section_name`/`_number`/`_paragraphs`, `pairing_status`, `basis_papernplus1_to_pairing`, `basis_pairing_to_papernplus1`, `ancestor_questions`, and a single `question_the_sections_answer`.
2. `{paperNplus2-name}-sections-with-paragraphs-and-questions.json` — the output of `orchestrator-extract-sections-paragraphs-and-questions` run on the fourth paper's PDF. A JSON array where each entry has `section_name`, `section_number`, `paragraphs`, and `question_this_section_answers`.

`{paperA-name}`, `{paperB-name}`, `{paperNplus1-name}`, `{paperNplus2-name}` must be the literal PDF filenames (minus `.pdf`) already used as prefixes on the input files — don't guess or reformat.

**Precondition: the question field is now guaranteed present.** The three-paper pairing file's `question_the_sections_answer` is enforced by `papernplus1-common-section-structure-by-paragraphs-questions`'s own hard Step 4 gate and carried forward by `papernplus1-pairings-with-paragraphs-and-questions`; `paperNplus2`'s own `question_this_section_answers` is enforced by `annotate-section-questions-given-paragraphs`'s hard gate. Every entry with real paragraph content on any present side is guaranteed a real, non-null question. Treat the fields as reliably present; a real counter-example is an input-integrity problem to flag, not a normal case.

## Workflow

### Step 1: Read both signals for every entry, on both sides

For each pairing entry, the signal is the union of whichever of the three sides are present: `paperA_paragraphs`, `paperB_paragraphs`, `paperNplus1_paragraphs` (whichever are non-empty), and the single `question_the_sections_answer` (non-null or not). For each `paperNplus2` section, read `question_this_section_answers` and every paragraph in `paragraphs`. Same joint-evidence standard as every skill in this family: the question and the paragraphs are read together as one body of evidence, not a hypothesis-then-confirmation pipeline.

**If a pairing entry's present side(s) are content-empty (empty paragraphs, null question on every present side), AND a candidate `paperNplus2` section is also content-empty**, fall back to exact-title matching: does `paperNplus2`'s section name exactly match `paperA_section_name`, `paperB_section_name`, and/or `paperNplus1_section_name`? A match against any present side counts. If no `paperNplus2` section title exactly matches, the honest answer is no match.

This exception applies only when every side being compared is content-empty. The moment any side has real content, match by role (Step 2).

### Step 2: Map each pairing to its closest paperNplus2 section

For each pairing entry, compare its combined signal against every `paperNplus2` section:

- **Judge role correspondence from the question field and the paragraphs together, as one joint body of evidence — never let the question pre-filter which candidates get their paragraphs read.** Read every present paragraph and the question field for every pairing/`paperNplus2` candidate pair before deciding whether it's a match.
- **Weigh the question field as reliable, primary evidence of role, not a hint the paragraphs merely confirm or overrule.** It's now guaranteed present wherever real content exists (see the Inputs section's precondition note).
- **Let the paragraphs override the question only on a genuine conflict**, not merely because it's phrased differently — same role-based test used throughout this family.
- **A null question on an entry with real paragraph content is an input-integrity problem, not a normal case.** Flag a real counter-example to the user explicitly rather than treating the question as merely optional.
- **Watch for a type-narrow question on either side.**
- **If a pairing legitimately corresponds to multiple `paperNplus2` sections**, create a **separate output entry for each**. Verify the split entries collectively cover the pairing's full combined scope.
  - **A role doesn't need its own container in `paperNplus2` to be worth matching.** If the pairing's own narrow role (e.g. one side's verbatim materials or methodology-only content) is buried inside a much broader, denser `paperNplus2` section rather than living in its own subsection there, the match should still be found at the paragraph level within that dense section — don't treat the absence of a matching heading as evidence the role doesn't appear in `paperNplus2` at all.
- **The reverse is expected and fine, not something to fix here**: multiple different pairings can validly point at the same `paperNplus2` section.
- **Many pairings will have no match at all — common and expected**, especially for `non-alignable-diff` pairings representing content specific to just one or two of paperA/paperB/paperNplus1. Output no match rather than forcing the least-bad option.
- **A pairing where only one or two of the three sides are present can still validly match a `paperNplus2` section** — judge purely on the role of whatever content that pairing actually has.

Each entry needs these fields:

| Field | Description |
|---|---|
| `pairing_paperA_section_name` | The pairing's paperA section name, or `null` |
| `pairing_paperA_section_number` | The pairing's paperA section number, or `null` |
| `pairing_paperB_section_name` | The pairing's paperB section name, or `null` |
| `pairing_paperB_section_number` | The pairing's paperB section number, or `null` |
| `pairing_paperNplus1_section_name` | The pairing's paperNplus1 section name, or `null` |
| `pairing_paperNplus1_section_number` | The pairing's paperNplus1 section number, or `null` |
| `pairing_status` | The source pairing entry's own `pairing_status`, copied verbatim |
| `paperNplus2_section_name` | The matched section's name in the fourth paper, or `null` if no match |
| `paperNplus2_section_number` | The matched section's number, or `null` |
| `basis` | Why this correspondence holds, grounded in the paragraphs on every side compared. Never empty. |
| `question_the_sections_answer` | One question all matched sections are fundamentally trying to answer. Short, no self-answering. `null` when there's no match, and also for the empty-content exact-title fallback. |

Null-consistency: each of the three `pairing_paper*_section_name`/`_number` pairs moves independently — this just reflects whatever the source pairing entry already looked like. If there's a match at all, `paperNplus2_section_name` is non-null. If there's no match, `paperNplus2_section_name` and `paperNplus2_section_number` are both `null`, and `question_the_sections_answer` is `null`.

### Output

Save as a JSON array. Default filename: `{paperA-name}-{paperB-name}-{paperNplus1-name}-onto-{paperNplus2-name}-section-mapping-by-paragraphs-and-questions.json`.

Briefly tell the user how many pairings got a match vs. none, how many entries came from a split, and flag anything that stands out. It's normal for this direction to have a substantially higher no-match rate than the `papernplus2` direction, especially for `non-alignable-diff` pairings the fourth paper legitimately has no counterpart section for — say so rather than treating a high null rate as a problem.

### Output schema (strict)

ALWAYS use this exact shape for every entry — exactly these eleven keys, no additions, no renaming, no reordering:

```json
{
  "pairing_paperA_section_name": "string or null",
  "pairing_paperA_section_number": "string or null",
  "pairing_paperB_section_name": "string or null",
  "pairing_paperB_section_number": "string or null",
  "pairing_paperNplus1_section_name": "string or null",
  "pairing_paperNplus1_section_number": "string or null",
  "pairing_status": "string",
  "paperNplus2_section_name": "string or null",
  "paperNplus2_section_number": "string or null",
  "basis": "string, explains the match or why it's null -- never null or empty itself",
  "question_the_sections_answer": "string, or null if there's no match, or if the match came from the empty-content exact-title fallback"
}
```

`basis` is always a non-empty string, including for the exact-title-fallback and no-match cases. Don't add extra fields — no `ancestor_questions` (that's the pairing entry's own field, not reproduced here; it's handled correctly downstream in `papernplus2-common-section-structure-by-paragraphs-questions`).

## Common mistakes to avoid

- **Opening a PDF, or asking for one.**
- **Reading only one or two sides of a pairing instead of the union of everything present, OR reading only the paragraphs and demoting the question field to a mere afterthought.** Both signals are co-equal, joint evidence.
- **Looking for two question fields on the pairing side.** There's only one (`question_the_sections_answer`) at this stage of the pipeline.
- **Treating a high no-match rate as something to fix.** Especially for `non-alignable-diff` appendix/sub-section pairings — this direction will often have far more nulls than the `papernplus2` direction, and that asymmetry is itself informative.
- **Assuming `question_the_sections_answer: null` always means no match.** Check `paperNplus2_section_name`.
- **Treating a null question as merely optional and quietly proceeding on paragraphs alone.** It's now a guaranteed precondition (see Inputs). A real counter-example is an input-integrity problem to flag explicitly.
- **Forcing a pairing onto the least-bad `paperNplus2` section when nothing actually plays the same role.**
- **Trusting a type-narrow question at face value**, or **matching on shared vocabulary instead of shared role.**
- **Combining a multi-role pairing correspondence into one entry instead of splitting**, or **letting a sub-role fall out of scope when splitting.**
- **Assuming a dense candidate `paperNplus2` section's most prominent role is its only role, and stopping there.** A pairing representing a narrow role can have a real, buried counterpart inside a `paperNplus2` section that also covers several other things at once — don't write `null` just because `paperNplus2` didn't carve that role into its own heading.
- **Applying the exact-title fallback when any side being compared has real paragraph content.**
- **Copying `pairing_status` incorrectly, or making it up.**
- **Writing a long, self-answering `question_the_sections_answer`.**
- **Treating this skill's output and the `papernplus2` direction's output as needing to agree entry-for-entry.** They're independent passes; disagreement between them is useful signal, not a bug.
- **Reproducing or altering `ancestor_questions` here.** Out of scope for this skill entirely.

