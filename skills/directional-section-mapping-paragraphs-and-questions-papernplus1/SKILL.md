---
name: "directional-section-mapping-paragraphs-and-questions-papernplus1"
description: "Given the output of \"section-pairings-with-paragraphs-and-questions\" (a two-paper file, one entry per section PAIRING with paperA_paragraphs/paperB_paragraphs and basis/question fields) and the output of \"orchestrator-extract-sections-paragraphs-and-questions\" on a third paper's PDF, maps every section of that third paper onto its closest existing pairing using paragraphs and question fields as joint, co-equal evidence -- no PDF opened. Use when the user wants to fold a third (or Nth) paper into an existing two-paper section comparison, \"add another paper to this comparison,\" \"map this new paper onto the pairings I already have,\" or is building toward a multi-paper common section structure incrementally. Outputs {paperNplus1-name}-onto-{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions.json."
---

---
name: "directional-section-mapping-paragraphs-and-questions-papernplus1"
description: "Given the output of \"section-pairings-with-paragraphs-and-questions\" (a two-paper file, one entry per section PAIRING with paperA_paragraphs/paperB_paragraphs and basis/question fields) and the output of \"orchestrator-extract-sections-paragraphs-and-questions\" on a third paper's PDF, maps every section of that third paper onto its closest existing pairing using paragraphs and question fields as joint, co-equal evidence -- no PDF opened. Use when the user wants to fold a third (or Nth) paper into an existing two-paper section comparison, \"add another paper to this comparison,\" \"map this new paper onto the pairings I already have,\" or is building toward a multi-paper common section structure incrementally. Outputs {paperNplus1-name}-onto-{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions.json."
---

# Directional Section Mapping (By Paragraphs and Questions) — Paper N+1

## What this is (and isn't)

This is the "add one more paper" analog of `directional-section-mapping-by-paragraphs-and-questions`. That skill maps every section of one paper onto its closest section in a second paper. This skill does the same kind of role-based matching, but the target side is not a single paper's section list — it's an already-produced two-paper **section-pairings** file, where each entry represents a section correspondence (or lack thereof) between paperA and paperB. For every section in a third paper (`paperNplus1`), this skill finds the pairing entry that plays the same role, so a new paper can be folded into an existing two-paper structure without re-running the two-paper comparison from scratch.

Like its sibling, this is a **single-direction** pass: paperNplus1's sections are mapped onto the pairings, not the other way around. It does not re-judge or alter anything about the paperA/paperB correspondence it's given — that structure is taken as fixed input. For the reverse pass (finding, per pairing, its closest paperNplus1 section), use `pairing-to-papernplus1-mapping-by-paragraphs-and-questions` instead — the two are separate skills because the input/output shapes aren't symmetric the way paper1/paper2 are in the base skill.

No PDF is opened at any point.

## Inputs

Two files:

1. `{paperA-name}-{paperB-name}-sections-with-paragraphs-and-questions.json` — the output of `section-pairings-with-paragraphs-and-questions`. A JSON array where each entry has `paperA_section_name`, `paperA_section_number`, `paperA_paragraphs`, `paperB_section_name`, `paperB_section_number`, `paperB_paragraphs`, `basis_p1_p2`, `question_p1_p2`, `basis_p2_p1`, `question_p2_p1`, and `pairing_status` (`"common-structure"`, `"alignable-diff"`, or `"non-alignable-diff"`).
2. `{paperNplus1-name}-sections-with-paragraphs-and-questions.json` — the output of `orchestrator-extract-sections-paragraphs-and-questions` (or `annotate-section-questions-given-paragraphs`) run on the third paper's PDF. A JSON array where each entry has `section_name`, `section_number`, `paragraphs`, and `question_this_section_answers`.

`{paperA-name}`, `{paperB-name}`, `{paperNplus1-name}` must be the literal PDF filenames (minus `.pdf`) already used as prefixes on the input files — don't guess or reformat. If it's unclear which paper is `paperNplus1` (the one being folded in) versus which pair is the existing structure, ask.

**Precondition: the question field is now guaranteed present.** `paperNplus1`'s own `question_this_section_answers` is enforced by a hard completeness gate in `annotate-section-questions-given-paragraphs`; the pairing file's `question_p1_p2`/`question_p2_p1` fields are enforced by `common-section-structure-by-paragraphs-and-questions`'s own hard gate and carried forward unchanged by `section-pairings-with-paragraphs-and-questions`. Every section/pairing with real paragraph content on any present side is guaranteed a real, non-null question; `null` is only legitimate when every present side's paragraphs are genuinely empty. Treat the fields as reliably present. A real counter-example (non-empty paragraphs, null question) is an input-integrity problem upstream — flag it to the user rather than silently treating the question as absent.

## Workflow

### Step 1: Read both signals for every section, on both sides

