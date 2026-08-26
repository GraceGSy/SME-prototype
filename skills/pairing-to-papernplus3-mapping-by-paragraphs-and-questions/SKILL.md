---
name: "pairing-to-papernplus3-mapping-by-paragraphs-and-questions"
description: "The reverse-direction sibling of \"directional-section-mapping-paragraphs-and-questions-papernplus3\". Given the same two inputs (a four-paper \"papernplus2-pairings-with-paragraphs-and-questions\" file, and the \"orchestrator-extract-sections-paragraphs-and-questions\" output for a fifth paper's PDF), maps in the OTHER direction: for every four-way pairing entry, finds its closest section in the fifth paper using paragraphs and the question field as joint, co-equal evidence. No PDF opened. Use when the user wants to check which four-way pairings a new (fifth) paper actually covers, wants the reverse pass of the papernplus3 skill to catch forced/one-sided matches, or explicitly asks for \"the other direction\" of folding a fifth paper into an existing four-paper structure. Outputs {paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-onto-{paperNplus3-name}-section-mapping-by-paragraphs-and-questions.json."
---

---
name: "pairing-to-papernplus3-mapping-by-paragraphs-and-questions"
description: "The reverse-direction sibling of \"directional-section-mapping-paragraphs-and-questions-papernplus3\". Given the same two inputs (a four-paper \"papernplus2-pairings-with-paragraphs-and-questions\" file, and the \"orchestrator-extract-sections-paragraphs-and-questions\" output for a fifth paper's PDF), maps in the OTHER direction: for every four-way pairing entry, finds its closest section in the fifth paper using paragraphs and the question field as joint, co-equal evidence. No PDF opened. Use when the user wants to check which four-way pairings a new (fifth) paper actually covers, wants the reverse pass of the papernplus3 skill to catch forced/one-sided matches, or explicitly asks for \"the other direction\" of folding a fifth paper into an existing four-paper structure. Outputs {paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-onto-{paperNplus3-name}-section-mapping-by-paragraphs-and-questions.json."
---

# Pairing-to-PaperNplus3 Section Mapping (By Paragraphs and Questions)

## What this is (and isn't)

This is the reverse-direction sibling of `directional-section-mapping-paragraphs-and-questions-papernplus3`, one generation further along the same pattern as `pairing-to-papernplus2-mapping-by-paragraphs-and-questions`. That skill asks, for every section of a fifth paper (`paperNplus3`), which existing four-way pairing plays the same role. This skill asks the opposite question: for every existing four-way pairing (from `papernplus2-pairings-with-paragraphs-and-questions`), which section of `paperNplus3` plays the same role?

The two directions are separate skills, not one skill with swappable arguments, same rationale as every earlier generation of this family: a pairing entry (four-sided: paperA/paperB/paperNplus1/paperNplus2 paragraphs, a `pairing_status`) is a structurally different object from a single paper's section entry. Running both directions and comparing them reveals where they agree.

This skill does not modify, re-judge, or re-confirm the paperA/paperB/paperNplus1/paperNplus2 pairing structure it's given, and it does not touch `ancestor_questions` — it only decides which `paperNplus3` section (if any) each pairing corresponds to. No PDF is opened at any point.

## Inputs

Two files — the same two inputs as `directional-section-mapping-paragraphs-and-questions-papernplus3`, reasoned about in the other direction:

1. `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-sections-with-paragraphs-and-questions.json` — the output of `papernplus2-pairings-with-paragraphs-and-questions`. A JSON array where each entry has `paperA_section_name`/`_number`/`_paragraphs`, `paperB_section_name`/`_number`/`_paragraphs`, `paperNplus1_section_name`/`_number`/`_paragraphs`, `paperNplus2_section_name`/`_number`/`_paragraphs`, `pairing_status`, `basis_papernplus2_to_pairing`, `basis_pairing_to_papernplus2`, `ancestor_questions`, and a single `question_the_sections_answer`.
2. `{paperNplus3-name}-sections-with-paragraphs-and-questions.json` — the output of `orchestrator-extract-sections-paragraphs-and-questions` run on the fifth paper's PDF. A JSON array where each entry has `section_name`, `section_number`, `paragraphs`, and `question_this_section_answers`.

`{paperA-name}`, `{paperB-name}`, `{paperNplus1-name}`, `{paperNplus2-name}`, `{paperNplus3-name}` must be the literal PDF filenames (minus `.pdf`) already used as prefixes on the input files — don't guess or reformat.

