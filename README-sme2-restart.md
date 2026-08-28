# Elena's restart of the SME-2 implementation

This is a fresh, better SME-2 implemenation.

Four stages, ordered:

1. **PDF → nested sections/subsections/paragraphs** (a Claude skill)
2. **Add a role question to every section, subsection, and paragraph** (a standalone script: `pipeline/annotate_text_questions.py`)
3. **Closest-match batch** (a standalone script: `pipeline/closest_section_match_batch.py`)
4. **Closest-match graph** (a standalone script/module: `pipeline/closest_match_graph.py`) — accumulates Stage 3's per-pair output into one persistent cross-paper correspondence graph, confirming bidirectional matches and flagging redundant one-directional ones

## Setup

Same environment as the rest of the repo:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

Stage 1 is run as a Claude skill inside a Cowork/Claude Code session (not a standalone
script in this repo). Stages 2, 3, and 4 are standalone Python scripts you run yourself
from a terminal, using the key above (Stage 4 itself makes no API calls, but shares the
same environment).

## Stage 1: PDF → nested sections, subsections, and paragraphs (no appendices)

Run via the `orchestrator-extract-sections-subsecs-paragraphs-no-appendices` skill (in
`skills/orchestrator-extract-sections-subsecs-paragraphs-no-appendices/`), one PDF at a
time. It chains two sub-skills and always re-reads the PDF fresh — there's no
cheap-derivation shortcut for this variant:

1. `extract-top-and-second-level-section-names-excluding-appendices` — top-level section
   names/numbers plus, nested under each, its second-level subsection names/numbers (if
   any), with appendix entries filtered out by role and position.
2. `extract-section-and-subsection-paragraphs` — splits each top-level section's text
   into paragraphs. A section with subsections gets only its lead-in text (before the
   first subsection heading) in its own `paragraphs` field; each subsection carries its
   own `paragraphs` array. Includes a hard order-integrity check, surfaced explicitly if
   any content has nowhere correct to go without misrepresenting PDF reading order.

Output, both saved alongside the PDF:

- `{paper-name}-sections-with-subsections-no-appendices.json`
- `{paper-name}-sections-with-subsections-and-paragraph-content-no-appendices.json`

This orchestrator deliberately does **not** compose any question fields — that's Stage 2.

Already run for five papers in `papers/hci 5 paper corpus/`: `abstractexplorer`,
`corpusstudio`, `examplore_chi18`, `mesotext`, `paralib_uist22`.

## Stage 2: Add a role question to every section, subsection, and paragraph

Script: `pipeline/annotate_text_questions.py` (single file) and
`pipeline/annotate_text_questions_from_manifest.py` (runs it over every paper listed in
a manifest). Committed 2026-08-27. This is **not** a Claude skill — it's a standalone
script that calls the Anthropic API directly, same shape as the main pipeline's other
`extract_*`/`summarize_*` scripts.

