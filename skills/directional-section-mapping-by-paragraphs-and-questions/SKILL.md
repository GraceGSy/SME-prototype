---
name: "directional-section-mapping-by-paragraphs-and-questions"
description: "Given two academic or narrative section JSON files with paragraphs and precomputed questions, maps every section in document1 to its closest role counterpart in document2 using both signals together. Multiple legitimate correspondences and null matches remain valid outputs."
---

# Directional Section Mapping (By Paragraphs and Questions)

## What this is (and isn't)

This is the middle ground between `directional-section-mapping` (reads PDFs) and `directional-section-mapping-by-questions-only` (reads only the compressed `question_this_section_answers` field): for every section in `paper1`, find its closest corresponding section in `paper2`, reasoning from each section's full `paragraphs` array *and* its precomputed question together — never by opening a PDF.

The point of using both fields, rather than just the question, is that a section's question is a compressed hypothesis about its role, and compression can lose things — a question can be narrower than the paragraphs it was written from (see the type-narrow pitfall in Step 2). Having the paragraphs on hand lets you catch and correct for that, the way `directional-section-mapping` can by reading the PDF, but without the cost of reopening it.

Like both siblings, this is a **single-direction** pass and does not check whether paper2's side of a pairing agrees when reasoned about independently. Run it twice (swapping which paper is `paper1`), using distinct output filenames, if both directions are wanted — or point the user to `paper-section-alignment` for the bidirectional-confirmation version (note that skill currently reasons from PDFs, not from these JSON files).

## No-match entries now pull paper1's own question forward instead of going null (fixed 2026-08-16)

This skill used to set `question_the_sections_both_answer` to `null` for every entry where `paper2_section_name` was `null` (no counterpart found in paper2) — reasoning that there was no "shared" question to compose since there was nothing on the paper2 side to share it with. That was a real mistake, caught downstream: a leftover-section-differences.json entry for a genuinely singleton section (only one paper has this content) ended up with a null question field, even though paper1's own section already had a perfectly good, previously-computed question sitting right there in the input file (`question_this_section_answers`) — there was never any need to leave the field empty or invent something new.

The corrected rule: **when there's no match, don't compose anything and don't leave it null — copy paper1's own `question_this_section_answers` value for that section into `question_the_sections_both_answer`, verbatim, unmodified.** The field's name still says "both," but for a no-match entry there's only one real section left in the picture, and the question it already answers on its own is exactly the right thing to carry forward — recomposing it would be wasted, duplicate reasoning, and leaving it null would silently discard information that already exists. This applies identically whether the underlying "sections" are real paper sections or paragraph-level pseudo-sections (from `extract-paragraphs-as-pseudo-sections`) — the same rule holds at both granularities, since this skill has no awareness of which one it's being run on.

This also changes what a `null` in this field means going forward: it's no longer a reliable signal of "no match" on its own (a no-match entry is normally non-null now, carrying paper1's own question). A genuine `null` now means one of exactly two things: paper1's own `question_this_section_answers` was itself `null` to begin with (unusual, given the input contract — see Inputs below), or the match came from Step 1's empty-content exact-title fallback, where both sides are empty and there's nothing on either side to pull forward. See the updated "Output schema (strict)" and "Common mistakes" sections below for the full, corrected rules.

## Inputs

Two files, each a JSON array of section objects, in the order sections appear in that paper. Every entry needs at least: `section_name`, `section_number`, `paragraphs` (an array of `{paragraph_number, text}`), and `question_this_section_answers`. The natural source is `sections-with-paragraphs-and-questions.json` from `annotate-section-questions-given-paragraphs`, but if the user instead has separate files — a `sections-with-paragraph-content.json` and a `sections-with-questions-only.json`/`sections-with-questions.json` — merge them by `section_number` before starting; both fields are required per section for this skill to do its job.

The order the user gives the two files matters: the first is `paper1`, and the correspondence is found *from* paper1's sections *to* paper2's sections. If it's ambiguous which should anchor the mapping, ask.

No PDF is needed or should be opened for this skill. If a section is missing paragraphs or a question, that means extraction/annotation needs to be (re)run on that paper first — it is not a reason to go find the PDF.