**Precondition: the question field is now guaranteed present.** The four-paper pairing file's `question_the_sections_answer` is enforced by `papernplus2-common-section-structure-by-paragraphs-questions`'s own hard Step 4 gate and carried forward by `papernplus2-pairings-with-paragraphs-and-questions`; `paperNplus3`'s own `question_this_section_answers` is enforced by `annotate-section-questions-given-paragraphs`'s hard gate. Every entry with real paragraph content on any present side is guaranteed a real, non-null question. Treat the fields as reliably present; a real counter-example is an input-integrity problem to flag, not a normal case.

## Workflow

### Step 1: Read both signals for every entry, on both sides

For each pairing entry, the signal is the union of whichever of the four sides are present: `paperA_paragraphs`, `paperB_paragraphs`, `paperNplus1_paragraphs`, `paperNplus2_paragraphs` (whichever are non-empty), and the single `question_the_sections_answer` (non-null or not). For each `paperNplus3` section, read `question_this_section_answers` and every paragraph in `paragraphs`. Same joint-evidence standard as every skill in this family: the question and the paragraphs are read together as one body of evidence, not a hypothesis-then-confirmation pipeline.

**If a pairing entry's present side(s) are content-empty (empty paragraphs, null question on every present side), AND a candidate `paperNplus3` section is also content-empty**, fall back to exact-title matching: does `paperNplus3`'s section name exactly match `paperA_section_name`, `paperB_section_name`, `paperNplus1_section_name`, and/or `paperNplus2_section_name`? A match against any present side counts. If no `paperNplus3` section title exactly matches, the honest answer is no match.

This exception applies only when every side being compared is content-empty. The moment any side has real content, match by role (Step 2).

### Step 2: Map each pairing to its closest paperNplus3 section

For each pairing entry, compare its combined signal against every `paperNplus3` section:

- **Judge role correspondence from the question field and the paragraphs together, as one joint body of evidence — never let the question pre-filter which candidates get their paragraphs read.** Read every present paragraph and the question field for every pairing/`paperNplus3` candidate pair before deciding whether it's a match.
- **Weigh the question field as reliable, primary evidence of role, not a hint the paragraphs merely confirm or overrule.** It's now guaranteed present wherever real content exists (see the Inputs section's precondition note).
- **Let the paragraphs override the question only on a genuine conflict**, not merely because it's phrased differently — same role-based test used throughout this family.
- **A null question on an entry with real paragraph content is an input-integrity problem, not a normal case.** Flag a real counter-example to the user explicitly rather than treating the question as merely optional.
- **Watch for a type-narrow question on either side.**
- **If a pairing legitimately corresponds to multiple `paperNplus3` sections**, create a **separate output entry for each**. Verify the split entries collectively cover the pairing's full combined scope.
  - **A role doesn't need its own container in `paperNplus3` to be worth matching.** If the pairing's own narrow role (e.g. one side's verbatim materials or methodology-only content) is buried inside a much broader, denser `paperNplus3` section rather than living in its own subsection there, the match should still be found at the paragraph level within that dense section — don't treat the absence of a matching heading as evidence the role doesn't appear in `paperNplus3` at all. **This is not hypothetical**: in the real end-to-end test that first exercised this skill (folding mesotext.pdf in as paper 5 against the AbstractExplorer/CorpusStudio/Examplore/ParaLib structure), three AbstractExplorer-only pairings — a qualitative-coding methodology, verbatim task prompts, and verbatim survey questions, each with its own subsection on AbstractExplorer's side — matched correctly to paragraphs found inside mesotext's Appendix C, even though mesotext filed all three under one appendix rather than three separate headings.
- **The reverse is expected and fine, not something to fix here**: multiple different pairings can validly point at the same `paperNplus3` section.
- **Many pairings will have no match at all — common and expected**, especially for `non-alignable-diff` pairings representing content specific to just one, two, or three of paperA/paperB/paperNplus1/paperNplus2. Output no match rather than forcing the least-bad option.
- **A pairing where only some of the four sides are present can still validly match a `paperNplus3` section** — judge purely on the role of whatever content that pairing actually has.

Each entry needs these fields:

| Field | Description |
|---|---|
| `pairing_paperA_section_name` | The pairing's paperA section name, or `null` |
| `pairing_paperA_section_number` | The pairing's paperA section number, or `null` |
| `pairing_paperB_section_name` | The pairing's paperB section name, or `null` |
| `pairing_paperB_section_number` | The pairing's paperB section number, or `null` |
| `pairing_paperNplus1_section_name` | The pairing's paperNplus1 section name, or `null` |
| `pairing_paperNplus1_section_number` | The pairing's paperNplus1 section number, or `null` |
| `pairing_paperNplus2_section_name` | The pairing's paperNplus2 section name, or `null` |
| `pairing_paperNplus2_section_number` | The pairing's paperNplus2 section number, or `null` |
| `pairing_status` | The source pairing entry's own `pairing_status`, copied verbatim |
| `paperNplus3_section_name` | The matched section's name in the fifth paper, or `null` if no match |
| `paperNplus3_section_number` | The matched section's number, or `null` |
| `basis` | Why this correspondence holds, grounded in the paragraphs on every side compared. Never empty. |
| `question_the_sections_answer` | One question all matched sections are fundamentally trying to answer. Short, no self-answering. `null` when there's no match, and also for the empty-content exact-title fallback. |

Null-consistency: each of the four `pairing_paper*_section_name`/`_number` pairs moves independently — this just reflects whatever the source pairing entry already looked like. If there's a match at all, `paperNplus3_section_name` is non-null. If there's no match, `paperNplus3_section_name` and `paperNplus3_section_number` are both `null`, and `question_the_sections_answer` is `null`.

### Output

Save as a JSON array. Default filename: `{paperA-name}-{paperB-name}-{paperNplus1-name}-{paperNplus2-name}-onto-{paperNplus3-name}-section-mapping-by-paragraphs-and-questions.json`.

Briefly tell the user how many pairings got a match vs. none, how many entries came from a split, and flag anything that stands out. It's normal for this direction to have a substantially higher no-match rate than the `papernplus3` direction, especially for `non-alignable-diff` pairings the fifth paper legitimately has no counterpart section for — say so rather than treating a high null rate as a problem.

### Output schema (strict)

ALWAYS use this exact shape for every entry — exactly these thirteen keys, no additions, no renaming, no reordering:

```json
{
  "pairing_paperA_section_name": "string or null",
  "pairing_paperA_section_number": "string or null",
  "pairing_paperB_section_name": "string or null",
  "pairing_paperB_section_number": "string or null",
  "pairing_paperNplus1_section_name": "string or null",
  "pairing_paperNplus1_section_number": "string or null",
  "pairing_paperNplus2_section_name": "string or null",
  "pairing_paperNplus2_section_number": "string or null",
  "pairing_status": "string",
  "paperNplus3_section_name": "string or null",
  "paperNplus3_section_number": "string or null",
  "basis": "string, explains the match or why it's null -- never null or empty itself",
  "question_the_sections_answer": "string, or null if there's no match, or if the match came from the empty-content exact-title fallback"
}
```

`basis` is always a non-empty string, including for the exact-title-fallback and no-match cases. Don't add extra fields — no `ancestor_questions` (that's the pairing entry's own field, not reproduced here; it's handled correctly downstream in `papernplus3-common-section-structure-by-paragraphs-questions`).

