---
name: "pairing-to-papernplus1-mapping-by-paragraphs-and-questions"
description: "The reverse-direction sibling of \"directional-section-mapping-paragraphs-and-questions-papernplus1\". Given the same two inputs (a two-paper \"section-pairings-with-paragraphs-and-questions\" file, and the \"orchestrator-extract-sections-paragraphs-and-questions\" output for a third paper's PDF), maps in the OTHER direction: for every pairing entry, finds its closest section in the third paper using paragraphs and question fields as joint, co-equal evidence. No PDF opened. Use when the user wants to check which pairings a new paper actually covers, wants the reverse pass of the papernplus1 skill to catch forced/one-sided matches, or explicitly asks for \"the other direction\" of folding a third paper into an existing two-paper structure. Outputs {paperA-name}-{paperB-name}-onto-{paperNplus1-name}-section-mapping-by-paragraphs-and-questions.json."
---

---
name: "pairing-to-papernplus1-mapping-by-paragraphs-and-questions"
description: "The reverse-direction sibling of \"directional-section-mapping-paragraphs-and-questions-papernplus1\". Given the same two inputs (a two-paper \"section-pairings-with-paragraphs-and-questions\" file, and the \"orchestrator-extract-sections-paragraphs-and-questions\" output for a third paper's PDF), maps in the OTHER direction: for every pairing entry, finds its closest section in the third paper using paragraphs and question fields as joint, co-equal evidence. No PDF opened. Use when the user wants to check which pairings a new paper actually covers, wants the reverse pass of the papernplus1 skill to catch forced/one-sided matches, or explicitly asks for \"the other direction\" of folding a third paper into an existing two-paper structure. Outputs {paperA-name}-{paperB-name}-onto-{paperNplus1-name}-section-mapping-by-paragraphs-and-questions.json."
---

# Pairing-to-PaperNplus1 Section Mapping (By Paragraphs and Questions)

## What this is (and isn't)

This is the reverse-direction sibling of `directional-section-mapping-paragraphs-and-questions-papernplus1`. That skill asks, for every section of a third paper (`paperNplus1`), which existing paperA/paperB pairing plays the same role. This skill asks the opposite question: for every existing pairing (from `section-pairings-with-paragraphs-and-questions`), which section of `paperNplus1` plays the same role?

The two directions are separate skills, not one skill with swappable arguments, because the input shapes on each side are not symmetric — a pairing entry (dual-sided: paperA and paperB paragraphs/questions, a `pairing_status`) is a structurally different object from a single paper's section entry (paragraphs, one question). Running both directions and comparing them is the same rationale as running the base two-paper skill in both directions: a directional pass can be forced into the closest available option even when nothing genuinely corresponds, and only checking both directions independently reveals where they agree.

This skill does not modify, re-judge, or re-confirm the paperA/paperB pairing structure it's given — it only decides which `paperNplus1` section (if any) each pairing corresponds to. No PDF is opened at any point.

## Inputs

Two files — the same two inputs as `directional-section-mapping-paragraphs-and-questions-papernplus1`, just being reasoned about in the other direction:

1. `{paperA-name}-{paperB-name}-sections-with-paragraphs-and-questions.json` — the output of `section-pairings-with-paragraphs-and-questions`. A JSON array where each entry has `paperA_section_name`, `paperA_section_number`, `paperA_paragraphs`, `paperB_section_name`, `paperB_section_number`, `paperB_paragraphs`, `basis_p1_p2`, `question_p1_p2`, `basis_p2_p1`, `question_p2_p1`, and `pairing_status` (`"common-structure"`, `"alignable-diff"`, or `"non-alignable-diff"`).
2. `{paperNplus1-name}-sections-with-paragraphs-and-questions.json` — the output of `orchestrator-extract-sections-paragraphs-and-questions` (or `annotate-section-questions-given-paragraphs`) run on the third paper's PDF. A JSON array where each entry has `section_name`, `section_number`, `paragraphs`, and `question_this_section_answers`.

`{paperA-name}`, `{paperB-name}`, `{paperNplus1-name}` must be the literal PDF filenames (minus `.pdf`) already used as prefixes on the input files — don't guess or reformat.