It walks a Stage 1 nested JSON file — sections, then subsections, then paragraphs, in
that order — and writes a `question_this_text_answers` field onto every non-empty unit
at all three levels (not just section/subsection): each top-level section (from its own
lead-in text plus all its subsections' text, serialized in paper order), each subsection
(its own text alone), and each individual paragraph (serialized with its parent
section/subsection headers for context). A unit with no real text becomes `null` with no
API call; an already-annotated unit is skipped unless `--force` is passed.

```bash
cd pipeline

# One file at a time
python3 annotate_text_questions.py path/to/paper-sections-with-subsections-and-paragraph-content-no-appendices.json

# All five HCI-corpus papers via the checked-in manifest
python3 annotate_text_questions_from_manifest.py incremental_graph/runs/hci-five-paper-corpus/manifest.yaml
```

Useful flags on both: `--dry-run` (print what would be sent/written without calling the
API or touching the file), `--force` (recompute even where the field already exists),
`--model` (defaults to `$SME_EXTRACT_MODEL` or `claude-sonnet-5`), `--cache-dir`
(defaults to `pipeline/output/_cache/text_questions/` — per-unit response cache, keyed
by a hash of the system prompt + serialized text, so a rerun after a crash or partial
completion doesn't re-pay for units already answered).

The system prompt asks for the unit's *function/role* in the document — what job the
text is doing, not its topic or a restatement of its title — kept short (under ~20
words), genuinely open, and never self-answering (no parenthetical lists of specifics).
After annotating, the script runs a **hard completeness check**: any non-empty unit
still missing a non-null `question_this_text_answers` fails the whole run with a
non-zero exit and a listed set of violations, rather than silently leaving gaps.

All five papers in `papers/hci 5 paper corpus/` already have this field filled in at
every level. Stage 3 refuses to run against a file that shows no sign of having been
through this step (see its own precondition check, described below).

## Stage 3: Closest-match batch — `pipeline/closest_section_match_batch.py`

A standalone re-implementation of the `closest-section-match-nested` skill's workflow as
an automated script, run over an **ordered pair** of Stage 1/2 output files:

```bash
cd pipeline
python3 closest_section_match_batch.py \
  --paper1 "/path/to/paperA-sections-with-subsections-and-paragraph-content-no-appendices.json" \
  --paper2 "/path/to/paperB-sections-with-subsections-and-paragraph-content-no-appendices.json" \
  [--output OUTPUT.json] [--model claude-sonnet-5] [--max-workers 5] [--limit N] [--resume]
```

Example, using two of the five HCI papers already through Stages 1–2:

```bash
python3 closest_section_match_batch.py \
  --paper1 "/Users/elena/GitRepos/SME-prototype/papers/hci 5 paper corpus/examplore_chi18-sections-with-subsections-and-paragraph-content-no-appendices.json" \
  --paper2 "/Users/elena/GitRepos/SME-prototype/papers/hci 5 paper corpus/corpusstudio-sections-with-subsections-and-paragraph-content-no-appendices.json" \
  --limit 5
```

### What it does

**Candidate construction (identical for both papers).** Every top-level entry becomes
one "whole section" candidate (its own lead-in paragraphs plus every subsection's
paragraphs, concatenated, tagged with the entry's own `question_this_text_answers`) plus,
if it has subsections, one candidate per subsection (that subsection's own paragraphs
alone, tagged with its own question). Paper1's full candidate list is what the script
loops **queries** over; paper2's full candidate list is the fixed **pool** every query is
matched against.

**Matching.** For each paper1 candidate, one Claude call sends the full paper2 candidate
pool (names, numbers, questions, paragraph text) and asks for the single closest match by
role (or none) — judge by shared role, not shared vocabulary; weigh the question as
primary evidence; let paragraphs override only on a genuine conflict; never split into
more than one match. A candidate with empty paragraphs *and* no question is resolved
locally via an exact-name fallback instead, at no API cost.

**Prompt caching, with a pre-warm step.** Paper2's full candidate pool is identical
across every query in a run, so it's sent as one `cache_control: {"type": "ephemeral"}`
content block. Because the per-query calls are independent of each other's results, they
run concurrently via a thread pool (`--max-workers`, default 5) rather than one at a
time. But a cache entry only becomes readable after the response that *wrote* it begins
— firing every query at once from a cold cache would make several race to write the same
block, each paying the full write price. The script avoids that by sending one dedicated
`max_tokens: 0` pre-warm request first (confirmed via `cache_creation_input_tokens > 0`
in its response), and only opens the thread pool once that write is confirmed. Every real
query call after that should then read the already-warm cache instead of re-writing it.

**`--limit` / `--resume`, for inspectable batches.** `--limit N` sends at most N real API
calls in one run (free local fallback matches don't count against it) and writes
whatever's been resolved so far to the output file, printing the exact resume command.
`--resume` reloads that output file, matches existing rows back to their query by
section/subsection identity, and skips anything already resolved — so re-running never
re-sends or re-pays for a query that already has an answer. Useful for smoke-testing a
new paper pair before committing to a full run:

```bash
# First batch: 5 real calls, then stop
python3 closest_section_match_batch.py --paper1 ... --paper2 ... --limit 5

# Inspect the partial output file, then continue in more batches of 5...
python3 closest_section_match_batch.py --paper1 ... --paper2 ... --resume --limit 5

# ...or finish the rest in one go once you're satisfied
python3 closest_section_match_batch.py --paper1 ... --paper2 ... --resume
```

### Output

`{paperA-name}-{paperB-name}-closest-section-match-batch.json` (default name, alongside
paper1) — one row per paper1 candidate:

| Field | Meaning |
|---|---|
| `paper1_section_name`, `paper1_section_number` | Paper1 candidate's top-level section identity |
| `paper1_subsection_name`, `paper1_subsection_number` | `null` for a whole-section candidate; populated for a subsection candidate |
| `paper2_section_name`, `paper2_section_number` | Matched section in paper2, or `null` if no match |
| `paper2_subsection_name`, `paper2_subsection_number` | `null` for a whole-section match, a no-match, or if paper2's match is itself a whole section |
| `basis` | Why the match holds (or why nothing corresponds) — never empty |

Console output at the end reports API calls made, fallback-resolved count, real matches
vs. no-match, and token usage split into `input_tokens` / `cache_creation_input_tokens` /
`cache_read_input_tokens` / `output_tokens` — expect the cache-creation cost concentrated
in the pre-warm call, and every real query call after it showing a cache read instead.

### Notes

- Requires the `anthropic` Python package and `ANTHROPIC_API_KEY` in the environment.
  This script does **not** use the main pipeline's on-disk response cache under
  `output/sections/_cache/`; its cost control is Anthropic prompt caching plus
  `--limit`/`--resume`, not response caching.
- No `temperature` parameter is set on the matching calls — this model generation
  rejects it (`400 invalid_request_error: temperature is deprecated for this model`)
  rather than ignoring it, unlike earlier Claude models where `temperature=0` was
  typically used here for determinism.
- Keep `--max-workers` within your account's requests-per-minute rate limit — all
  workers share one `Anthropic` client, and concurrent calls burst against that limit in
  a way a sequential loop with a fixed sleep wouldn't.

## Stage 4: Closest-match graph — `pipeline/closest_match_graph.py`

Module + CLI (`ClosestMatchGraph`, wrapping `nx.MultiDiGraph` — `networkx` is already in
`pipeline/requirements.txt`, no new dependency). Turns Stage 3's per-pair output into one
persistent, incrementally-growing cross-paper structure, rather than leaving each pair's
`closest-section-match-batch.json` as an island.

**Feed it one paper pair's two directional passes at a time.** For a pair (A, B) you run
Stage 3 twice — `--paper1=A --paper2=B` and `--paper1=B --paper2=A` — then call:

```bash
cd pipeline
python3 closest_match_graph.py \
  --graph closest_match_graph.json \
  --paper1-id examplore_chi18 --paper2-id corpusstudio \
  --paper1-to-paper2 "path/to/examplore_chi18-corpusstudio-closest-section-match-batch.json" \
  --paper2-to-paper1 "path/to/corpusstudio-examplore_chi18-closest-section-match-batch.json"
```

Each run loads the existing graph (or starts fresh), adds this one pair, and saves back —
so running it once per pair as more `closest-section-match-batch.json` files are generated
is how the graph grows over time.

**Confirmed matches collapse into one node; everything else stays a visible edge.** If
both directional passes independently agree on a correspondence (A's unit → B's unit AND
B's unit → A's same unit), the two units' nodes merge into one group node whose `members`
list keeps absorbing further confirmed units as more pairs are processed — a unit
confirmed-matched in pair (A, B) and later confirmed-matched again in pair (B, C) ends up
in the *same* three-member node, not two disconnected ones. If only one direction found
the match, it becomes a `one_directional_match` edge between the two separate nodes
instead — weaker evidence, kept visible rather than discarded.

**`redundant_edges()` flags (without removing) one-directional edges made redundant by an
existing confirmed match.** Rule: a one-directional edge (S → T) is flagged when some
other unit in S's own section family — its parent section, or a sibling subsection under
that same parent — is *already* confirmed-matched to that exact same T. It deliberately
does **not** flag an edge whose target is merely *near* an already-confirmed match (e.g. a
sibling of the confirmed partner, or its parent) — that case is a genuine finer-grained
refinement of an already-confirmed whole-section pairing, not a restatement of it, so it's
left alone. `.summary()` reports the flagged count as `redundant_one_directional_edges`;
nothing is ever pruned automatically, so every flag stays inspectable against its
`covering_confirmed_node` and original `basis` text.

Tests: `pipeline/tests/test_closest_match_graph.py` (11 cases — confirmed merges,
one-directional edges, incremental cross-pair growth, save/load round-tripping,
idempotent re-processing, and both directions of the redundancy rule plus the
non-redundant refinement case).

## Worked example: examplore_chi18 ↔ corpusstudio

Both directional Stage 3 passes have been run for this pair and fed into the graph.
Numbers, for a sense of what a real pair looks like: 23 examplore_chi18 queries, 21
non-empty corpusstudio queries, **12 confirmed bidirectional matches**, 30 raw
one-directional matches, of which **11 are flagged redundant** by the Stage 4 rule above,
leaving **19 genuinely open one-directional correspondences**.

The confirmed matches cover the paper skeleton cleanly — Abstract, Introduction, whole
Related Work, whole User Study (+ Participants), Discussion, Conclusion, Acknowledgments,
References, plus Results splitting into Quantitative/Qualitative Analysis on one side
matching the other's separate Quantitative/Qualitative Results sections.

### Open questions for discussion

The 19 remaining one-directional matches aren't noise scattered evenly across the paper —
they cluster into two specific structural disagreements worth raising with collaborators,
plus a few smaller loose ends.

**1. Related Work: the two papers' subsection breakdowns don't line up, and the two
matching passes actively disagree about how to reconcile them.** examplore_chi18 splits
Related Work into three subsections (Interfaces for Exploring Collections of Complex
Objects; Learning APIs with Code Examples; Mining and Visualization of API Usage);
corpusstudio splits its Background and Related Work into a different three (Community
Writing Norms 2.1; Writing with External Text 2.2; Finding Relevant Examples 2.3). Neither
side's three subsections map onto the other's three subsections 1:1. Concretely:
examplore_chi18's own pass matches its "Learning APIs with Code Examples" subsection to
corpusstudio's 2.2 ("Writing with External Text") — but corpusstudio's own pass has *two
different* subsections (2.1 "Community Writing Norms" *and* 2.3 "Finding Relevant
Examples") both independently proposing that same examplore_chi18 subsection as their own
closest match, while ignoring 2.2 entirely as the reverse-direction pick. That's a genuine
three-way disagreement about where the boundaries are, not just a labeling difference —
worth a human call on whether these three-vs-three subsection sets should be considered
structurally comparable at all, or whether one paper's Related Work is organized by a
different principle than the other's.

**2. System description: examplore_chi18 splits across three top-level sections that
corpusstudio bundles into one.** examplore_chi18 has three separate top-level sections for
what corpusstudio does in one: SYNTHETIC CODE SKELETON (core design concept),
SCENARIO: INTERACTING WITH CODE DISTRIBUTIONS (walkthrough — already confirmed against
corpusstudio's Usage Scenario subsection), and SYSTEM ARCHITECTURE AND IMPLEMENTATION
(technical pipeline). corpusstudio bundles design goals, scenario, feature description, and
implementation all under one top-level "Corpus Studio" section (3), broken into
subsections instead. The mismatch shows up as an unresolved triangle: examplore_chi18's
whole SYSTEM ARCHITECTURE AND IMPLEMENTATION points at corpusstudio's whole "Corpus
Studio" section, but corpusstudio's whole "Corpus Studio" section points back at
examplore_chi18's SYNTHETIC CODE SKELETON instead (not System Architecture) — and
corpusstudio's "Implementation Details" subsection (3.4) separately points at
examplore_chi18's whole System Architecture section, closer but still not confirmed
against anything examplore_chi18 itself proposed. Worth deciding, as a matter of
comparison methodology, whether to treat corpusstudio's whole "Corpus Studio" section as
the counterpart to *all three* of examplore_chi18's top-level sections combined, rather
than expecting a single best match.

**Root cause, confirmed by the model's own reasoning, not just inferred from the
mismatch.** Both directional passes independently describe the same underlying fact in
their own `basis` text, then still resolve it differently. The reverse-direction row
(`Corpus Studio → SYNTHETIC CODE SKELETON`) says the query "is a single top-level section
combining scenario + design + implementation, and paper2 splits these into three separate
sections (SYNTHETIC CODE SKELETON, SCENARIO, SYSTEM ARCHITECTURE AND IMPLEMENTATION) ...
with secondary correspondence to the SCENARIO and IMPLEMENTATION sections." The
forward-direction row (`SYSTEM ARCHITECTURE AND IMPLEMENTATION → Corpus Studio`)
independently says corpusstudio's whole section "combin[es] design and implementation
details" into one. So this isn't ordinary matcher noise or a coin-flip disagreement —
both passes agree corpusstudio genuinely bundles three roles that examplore_chi18 keeps
separate. The Usage Scenario slice of that bundle already resolved cleanly, because it
has its own subsection and confirmed against SCENARIO on its own. What's left when the
*whole* "Corpus Studio" section is queried (lead-in text plus every remaining
subsection, concatenated — see Stage 3's candidate construction above) is an undivided
mix of "design concept" and "implementation," which doesn't reduce to one target the same
way twice: the forward pass weights the implementation half and picks SYSTEM ARCHITECTURE
AND IMPLEMENTATION; the reverse pass weights the design-concept half and picks SYNTHETIC
CODE SKELETON. Each direction only ever sees its own single query in isolation, with no
visibility into how the other direction split the same content — so a genuine
one-to-many correspondence, which Stage 3's own splitting rule ("if a query legitimately
corresponds to multiple candidates, create a separate output entry for each") exists to
handle, never gets the chance to trigger, because no single query row spans both
directions at once.

**Smaller loose ends**, not part of either cluster above but still unresolved:

- `Corpus Studio > Design Goals` → `INTRODUCTION` (corpusstudio has no dedicated Design
  Goals equivalent in examplore_chi18; the Introduction is the closest examplore_chi18
  gets to stating design rationale up front).
- `User Study > Study Procedure` ↔ `USER STUDY > Methodology` (near-miss: each side's
  procedural-walkthrough subsection points at the other, but by different names, and
  examplore_chi18's own pass instead matched Methodology to the whole User Study section
  rather than reciprocating Study Procedure specifically).
- `Qualitative Results > Document-level Writing Support` → `RESULTS` (whole) — the one
  corpusstudio Qualitative Results subsection whose target is the *whole* Results section
  rather than the already-confirmed `RESULTS > Qualitative Analysis` subsection specifically.

### Full data: confirmed, redundant, and surviving matches

Raw tables behind the numbers and clusters above, for reference.

**Confirmed bidirectional matches (12)**

| examplore_chi18 | corpusstudio |
|---|---|
| ABSTRACT | Abstract |
| INTRODUCTION | Introduction |
| RELATED WORK (whole) | Background and Related Work (whole) |
| SCENARIO: INTERACTING WITH CODE DISTRIBUTIONS | Corpus Studio > Usage Scenario |
| USER STUDY (whole) | User Study (whole) |
| USER STUDY > Participants | User Study > Participants |
| RESULTS > Quantitative Analysis | Quantitative Results (whole) |
| RESULTS > Qualitative Analysis | Qualitative Results (whole) |
| DISCUSSION AND LIMITATIONS (whole) | Discussion (whole) |
| CONCLUSION (whole) | Conclusion (whole) |
| ACKNOWLEDGMENTS | Acknowledgments |
| REFERENCES (empty) | References (empty) |

**One-directional matches filtered as redundant (11)** — each target is already the exact
confirmed partner of another member of the source's own section family; the third column
is that covering confirmed match (from the table above):

| Source | → Target | Caused by (confirmed match) |
|---|---|---|
| corpusstudio: Background and Related Work > Writing with External Text | examplore_chi18: RELATED WORK | RELATED WORK (whole) ↔ Background and Related Work (whole) |
| examplore_chi18: USER STUDY > Methodology | corpusstudio: User Study | USER STUDY (whole) ↔ User Study (whole) |
| examplore_chi18: RESULTS (whole) | corpusstudio: Qualitative Results (whole) | RESULTS > Qualitative Analysis ↔ Qualitative Results (whole) |
| corpusstudio: Qualitative Results > Sentence-level Writing Support | examplore_chi18: RESULTS > Qualitative Analysis | RESULTS > Qualitative Analysis ↔ Qualitative Results (whole) |
| corpusstudio: Qualitative Results > Bookmark and User Notes | examplore_chi18: RESULTS > Qualitative Analysis | RESULTS > Qualitative Analysis ↔ Qualitative Results (whole) |
| corpusstudio: Qualitative Results > Tooltips | examplore_chi18: RESULTS > Qualitative Analysis | RESULTS > Qualitative Analysis ↔ Qualitative Results (whole) |
| corpusstudio: Qualitative Results > Use of Features, Especially Across Writing Stages | examplore_chi18: RESULTS > Qualitative Analysis | RESULTS > Qualitative Analysis ↔ Qualitative Results (whole) |
| corpusstudio: Quantitative Results > Task 1: Outline Writing | examplore_chi18: RESULTS > Quantitative Analysis | RESULTS > Quantitative Analysis ↔ Quantitative Results (whole) |
| corpusstudio: Quantitative Results > Task 2: Writing a Section of a Manuscript | examplore_chi18: RESULTS > Quantitative Analysis | RESULTS > Quantitative Analysis ↔ Quantitative Results (whole) |
| corpusstudio: Discussion > Designing a System with Many Retrieved Examples | examplore_chi18: DISCUSSION AND LIMITATIONS | DISCUSSION AND LIMITATIONS (whole) ↔ Discussion (whole) |
| corpusstudio: Discussion > Limitations and Future Work | examplore_chi18: DISCUSSION AND LIMITATIONS | DISCUSSION AND LIMITATIONS (whole) ↔ Discussion (whole) |

**One-directional matches that survived the filter — forward, examplore_chi18 → corpusstudio (7)**

| examplore_chi18 | → corpusstudio |
|---|---|
| RELATED WORK > Interfaces for Exploring Collections of Complex Objects | Background and Related Work > Finding Relevant Examples |
| RELATED WORK > Learning APIs with Code Examples | Background and Related Work > Writing with External Text |
| RELATED WORK > Mining and Visualization of API Usage | Background and Related Work > Writing with External Text |
| SYSTEM ARCHITECTURE AND IMPLEMENTATION (whole) | Corpus Studio (whole) |
| SYSTEM ARCHITECTURE AND IMPLEMENTATION > Data Collection | Data & Processing > Pre-processing Documents |
| SYSTEM ARCHITECTURE AND IMPLEMENTATION > Post-processing | Corpus Studio > Implementation Details |
| SYSTEM ARCHITECTURE AND IMPLEMENTATION > Visualization | Corpus Studio > System Characteristics |

**One-directional matches that survived the filter — reverse, corpusstudio → examplore_chi18 (12)**

| corpusstudio | → examplore_chi18 |
|---|---|
| Background and Related Work > Finding Relevant Examples | RELATED WORK > Learning APIs with Code Examples |
| Corpus Studio (whole) | SYNTHETIC CODE SKELETON |
| Data & Processing > Pre-processing Documents | SYSTEM ARCHITECTURE AND IMPLEMENTATION > Post-processing |
| Corpus Studio > Implementation Details | SYSTEM ARCHITECTURE AND IMPLEMENTATION (whole) |
| Corpus Studio > System Characteristics | SYNTHETIC CODE SKELETON |
| Background and Related Work > Community Writing Norms | RELATED WORK > Learning APIs with Code Examples |
| Corpus Studio > Design Goals | INTRODUCTION |
| Data & Processing (whole) | SYSTEM ARCHITECTURE AND IMPLEMENTATION (whole) |
| Data & Processing > Embedding Process | SYSTEM ARCHITECTURE AND IMPLEMENTATION > Post-processing |
| Data & Processing > Extracting an Ordered Distribution over Section Titles | SYSTEM ARCHITECTURE AND IMPLEMENTATION > Post-processing |
| User Study > Study Procedure | USER STUDY > Methodology |
| Qualitative Results > Document-level Writing Support | RESULTS (whole) |

## Open gaps

- **No wrapper that runs both Stage 3 directions and updates the graph in one command.**
  Today: run Stage 3 twice by hand (`--paper1=A --paper2=B`, then `--paper1=B --paper2=A`),
  then call `closest_match_graph.py` with both output files. A single orchestrating script
  would remove that manual step.
- **`redundant_edges()` is available as a library/CLI-summary count, but nothing renders
  the flagged list to a file yet** — the worked example above was generated by calling it
  directly in a Python shell, not via a packaged report/export command.