For each `paperNplus1` entry, read `question_this_section_answers` and every paragraph in `paragraphs`, same as the base skill — treat the question and the paragraphs as one joint body of evidence about the section's role, not a hypothesis to be confirmed by paragraphs alone.

For each pairing entry, the "signal" is the **union of whichever sides are present**: read `paperA_paragraphs` and `paperB_paragraphs` (whichever are non-empty — a pairing can legitimately have only one side populated, for a `non-alignable-diff` or `alignable-diff` entry), and both `question_p1_p2` and `question_p2_p1` (whichever are non-null). Treat all of this together as what that pairing's role actually is — not just one paper's side of it.

**If a `paperNplus1` section's `paragraphs` is empty and its `question_this_section_answers` is `null`, AND a pairing entry's present side(s) are similarly empty-of-content** (empty paragraphs on every present side, null on every present question field), there is no content to reason with on either side. In this specific case only, fall back to matching by exact section-title: does `paperNplus1`'s section name exactly match `paperA_section_name` and/or `paperB_section_name`? An exact match against *either* present side is sufficient (the pairing's own paperA/paperB identity was already confirmed or flagged elsewhere; you're only checking whether paperNplus1's empty section shares that identity). If the titles aren't identical to any present side, don't guess — output no match with a basis explaining there was no content and no exact title match either.

This exact-title exception applies only when every side actually being compared is content-empty. The moment any side has real paragraph content, match by role (Step 2) as usual.

### Step 2: Map each paperNplus1 section to its closest pairing

For each `paperNplus1` section, compare it against every pairing entry using the full signal (paragraphs from whichever paper-sides are present, both question fields where non-null) — never a bare title match when content exists:

- **Judge role correspondence from the question fields and the paragraphs together, as one joint body of evidence — never let a question pre-filter which candidates get their paragraphs read.** For every `paperNplus1`/pairing candidate pair, read every present question field and every present paragraph before deciding whether it's a match. A question worded narrowly or just differently from its counterpart can make a genuinely-corresponding pair look implausible before its paragraphs are ever read — give every candidate pairing both signals, every time.
- **Weigh the question fields as reliable, primary evidence of role, not a hint the paragraphs merely confirm or overrule.** They were composed specifically to capture each side's role, and — see the Inputs section's precondition note — are now guaranteed present wherever real content exists. Treat them and the paragraphs as witnesses to the same fact: when they agree, that's real information, not something to re-derive from paragraphs alone.
- **Let the paragraphs override a question only on a genuine conflict** — when what the paragraphs actually show doesn't match what the question claims — not merely because a question is phrased differently or uses different vocabulary. The underlying test is still: are these doing the same job in the arc from problem to contribution to evidence to reflection — not do they share topic or vocabulary.
- **A null question on an entry with real paragraph content is an input-integrity problem, not a normal case to route around.** Upstream extraction/pairing now guarantees a real question wherever real paragraph content exists (see the Inputs section's precondition note). Flag a real counter-example to the user explicitly rather than silently reasoning from paragraphs alone as if nothing were wrong.
- **Watch for a type-narrow question**, same pitfall as the base skill: a pairing's own question(s) can undersell content that's actually present in its paragraphs. Judge on the paragraphs; say so in `basis` if you override a question's framing.
- **If a `paperNplus1` section legitimately corresponds to multiple pairings** (e.g. it covers two roles that were separately split when paperA and paperB were originally compared — see the worked example below, where a single Results section splits across a pairing's Qualitative-Results and Quantitative-Results entries), create a **separate output entry for each** correspondence. When splitting, use the paragraphs to verify the split entries collectively cover the paperNplus1 section's full scope — don't let part of it silently disappear.
  - **A role doesn't need its own container to be worth splitting out.** This applies even when paperNplus1 folds several distinct roles into one dense section that paperA or paperB instead broke out into their own named subsections (e.g. a paperNplus1 "User Study" section that includes, as paragraphs, its verbatim task instructions or verbatim survey text or coding methodology alongside its design/procedure narrative — content that a pairing entry might represent as its own separate appendix subsection). The correspondence should still be found and split at the paragraph level; a role being un-sectioned in paperNplus1 is not evidence it isn't there.
- **If nothing among the pairings plays the same role**, the honest answer is no match (all `matched_pairing_*` fields `null`) — don't force the least-bad pairing. This is expected and common: many pairing entries represent content specific to just paperA or just paperB (most `non-alignable-diff` entries), and a third paper often won't have a counterpart for those either.
- **A `paperNplus1` section can validly land on a pairing where only one of paperA/paperB is present** (an `alignable-diff` or `non-alignable-diff` entry) — that's a real correspondence, not a downgrade. Judge purely on role, using whatever content that pairing actually has.
- **The same `paperNplus1` section, or the same pairing, can appear in more than one output entry.** Two different `paperNplus1` sections can both correspond to the same pairing (e.g. a design-rationale section and a separate usage-walkthrough section that were both part of one combined system-description pairing) — that's fine, output both. Likewise a paperA section can be the paperA-side of two different pairings that a paperNplus1 paper's two separate sections each match into — also fine, and worth expecting whenever paperNplus1 splits a role that paperA and paperB happened to fold together (or vice versa).

Each entry needs these fields:

| Field | Description |
|---|---|
| `paperNplus1_section_name` | Section name/title from the third paper |
| `paperNplus1_section_number` | Section number from the third paper (as a string), or `null` |
| `matched_pairing_paperA_section_name` | The matched pairing's paperA section name, or `null` if no match |
| `matched_pairing_paperA_section_number` | The matched pairing's paperA section number, or `null` |
| `matched_pairing_paperB_section_name` | The matched pairing's paperB section name, or `null` if no match |
| `matched_pairing_paperB_section_number` | The matched pairing's paperB section number, or `null` |
| `matched_pairing_status` | The matched pairing entry's own `pairing_status` value, copied verbatim (`"common-structure"`, `"alignable-diff"`, or `"non-alignable-diff"`), or `null` if no match |
| `basis` | Why this correspondence holds — grounded in what the paragraphs actually say on every side being compared, not a restatement of the question fields. Never empty, even for a no-match or title-fallback entry. |
| `question_the_sections_answer` | One question all the matched sections are fundamentally trying to answer, framed around role. Short, genuinely open, no em-dash/parenthetical self-answering. `null` when there's no match, **and also** when the match came from the empty-content exact-title fallback in Step 1 (there's no real content on any side to ground a question in, even though the title match itself counts as a match). |

Note: unlike the base skill, `matched_pairing_paperA_*` and `matched_pairing_paperB_*` are **not** required to be both-null-or-both-non-null together as a pair — a matched pairing can legitimately have one side present and the other `null` (that's just what the source pairing entry itself looked like). What *does* have to move together is: if there's a match at all, at least one of the two sides must be non-null and `matched_pairing_status` must be non-null. If there's no match, all of `matched_pairing_paperA_section_name`, `matched_pairing_paperA_section_number`, `matched_pairing_paperB_section_name`, `matched_pairing_paperB_section_number`, and `matched_pairing_status` must be `null` together, and `question_the_sections_answer` must be `null`. `question_the_sections_answer` being `null` does **not** always mean there's no match — see the exact-title-fallback exception in the field description above and the References example below, where `matched_pairing_status` is `"common-structure"` (a real match) but `question_the_sections_answer` is still `null` because there's no content to ask a question about.

### Output

Save as a JSON array of these objects. Default filename: `{paperNplus1-name}-onto-{paperA-name}-{paperB-name}-section-mapping-by-paragraphs-and-questions.json`.

Briefly tell the user how many `paperNplus1` sections got a match vs. none, how many entries came from a split, and flag any case where a question's framing was overridden by the paragraphs.

### Output schema (strict)

ALWAYS use this exact shape for every entry — exactly these nine keys, no additions, no renaming, no reordering:

```json
{
  "paperNplus1_section_name": "string",
  "paperNplus1_section_number": "string or null",
  "matched_pairing_paperA_section_name": "string or null",
  "matched_pairing_paperA_section_number": "string or null",
  "matched_pairing_paperB_section_name": "string or null",
  "matched_pairing_paperB_section_number": "string or null",
  "matched_pairing_status": "string or null",
  "basis": "string, explains the match or why it's null -- never null or empty itself",
  "question_the_sections_answer": "string, or null if there's no match, or if the match came from the empty-content exact-title fallback"
}
```

Worked example (three real HCI papers -- Examplore mapped onto an existing AbstractExplorer/CorpusStudio pairing file):

```json
[
  {
    "paperNplus1_section_name": "Results",
    "paperNplus1_section_number": null,
    "matched_pairing_paperA_section_name": "Results",
    "matched_pairing_paperA_section_number": "7",
    "matched_pairing_paperB_section_name": "Quantitative Results",
    "matched_pairing_paperB_section_number": "7",
    "matched_pairing_status": "common-structure",
    "basis": "Reports paired t-test statistics on correct-answer counts (paras 1-2) -- the same statistical-comparison role as the Results/Quantitative Results pairing. Split from the qualitative portion below since the pairing file itself splits paperA's single Results section into Qualitative and Quantitative counterparts, and this paper's Results section covers both roles.",
    "question_the_sections_answer": "What did quantitative comparison between the system and the baseline reveal?"
  },
  {
    "paperNplus1_section_name": "Results",
    "paperNplus1_section_number": null,
    "matched_pairing_paperA_section_name": "Results",
    "matched_pairing_paperA_section_number": "7",
    "matched_pairing_paperB_section_name": "Qualitative Results",
    "matched_pairing_paperB_section_number": "6",
    "matched_pairing_status": "common-structure",
    "basis": "Reports participant behavior patterns and quoted reflections (paras 0, 3-10) -- the same qualitative-experience role as the Results/Qualitative Results pairing, distinct from the quantitative-stats portion matched separately above.",
    "question_the_sections_answer": "What did participants report about their experience using the system, in their own words and observed behavior?"
  },
  {
    "paperNplus1_section_name": "System Architecture and Implementation",
    "paperNplus1_section_number": null,
    "matched_pairing_paperA_section_name": "AbstractExplorer",
    "matched_pairing_paperA_section_number": "4",
    "matched_pairing_paperB_section_name": "Data & Processing",
    "matched_pairing_paperB_section_number": "4",
    "matched_pairing_status": "alignable-diff",
    "basis": "Describes a three-phase data/processing pipeline -- the same role as this pairing, which itself links paperB's dedicated Data & Processing section to the pipeline content living inside paperA's broader system section, not to that section's UI-design content (matched separately elsewhere in this output).",
    "question_the_sections_answer": "What data was collected and how was it processed to power the system's core features?"
  },
  {
    "paperNplus1_section_name": "References",
    "paperNplus1_section_number": null,
    "matched_pairing_paperA_section_name": "References",
    "matched_pairing_paperA_section_number": null,
    "matched_pairing_paperB_section_name": "References",
    "matched_pairing_paperB_section_number": null,
    "matched_pairing_status": "common-structure",
    "basis": "This paper's own References section and the pairing's paperA/paperB sides all have empty paragraphs and a null question -- no content to reason from anywhere, so falling back to the exact-title exception: all three are literally titled 'References.'",
    "question_the_sections_answer": null
  }
]
```

`basis` is always a non-empty string, including for the exact-title-fallback and no-match cases. Don't add extra fields — no `confidence`, no `paragraphs`, nothing beyond the nine keys above.

## Common mistakes to avoid

- **Opening a PDF, or asking for one.** Same reason as the base skill: everything needed is already in the two JSON inputs.
- **Reading only one side of a pairing (just paperA, or just the question fields) instead of the union of everything present, OR reading only the paragraphs and demoting the question fields to a mere afterthought.** Both signals are co-equal, joint evidence — never let one filter or be skimmed past in favor of the other.
- **Requiring `matched_pairing_paperA_*` and `matched_pairing_paperB_*` to move together as a single null-or-not unit.** They don't — a matched pairing can have only one side present, and that's expected, not an error. What must move together is whether there's a match *at all* (see the Output section's null-consistency rule).
- **Assuming `question_the_sections_answer: null` always means no match.** It doesn't — an exact-title-fallback match on content-empty sections is a real match (`matched_pairing_status` non-null) but still gets a `null` question, since there's no content to form one from. Check `matched_pairing_status`, not the question field, to tell whether a match was found.
- **Treating a null question as merely optional and quietly proceeding on paragraphs alone.** It's now a guaranteed precondition (see Inputs). A real counter-example is an input-integrity problem to flag explicitly, not something to route around silently.
- **Forcing a match onto the least-bad pairing when nothing actually plays the same role.** Many pairing entries are paperA-only or paperB-only content that a third paper legitimately has no counterpart for — `null` is the honest, common, expected answer for those.
- **Trusting a type-narrow question at face value**, or **matching on shared vocabulary instead of shared role** — same pitfalls as the base skill, same fix: read the actual paragraphs.
- **Combining a multi-role correspondence into one entry instead of splitting**, or **letting a sub-role fall out of scope when splitting** — same splitting discipline as the base skill, verified against paragraph content, not just against a compressed question.
- **Assuming a dense paperNplus1 section's most prominent role is its only role, and stopping there.** The more distinct jobs a section's paragraphs do at once, the easier it is to write one broad `basis`/question for the section's overall shape and miss that a narrower stretch of paragraphs inside it plays a role that has its own separate correspondence to a pairing entry — especially a pairing whose own paperA/paperB side keeps that narrow role in its own subsection or appendix. The section's own boundary in paperNplus1 is not a signal about how many roles it plays.
- **Applying the exact-title fallback when any side being compared has real paragraph content.** The exception exists only for the fully-empty case, on every side being compared, not just one.
- **Copying `pairing_status`'s value into `matched_pairing_status` incorrectly, or making it up.** It must be the matched pairing entry's own `pairing_status` value, copied verbatim — never re-derived or guessed.
- **Writing a long, self-answering `question_the_sections_answer` via em-dash asides or parentheticals.** Same rule as every question field in this family — keep it short enough to ask out loud.
- **Treating this skill as doing anything to the paperA/paperB pairing structure itself.** It doesn't modify, re-judge, or re-confirm that structure — it only decides where paperNplus1's sections land relative to it.