**Precondition: the question field is now guaranteed present.** The pairing file's `question_p1_p2`/`question_p2_p1` fields are enforced by `common-section-structure-by-paragraphs-and-questions`'s own hard gate and carried forward unchanged by `section-pairings-with-paragraphs-and-questions`; `paperNplus1`'s own `question_this_section_answers` is enforced by `annotate-section-questions-given-paragraphs`'s hard gate. Every entry with real paragraph content on any present side is guaranteed a real, non-null question. Treat the fields as reliably present; a real counter-example is an input-integrity problem to flag, not a normal case.

## Workflow

### Step 1: Read both signals for every entry, on both sides

For each pairing entry, the signal is the union of whichever sides are present: `paperA_paragraphs` and `paperB_paragraphs` (whichever are non-empty), and both `question_p1_p2`/`question_p2_p1` (whichever are non-null). For each `paperNplus1` section, read `question_this_section_answers` and every paragraph in `paragraphs`. Same joint-evidence standard as every skill in this family: the question fields and the paragraphs are read together as one body of evidence, not a hypothesis-then-confirmation pipeline.

**If a pairing entry's present side(s) are content-empty (empty paragraphs, null question fields on every present side), AND a candidate `paperNplus1` section is also content-empty (empty `paragraphs`, null `question_this_section_answers`)**, fall back to exact-title matching: does `paperNplus1`'s section name exactly match `paperA_section_name` and/or `paperB_section_name`? A match against either present side counts. If no `paperNplus1` section title exactly matches, the honest answer is no match — don't guess.

This exception applies only when every side being compared is content-empty. The moment any side has real content, match by role (Step 2).

### Step 2: Map each pairing to its closest paperNplus1 section

For each pairing entry, compare its combined signal against every `paperNplus1` section:

- **Judge role correspondence from the question fields and the paragraphs together, as one joint body of evidence — never let a question pre-filter which candidates get their paragraphs read.** Read every present paragraph and every present question field for every pairing/`paperNplus1` candidate pair before deciding whether it's a match.
- **Weigh the question fields as reliable, primary evidence of role, not a hint the paragraphs merely confirm or overrule.** They're now guaranteed present wherever real content exists (see the Inputs section's precondition note) — treat them and the paragraphs as witnesses to the same fact.
- **Let the paragraphs override a question only on a genuine conflict**, not merely because it's phrased differently — same role-based test used throughout this family: same job in the paper's arc from problem to contribution to evidence to reflection, not shared topic or vocabulary.
- **A null question on an entry with real paragraph content is an input-integrity problem, not a normal case.** Flag a real counter-example to the user explicitly rather than treating the question as merely optional.
- **Watch for a type-narrow question on either side** — a pairing's own question(s), or a `paperNplus1` section's question, can undersell content actually present in the paragraphs. Judge on paragraphs; say so in `basis` if overriding a question's framing.
- **If a pairing legitimately corresponds to multiple `paperNplus1` sections** (e.g. a system-description pairing that itself spans both design rationale and a usage walkthrough — see the worked example below, where one pairing splits across a third paper's design section and its separate scenario/walkthrough section), create a **separate output entry for each**. Verify the split entries collectively cover the pairing's full combined scope.
  - **A role doesn't need its own container to be worth splitting out on the paperNplus1 side either.** If `paperNplus1` folds several roles a pairing distinguishes into one dense section (e.g. its own single "User Study" section covers what the pairing itself represents as separate design/procedure and verbatim-materials/methodology roles), match each role's paragraph range to its own pairing rather than treating the whole dense section as one target. The lack of a matching subsection boundary in `paperNplus1` is not evidence the narrower role isn't present there.
- **The reverse is expected and fine, not something to fix here**: multiple different pairings can validly point at the *same* `paperNplus1` section (e.g. a paper that doesn't split Results into qualitative/quantitative the way paperA and paperB did — its one Results section can legitimately be the target of two separate pairing entries). That's not a split on this skill's side; each pairing simply gets its own best independent match.
- **Many pairings will have no match at all — this is common and expected**, especially for `non-alignable-diff` pairings representing content specific to just paperA or just paperB (appendix subsections, a formative study, an ablation study). A third paper often has no counterpart section for those. Output no match (all `paperNplus1_*` fields `null`) rather than forcing the least-bad option.
- **A pairing where only paperA or only paperB is present** (`alignable-diff`/`non-alignable-diff`) can still validly match a `paperNplus1` section — judge purely on the role of whatever content that pairing actually has.

Each entry needs these fields:

| Field | Description |
|---|---|
| `pairing_paperA_section_name` | The pairing's paperA section name, or `null` |
| `pairing_paperA_section_number` | The pairing's paperA section number, or `null` |
| `pairing_paperB_section_name` | The pairing's paperB section name, or `null` |
| `pairing_paperB_section_number` | The pairing's paperB section number, or `null` |
| `pairing_status` | The source pairing entry's own `pairing_status`, copied verbatim |
| `paperNplus1_section_name` | The matched section's name in the third paper, or `null` if no match |
| `paperNplus1_section_number` | The matched section's number, or `null` |
| `basis` | Why this correspondence holds, grounded in the paragraphs on every side compared. Never empty, even for a no-match or title-fallback entry. |
| `question_the_sections_answer` | One question all matched sections are fundamentally trying to answer, framed around role. Short, no em-dash/parenthetical self-answering. `null` when there's no match, **and also** when the match came from the empty-content exact-title fallback (no content to ground a question in). |

Null-consistency: `pairing_paperA_section_name`/`pairing_paperA_section_number` always move together (both null or both non-null), independently of `pairing_paperB_section_name`/`pairing_paperB_section_number` doing the same — this just reflects whatever the source pairing entry already looked like, not a judgment call this skill makes. `paperNplus1_section_name` and `paperNplus1_section_number` are only required to move together to the extent the input paperNplus1 file itself provides them (a paper with no numbered headings can have a matched, non-null name alongside a `null` number — that's a property of the source data, not an error). If there's a match at all, `paperNplus1_section_name` is non-null. If there's no match, `paperNplus1_section_name` and `paperNplus1_section_number` are both `null`, and `question_the_sections_answer` is `null`.

### Output

Save as a JSON array of these objects. Default filename: `{paperA-name}-{paperB-name}-onto-{paperNplus1-name}-section-mapping-by-paragraphs-and-questions.json`.

Briefly tell the user how many pairings got a match vs. none, how many entries came from a split, and flag any case where a question's framing was overridden by the paragraphs. It's normal and expected for this direction to have a substantially higher no-match rate than the `papernplus1` direction, especially when paperA/paperB have appendix-heavy content the third paper doesn't — say so rather than treating a high null rate as a problem.

### Output schema (strict)

ALWAYS use this exact shape for every entry — exactly these nine keys, no additions, no renaming, no reordering:

```json
{
  "pairing_paperA_section_name": "string or null",
  "pairing_paperA_section_number": "string or null",
  "pairing_paperB_section_name": "string or null",
  "pairing_paperB_section_number": "string or null",
  "pairing_status": "string",
  "paperNplus1_section_name": "string or null",
  "paperNplus1_section_number": "string or null",
  "basis": "string, explains the match or why it's null -- never null or empty itself",
  "question_the_sections_answer": "string, or null if there's no match, or if the match came from the empty-content exact-title fallback"
}
```

Worked example (three real HCI papers -- the AbstractExplorer/CorpusStudio pairing file mapped onto Examplore):

```json
[
  {
    "pairing_paperA_section_name": "AbstractExplorer",
    "pairing_paperA_section_number": "4",
    "pairing_paperB_section_name": "CorpusStudio",
    "pairing_paperB_section_number": "3",
    "pairing_status": "common-structure",
    "paperNplus1_section_name": "Synthetic Code Skeleton",
    "paperNplus1_section_number": null,
    "basis": "Defines the third paper's core representational device and its design rationale -- matches the design-rationale portion of this pairing's combined role. Split from the scenario-walkthrough match below, since the pairing's own scope spans both design and a worked usage example, and the third paper splits those two roles into separate sections where paperA and paperB each keep them in one.",
    "question_the_sections_answer": "What is the system's core representational device, and what design rationale grounds it?"
  },
  {
    "pairing_paperA_section_name": "AbstractExplorer",
    "pairing_paperA_section_number": "4",
    "pairing_paperB_section_name": "CorpusStudio",
    "pairing_paperB_section_number": "3",
    "pairing_status": "common-structure",
    "paperNplus1_section_name": "Scenario: Interacting with Code Distributions",
    "paperNplus1_section_number": null,
    "basis": "A named-user walkthrough of using the interface -- matches the worked-example portion of this pairing's role, distinct from the design-rationale portion matched above.",
    "question_the_sections_answer": "How does a walkthrough of a specific user demonstrate the system's interaction model?"
  },
  {
    "pairing_paperA_section_name": "Summative User Study Surveys",
    "pairing_paperA_section_number": "J",
    "pairing_paperB_section_name": "Surveys",
    "pairing_paperB_section_number": "A",
    "pairing_status": "common-structure",
    "paperNplus1_section_name": null,
    "paperNplus1_section_number": null,
    "basis": "This pairing represents a dedicated appendix section itemizing survey question wording/results in both paperA and paperB. The third paper's extracted section list has no comparable standalone appendix section.",
    "question_the_sections_answer": null
  },
  {
    "pairing_paperA_section_name": "References",
    "pairing_paperA_section_number": null,
    "pairing_paperB_section_name": "References",
    "pairing_paperB_section_number": null,
    "pairing_status": "common-structure",
    "paperNplus1_section_name": "References",
    "paperNplus1_section_number": null,
    "basis": "Every side being compared -- this pairing's paperA and paperB sides, and the third paper's own References section -- has empty paragraphs and a null question. Falling back to the exact-title exception: all three are literally titled 'References.'",
    "question_the_sections_answer": null
  }
]
```

`basis` is always a non-empty string, including for the exact-title-fallback and no-match cases. Don't add extra fields.

## Common mistakes to avoid

- **Opening a PDF, or asking for one.** Everything needed is already in the two JSON inputs.
- **Reading only one side of a pairing instead of the union of everything present, OR reading only the paragraphs and demoting the question fields to a mere afterthought.** Both signals are co-equal, joint evidence — same discipline as the `papernplus1` direction.
- **Treating a high no-match rate as something to fix.** Many pairings — especially `non-alignable-diff` appendix/sub-section entries — legitimately have no counterpart in a third paper. This direction will often have far more nulls than the `papernplus1` direction, and that asymmetry is itself informative, not an error to paper over.
- **Assuming `question_the_sections_answer: null` always means no match.** Check `paperNplus1_section_name` (or the pairing's own non-null identity plus a non-null matched name), not the question field, to tell whether a match was found — the exact-title fallback on content-empty sections is a real match with a still-null question.
- **Treating a null question as merely optional and quietly proceeding on paragraphs alone.** It's now a guaranteed precondition (see Inputs). A real counter-example is an input-integrity problem to flag explicitly.
- **Forcing a pairing onto the least-bad `paperNplus1` section when nothing actually plays the same role.**
- **Trusting a type-narrow question at face value**, or **matching on shared vocabulary instead of shared role.**
- **Combining a multi-role pairing correspondence into one entry instead of splitting**, or **letting a sub-role fall out of scope when splitting.**
- **Assuming a dense `paperNplus1` candidate section's most prominent role is its only role, and stopping there.** A pairing representing a narrow role (verbatim materials, a methodology-only aside, an exact-instrument appendix) can still have a real counterpart buried inside a `paperNplus1` section that also covers several other roles at once — don't dismiss the match just because `paperNplus1` didn't give that narrow role its own heading. Read the full paragraph range for what it's actually doing before writing `null`.
- **Applying the exact-title fallback when any side being compared has real paragraph content.**
- **Copying `pairing_status` incorrectly, or making it up.** It must be the source pairing entry's own value, copied verbatim.
- **Writing a long, self-answering `question_the_sections_answer` via em-dash asides or parentheticals.**
- **Treating this skill as doing anything to the paperA/paperB pairing structure itself**, or **treating this skill's output and the `papernplus1` direction's output as needing to agree entry-for-entry.** They're independent passes; running both and comparing is exactly the point — disagreement between them is useful signal, not a bug in either skill.