**Precondition: the question field is now guaranteed present.** `question_this_section_answers` is enforced by a hard completeness gate in `annotate-section-questions-given-paragraphs` (its own Step 4) — every section with non-empty `paragraphs` in either input file is guaranteed a real, non-null question; `null` is only legitimate when a section's own `paragraphs` array is genuinely empty. Treat the field as reliably present rather than something to conditionally check for. If a real counter-example turns up (non-empty paragraphs, null question), that's an input-integrity problem in the upstream extraction, not a normal case — flag it to the user rather than silently treating the question as absent or falling back to paragraph-only reasoning.

## Workflow

### Step 1: Read both signals for every section, in both files

For each entry in both `paper1` and `paper2`'s arrays, read `question_this_section_answers` *and* every paragraph in `paragraphs` — not just the first one or two paragraphs, and not just the question. Treat the question and the paragraphs as one joint body of evidence about the section's role — read both fully for every section, not the question first as a quick filter and the paragraphs second as confirmation. This joint-evidence reasoning, rather than question-only shortcutting, is the entire reason this skill exists alongside the questions-only variant.

**If a section's `paragraphs` array is empty and its `question_this_section_answers` is `null`** (both fields empty at once — this happens for genuinely content-less sections like References, or figure-only appendices), there is no content to reason with for that entry, so content-based matching is off the table. In this specific case only, fall back to matching by section name — but *only* if the two sections' names are an **exact match** (e.g. both literally "References," or both literally "Acknowledgments"). An exact title match on an otherwise-empty section is a reasonable enough signal when there's nothing else to go on. If the names are close but not identical (e.g. "Related Work" vs. "Background and Related Work," or two differently-worded appendix titles), don't guess — output `null` with a basis explaining there was no content to compare and the titles weren't an exact match either.

This exact-title exception applies **only** when both sides have empty paragraphs and a null question. The moment either section has real paragraph content, go back to matching by role (Step 2) — never let a shared or similar title substitute for reading the content when content actually exists.

**If only one of the two fields is present** (e.g. paragraphs exist but the question is `null`), still proceed — you have paragraph text to reason from directly, so treat it like a full-content read rather than falling back to null just because the question field is empty.

### Step 2: Map each paper1 section to its closest paper2 counterpart

For each `paper1` section, compare it against every `paper2` section using both signals together, not the question alone:

- **Judge role correspondence from the question and the paragraphs together, as one joint body of evidence — never let the question pre-filter which candidates get their paragraphs read.** For every paper1/paper2 candidate pair, read `question_this_section_answers` and every paragraph on both sides before deciding whether it's a match. A question worded narrowly, generically, or just differently from its counterpart can make a genuinely-corresponding pair look implausible before its paragraphs are ever read — and a candidate ruled out that way never gets a second look. Give every paper2 candidate both signals, every time, not just the ones a question-only pass would shortlist.
- **For narrative documents, compare narrative function rather than academic-argument function.** Relevant roles include presenting the mystery, introducing evidence, revising the investigation, escalating danger, confronting a suspect, explaining the solution, and closing the case. Shared characters, crime vocabulary, or setting are topics, not role correspondence. Different plot events can play the same narrative role.
- **Weigh the question as reliable, primary evidence of role, not a hint the paragraphs merely confirm or overrule.** It was composed specifically to capture the section's role, and — see the Inputs section's precondition note — is now guaranteed present for every section with real content. Treat it and the paragraphs as two witnesses to the same fact: when they agree, that agreement is real information, not something to re-derive from paragraphs alone.
- **Let the paragraphs override the question only on a genuine conflict** — when what the paragraphs actually show doesn't match what the question claims (the type-narrow pitfall below is the main way this happens), not merely because the question is phrased differently from its counterpart or leans on different vocabulary. The role-based test still applies once you're weighing the two together: "are these two sections doing the same job — occupying the same position in the arc from problem to contribution to evidence to reflection?" not "do they cover the same topic or use the same kind of evidence?" A section reporting fieldwork that shaped a design and another paper's subsection merely asserting design rationale with no fieldwork behind it can still be a real correspondence, if both are "the section that justifies the design." Put that kind of difference in `basis` as an observation, not a reason to reject the match.
- **A null `question_this_section_answers` on a section with real paragraph content is an input-integrity problem, not a normal case to quietly route around.** Upstream extraction now guarantees a real question for every section with non-empty paragraphs (see the Inputs section's precondition note). If you hit a counter-example anyway, flag it to the user explicitly as a gap in that paper's own extraction output, rather than silently treating the question as merely optional and reasoning from paragraphs alone as if nothing were wrong.
- **Watch for a question that's narrower than its own paragraphs — a type-narrow question shouldn't cost a section its match.** A section's precomputed question can name every sub-topic and still lock onto one connecting verb-frame that leaves out a different kind of content actually present in the paragraphs (e.g. a results section whose question asks only "how did participants use X" when its paragraphs also report how participants *felt* about X). If paper1's or paper2's question looks narrower than what its paragraphs actually cover, judge the match on the paragraphs, and say so explicitly in `basis` rather than silently accepting the question's framing. This is the specific advantage this skill has over `directional-section-mapping-by-questions-only`, which has no paragraphs to fall back on when a question undersells its section.
- **If a paper1 section legitimately corresponds to multiple paper2 sections** (or vice versa within a single paper1 entry's scope), create a **separate entry for each** correspondence rather than combining them into one label — the same splitting rule as both sibling skills, for the same reason: a combined label silently breaks downstream bidirectional comparison.
  - When splitting, use the paragraphs (not just the questions) to check that the split entries collectively still cover the full scope of paper1's section — don't let a sub-role quietly fall out of the split. This is easier to get right here than in the questions-only variant, since you have the actual paragraph text to check coverage against, rather than trying to parse a single compressed question into parts.
  - **A role doesn't need its own container to be worth splitting out.** Splitting only requires that some stretch of paragraphs plays a distinct role — it does not require that content to live in its own named subsection or appendix in the source paper. One paper might carve "verbatim task instructions" or "exact survey questions" or "coding methodology" out into their own dedicated subsections, while another paper folds all of that same content, as paragraphs, into one broad, dense section (its main "User Study" section, say, covering design, procedure, verbatim materials, and methodology all at once). The correspondence should still be found and split at the paragraph level in the dense paper, exactly as if that content had its own heading there too — a role being un-sectioned in the source paper is not evidence it doesn't exist as a distinct role.
- **There is no subsection fallback available here**, unless the input files themselves happen to include subsection-level entries (they won't, if built from `extract-top-level-section-names`, which is top-level only). If nothing in paper2's list plays paper1's role, the honest answer is `null`, not a forced pick of the least-bad option.
- **Use `null` only when, having read the actual paragraphs on both sides, nothing in paper2 is genuinely trying to do the same job.** Don't default to `null` just because the two questions are worded differently, and don't default to a weak match just because the two questions happen to share vocabulary — both calls should be argued from the paragraph content, with the question as co-equal evidence, not the final word on its own. (This content-based standard doesn't apply to the both-sides-empty case — see Step 1's exact-title exception for that.)
- **When the answer is `null` (no match found), don't compose a question for it.** Instead, copy `paper1_section`'s own `question_this_section_answers` value from the input file into `question_the_sections_both_answer`, verbatim — see "No-match entries now pull paper1's own question forward" above. The only exception is if paper1's own `question_this_section_answers` was itself `null` in the input file, in which case there's genuinely nothing to pull forward and the field stays `null`.

Each entry needs these fields:

| Field | Description |
|---|---|
| `paper1_section_name` | Section name/title from paper1 |
| `paper1_section_number` | Section number from paper1 (as a string) |
| `paper2_section_name` | Closest corresponding section name in paper2, or `null` |
| `paper2_section_number` | Corresponding section number in paper2, or `null` |
| `basis` | Why these sections correspond — ground this in what the paragraphs actually say, not just a restatement of the two questions. If you overrode a type-narrow question based on the paragraphs, say so here. If weak or `null`, say why. |
| `question_the_sections_both_answer` | **If `paper2_section_name` is non-null and this isn't the empty-content title fallback:** one question both sections are fundamentally trying to answer, freshly framed around role and informed by both papers' paragraph content, not just their precomputed questions verbatim. Keep it short and genuinely open — don't pack the answer into it via em-dashes or parentheticals. **If `paper2_section_name` is null (no match):** don't compose anything new — copy paper1's own `question_this_section_answers` value forward verbatim (see "No-match entries now pull paper1's own question forward" above). Only `null` if paper1's own question was itself `null`, or if the match came from Step 1's empty-content exact-title fallback (nothing on either side to pull forward from). |

### Output

Save as a JSON array of these objects. Default filename: `p1-p2-section-mapping-by-paragraphs-and-questions.json`. If running this a second time in the reverse direction, use a distinct name like `p2-p1-section-mapping-by-paragraphs-and-questions.json` so it doesn't overwrite the first pass — ask if unclear which pass this is.

Briefly tell the user how many sections got a confirmed match vs. `null`, flag any case where you overrode a section's own question because the paragraphs told a broader story, and flag anything else that stands out.

### Output schema (strict)

ALWAYS use this exact shape for every entry — exactly these six keys, no additions, no renaming, no reordering:

```json
{
  "paper1_section_name": "string",
  "paper1_section_number": "string or null",
  "paper2_section_name": "string, or null if no match",
  "paper2_section_number": "string or null, matches paper2_section_name's null-ness",
  "basis": "string, explains the match or why it's null — never null or empty itself",
  "question_the_sections_both_answer": "string: a freshly composed shared question if paper2_section_name is non-null (real content match); paper1's own question_this_section_answers pulled forward verbatim if paper2_section_name is null (no match). null only if paper1's own question was itself null, or if the match came from the empty-content exact-title fallback."
}
```

The file itself is a JSON array of these objects, e.g.:

```json
[
  {
    "paper1_section_name": "Results",
    "paper1_section_number": "7",
    "paper2_section_name": "Qualitative Results",
    "paper2_section_number": "6",
    "basis": "Paper1's Results paragraphs 1-2 and 5-11 report theme-organized participant quotes; the same qualitative-analysis role as paper2's dedicated section.",
    "question_the_sections_both_answer": "What did qualitative analysis of participant transcripts reveal about how they used and felt about the system?"
  },
  {
    "paper1_section_name": "References",
    "paper1_section_number": null,
    "paper2_section_name": "References",
    "paper2_section_number": null,
    "basis": "Both sides have empty paragraphs and a null question; falling back to the exact-title exception since both are literally titled References.",
    "question_the_sections_both_answer": null
  },
  {
    "paper1_section_name": "Ablation Study",
    "paper1_section_number": "5",
    "paper2_section_name": null,
    "paper2_section_number": null,
    "basis": "No paper2 section's paragraphs report a dedicated ablation — its single user study doesn't isolate feature contributions the way this section does.",
    "question_the_sections_both_answer": "What does the ablation study reveal about each feature's individual contribution to overall performance?"
  }
]
```

Note the "Ablation Study" example: `paper2_section_name` is `null` (no match), yet `question_the_sections_both_answer` is a real, non-null string — it's paper1's own `question_this_section_answers` from its input file, copied forward verbatim, not composed fresh for this entry. Contrast with the "References" example, where the question genuinely is `null`, because that entry came from the empty-content exact-title fallback (nothing on either side to pull forward).

`paper2_section_name` and `paper2_section_number` are always both `null` together or both non-null together. `question_the_sections_both_answer` is **only** `null` in two cases: (1) the empty-content exact-title fallback from Step 1 (real match, but nothing on either side to ground or pull forward a question from), or (2) paper1's own `question_this_section_answers` was itself `null` in the input file for a no-match entry (rare — flag it if it happens, since it likely means that paper's own extraction/annotation step left a gap). **A `null` question no longer means "no match" by itself, and — just as important — a non-null question no longer means "there is a match."** Check `paper2_section_name` for match status in both directions; don't infer it from this field either way. `basis` is always a non-empty string — including for the exact-title-fallback case and the null-match case, both of which need their reasoning stated explicitly, not left implicit. Don't add extra fields — no `confidence`, no `paragraphs`, nothing beyond these six keys.

## Common mistakes to avoid

- **Opening a PDF, or asking for one.** This skill's reason to exist, same as its questions-only sibling, is to skip that cost — if the two input files are missing paragraphs or questions for a section, say so and treat it as an extraction gap, not a reason to go find the source PDF.
- **Reading only the question field and ignoring the paragraphs, OR reading only the paragraphs and treating the question as a mere afterthought.** Both fields are co-equal, joint evidence — the paragraphs must actually inform the match and the `basis`, not just get skimmed and set aside, and the question must be weighed as reliable primary evidence, not demoted to a spot-check performed only after the paragraphs already decided the outcome.
- **Letting the question pre-filter which paper2 candidates ever get their paragraphs read.** A narrow, generic, or differently-worded question can make a real correspondence look implausible before its paragraphs are ever opened. Read both signals for every candidate pair, not just the ones a question-only shortlist would surface.
- **Trusting a type-narrow question at face value.** A question that names every sub-topic can still exclude a different *kind* of content living in the same paragraphs (e.g. behavior vs. attitude/experience in qualitative results). Check the paragraphs for what they actually report, not just whether the question's topic list matches.
- **Matching on shared vocabulary/topic instead of shared role.** Two sections can share keywords while doing different jobs in their papers, and use completely different wording while doing the same job. Judge by what each section is trying to establish in its paper's arc.
- **Combining multi-section correspondences into one label instead of splitting them.** Same rule as both sibling skills, same reason: breaks exact-match bidirectional comparison downstream.
- **Splitting a section but letting a sub-role fall out of scope.** Use the paragraphs to verify the split entries collectively cover everything the paper1 section's paragraphs actually address — don't let a piece quietly disappear because it wasn't reflected in the (possibly narrower) precomputed question.
- **Assuming a dense section's most prominent role is its only role, and stopping there.** The more distinct jobs a section's paragraphs do at once (say, procedure narrative plus verbatim materials plus a methodology aside, all folded into one section rather than split into subsections), the easier it is to write one broad `basis`/question for the section's overall shape and miss that a narrower stretch of paragraphs inside it plays a role that deserves its own split entry. A section's boundary in its own source paper is not a signal about how many roles it plays — read every paragraph range for its own role, especially in a section that reads as unusually long or multi-part.
- **Defaulting to `null` without reading the paragraphs first.** The compressed questions alone can make two sections look unrelated when their actual content lines up, or look related when it doesn't — always confirm against the paragraph text before writing `null` or before accepting a shaky-looking match.
- **Applying the exact-title fallback to a section that actually has paragraph content.** The exact-title exception in Step 1 exists only because there's nothing else to go on for empty sections — if either side has real paragraphs, match by role as usual, even if the titles happen to match exactly too (a shared title is a coincidence, not evidence, once there's content to actually read).
- **Guessing an inexact title match for two empty sections instead of outputting `null`.** "References" and "Bibliography," or two differently-numbered/worded appendices, are not an exact match — the exception in Step 1 requires the names to be identical, not merely similar. When both sides are empty and the titles aren't identical, the honest answer is `null`.
- **Writing a long, compound `question_the_sections_both_answer` that answers itself via em-dash asides or parentheticals.** Same rule as the skills that produced the input questions — keep it short enough to ask out loud. This applies to the freshly-composed (real-match) case; a pulled-forward (no-match) question was presumably already held to this standard when it was first composed, so just copy it, don't re-edit it.
- **Leaving `question_the_sections_both_answer` null for a no-match entry, or composing a brand-new question for it, instead of pulling paper1's own `question_this_section_answers` forward verbatim.** This was a real bug (fixed 2026-08-16), caught via a real leftover-section-differences.json entry that had a null question despite paper1's own section already having a perfectly good precomputed question sitting in the input file. See "No-match entries now pull paper1's own question forward" above.
- **Rewording, paraphrasing, or "improving" paper1's own question when pulling it forward for a no-match entry.** Copy it byte-for-byte. It was already held to this skill family's phrasing standard when it was first composed; re-touching it risks introducing a subtle drift between the two copies for no benefit.
- **Assuming `question_the_sections_both_answer: null` always means no match was found, OR assuming a non-null value there always means a match was found.** Neither holds anymore now that no-match entries normally carry a pulled-forward, non-null question. Check `paper2_section_name` for match status in both directions — never infer it from this field.
- **Treating a null question as merely optional and quietly proceeding on paragraphs alone.** It's now a guaranteed precondition (see Inputs). A real counter-example is an input-integrity problem in the upstream file — flag it explicitly rather than silently routing around it.
- **Treating this skill as if it already does the bidirectional check.** It doesn't, on purpose — same as both siblings. Point users who want confirmed/bidirectional matches to `paper-section-alignment`, or run this skill twice.
- **Leaving `paper2_section_number` non-null when `paper2_section_name` is null, or vice versa, or writing an empty `basis`.** See "Output schema (strict)" above — these two fields' null-ness must always match, and `basis` is never empty, even for a null or title-fallback match.