## Common mistakes to avoid

- **Opening a PDF, or asking for one.**
- **Reading only some sides of a pairing instead of the union of everything present, OR reading only the paragraphs and demoting the question field to a mere afterthought.** Both signals are co-equal, joint evidence.
- **Looking for two question fields on the pairing side.** There's only one (`question_the_sections_answer`) at this stage of the pipeline.
- **Treating a high no-match rate as something to fix.** Especially for `non-alignable-diff` appendix/sub-section pairings — this direction will often have far more nulls than the `papernplus3` direction, and that asymmetry is itself informative.
- **Assuming `question_the_sections_answer: null` always means no match.** Check `paperNplus3_section_name`.
- **Treating a null question as merely optional and quietly proceeding on paragraphs alone.** It's now a guaranteed precondition (see Inputs). A real counter-example is an input-integrity problem to flag explicitly.
- **Forcing a pairing onto the least-bad `paperNplus3` section when nothing actually plays the same role.**
- **Trusting a type-narrow question at face value**, or **matching on shared vocabulary instead of shared role.**
- **Combining a multi-role pairing correspondence into one entry instead of splitting**, or **letting a sub-role fall out of scope when splitting.**
- **Assuming a dense candidate `paperNplus3` section's most prominent role is its only role, and stopping there.** A pairing representing a narrow role can have a real, buried counterpart inside a `paperNplus3` section that also covers several other things at once — don't write `null` just because `paperNplus3` didn't carve that role into its own heading. See the mesotext Appendix C example above: the correct match existed only as paragraphs inside a denser appendix, with no heading of its own on that side.
- **Applying the exact-title fallback when any side being compared has real paragraph content.**
- **Copying `pairing_status` incorrectly, or making it up.**
- **Writing a long, self-answering `question_the_sections_answer`.**
- **Treating this skill's output and the `papernplus3` direction's output as needing to agree entry-for-entry.** They're independent passes; disagreement between them is useful signal, not a bug.
- **Reproducing or altering `ancestor_questions` here.** Out of scope for this skill entirely.

