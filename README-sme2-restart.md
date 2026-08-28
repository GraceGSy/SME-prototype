# Elena's restart of the SME-2 implementation

This is a fresh, better SME-2 implemenation.

Three stages, ordered:

1. **PDF → nested sections/subsections/paragraphs** (a Claude skill)
2. **Add a role question to every section, subsection, and paragraph** (a standalone script: `pipeline/annotate_text_questions.py`)
3. **Closest-match batch** (a standalone script: `pipeline/closest_section_match_batch.py`)

## Setup

Same environment as the rest of the repo:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

Stage 1 is run as a Claude skill inside a Cowork/Claude Code session (not a standalone
script in this repo). Stages 2 and 3 are standalone Python scripts you run yourself from
a terminal, using the key above.

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

## Open gaps

- **No aggregation step yet** past a single ordered pair's `closest-section-match-batch.json`.
  Comparing across more than two papers, or turning per-pair match files into a shared
  structure the way the main pipeline's grouping/refinement steps do, isn't built here.
