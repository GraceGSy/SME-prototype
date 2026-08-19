# Structural cross-paper matching pipeline

Extracts a hierarchical structure (sections → paragraphs) from a set of academic
papers, tags each unit with a free-text question describing its role, cross-matches
those tags between papers, groups the resulting links, and iteratively refines those
groups (the "epoch" track) into a small set of cross-paper research-question clusters.

**This README assumes you already have each paper split into sections and
paragraphs** — i.e. you have a `stage-0-pseudo-section-files/` folder like
`SME/papers/papers1/stage-0-pseudo-section-files/` or
`SME/papers/papers3/stage-0-pseudo-section-files/`, one JSON file per paper, each
holding that paper's sections in reading order with each section's paragraphs
already split out (see "Starting input" below for the exact shape). Getting from a
raw PDF to that shape isn't covered by the steps below — the older, raw-PDF-driven
scripts (`extract_sections.py`, `attach_section_text.py`, `extract_fine_grained.py`)
still exist and still work if you need that starting point instead, but the
paragraph splits they produce are lower quality than what a dedicated Claude Skill
run per paper gives you, which is why this pipeline now assumes the latter.

Loosely inspired by Gentner's Structure-Mapping Engine (structural alignment between
papers), but implemented as a much simpler tag-matching pipeline rather than a full
entity/proposition graph aligner. (An earlier, more literal SME-style attempt lives in
`schema.py` / `extract_graph.py` / `align_graphs.py` / `align_trace.py` / `cli.py` and
`viz/index.html` / `viz/align_viewer.html` — **not used by the current pipeline**,
kept only for reference. The iteration-based paragraph-group refinement track —
`summarize_groups.py`, `refine_paragraph_groups.py`, `compute_ranking_matrices.py`,
`compute_group_balance.py` — is also still in the codebase but not needed to reach
epoch results and isn't covered here either.)

## Setup

```bash
pip install -r requirements.txt
```

Requires an Anthropic API key with available credit:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

(The scripts read this from the environment directly via the `anthropic` SDK — there's
no `.env` loading in the code, so `export` it in your shell, or `source` a `.env` file
yourself before running.)

Optionally override the model used for extraction/tagging/summarization calls
(defaults to `claude-sonnet-5`):

```bash
export SME_EXTRACT_MODEL=claude-sonnet-5
```

Every script below reads its output/input directory from `SME_OUTPUT_DIR` (defaults
to `output/sections` next to the scripts if unset) — set it once per run and every
step in that run reads and writes the same directory:

```bash
export SME_OUTPUT_DIR="$(pwd)/output/my_paper_set"
```

## Starting input: `stage-0-pseudo-section-files/`

One JSON file per paper, named `<paper_id>-sections-with-paragraphs-and-questions-no-appendices.json`,
each a JSON array of that paper's sections **in reading order**, appendices already
excluded:

```json
[
  {
    "section_name": "Introduction",
    "section_number": "1",
    "paragraphs": [
      {"paragraph_number": 1, "text": "..."},
      {"paragraph_number": 2, "text": "..."}
    ],
    "question_this_section_answers": "..."
  },
  ...
]
```

`section_number` is `null` for unnumbered sections (Abstract, Acknowledgments,
References, ...). Despite its name, `question_this_section_answers` is **not** used
by any step below — tagging is done fresh, later, from the paragraph text itself (see
Steps 2–3). The paper's `paper_id` is derived from the filename (everything before
`-sections-with-paragraphs-and-questions-no-appendices.json`).

## Running the pipeline

Run these **in order**. Every output file below lives in `$SME_OUTPUT_DIR`.

```bash
# Step 1 -- script: build_hybrid_from_pseudo_sections.py
# Converts every stage-0 pseudo-section file in SOURCE_DIR into the
# pipeline's own SectionedPaper shape: sections get a fresh "s1", "s2", ...
# id (in reading order) and their text reconstructed by joining their
# paragraphs; paragraphs get a fresh, whole-paper-continuous "pa1", "pa2",
# ... id and record their parent section's id. No API call. Both sections'
# and paragraphs' `tag` fields are left as "" -- tagging is Steps 2-3.
# If <paper_id>.json already exists in $SME_OUTPUT_DIR, its paper_id/title
# are preserved (only sections/paragraphs are replaced); otherwise both
# default to the filename-derived paper_id, since stage-0 files don't carry
# a title -- hand-edit it afterward if you want the paper's real title on
# record.
# Output: <paper_id>.json (sections + paragraphs, no tags yet) + manifest.json
python3 build_hybrid_from_pseudo_sections.py SME/papers/papers1/stage-0-pseudo-section-files

# Step 2 -- Claude Skill: annotate-section-questions-given-paragraphs
#   (implemented directly by script: tag_hybrid_sections.py)
# For every section, reads ALL of its already-extracted paragraphs and
# composes one role-based question the section exists to answer in the
# paper's argument (never a topic summary, never self-answering, must span
# every paragraph -- see SME/skills/annotate-section-questions-given-paragraphs.skill
# for the skill's own full guidance, which this script's system prompt
# follows). One Claude call per section. A section with zero paragraphs
# (References, typically) is left with tag = "".
# Output: <paper_id>.json, sections now have a real `tag`
python3 tag_hybrid_sections.py

# Step 3 -- script: tag_hybrid_paragraphs.py
# The original pipeline's own paragraph-tagging logic (extract_fine_grained.py's
# tag guidance, verbatim), WITHOUT its paragraph-segmentation/start_text/
# discourse-relation machinery -- paragraphs here are already correctly
# split (Step 1), so this only adds a tag to each one. One Claude call per
# section, batching that section's paragraphs into one request, matched
# back to their existing unit_id (not by response order).
# Output: <paper_id>.json, paragraphs now have a real `tag`
python3 tag_hybrid_paragraphs.py

# Step 4 -- script: filter_references.py
# Drops each paper's References section (and any of its own paragraphs),
# in place. A paper with no References section, or one that already has
# zero paragraphs, is left untouched. No API call.
# Output: <paper_id>.json, References section (and its paragraphs) removed
python3 filter_references.py

# Step 5 -- script: match_tags.py
# For every section/paragraph, find its top-3 most similar tags in each
# OTHER paper (directional candidates). No API call -- pure lexical
# similarity.
# Output: tag_matches.json
python3 match_tags.py

# Step 6 -- script: prune_bidirectional.py
# Prune to only bidirectional (mutual top-3) matches. No API call.
# Output: bidirectional_matches.json
python3 prune_bidirectional.py

# Step 7 -- script: group_matches.py
# Group linked quotes into connected components (transitive), filtered to
# a per-granularity similarity threshold before grouping. No API call.
# Output: quote_groups.json (sections + paragraphs groups; no
# overarching_question yet -- the epoch track below computes its own)
python3 group_matches.py
```

Steps 2 and 3 are the only ones above that call the Claude API. Both cache their
responses to disk under `$SME_OUTPUT_DIR/_cache/` (`hybrid_section_tags/` and
`hybrid_paragraph_tags/`, keyed by `paper_id__section_id`) and check the cache before
calling again — safe to re-run after a crash or after running out of credit.

**Cache-staleness warning:** because the cache key is `paper_id__section_id`, not the
actual paragraph content, re-running Step 1 against *different* stage-0 data (a new
extraction, a different set of paragraphs) for a paper whose section ids stay the
same will make Steps 2–3 silently reuse stale cached tags — in the worst case,
returning tags for paragraph ids that no longer exist, leaving those paragraphs with
an empty tag with no error raised. If you rebuild a paper's Step 1 output from new
source data, delete its cache entries under `_cache/hybrid_section_tags/` and
`_cache/hybrid_paragraph_tags/` first (or the whole `_cache/` directory, to be safe).

### Output files

| File | Produced by | Contents |
|---|---|---|
| `<paper_id>.json` | build_hybrid_from_pseudo_sections.py, tag_hybrid_sections.py, tag_hybrid_paragraphs.py, filter_references.py | one paper's sections + paragraphs, each with `id`, `title`, `tag`, `text`, `prev_relation`, `next_relation`; paragraphs also have `section_id` (their parent section's id). `prev_relation`/`next_relation` are always `""` in this track. |
| `manifest.json` | build_hybrid_from_pseudo_sections.py | `[{paper_id, title, file}, ...]` for every paper in `$SME_OUTPUT_DIR` |
| `tag_matches.json` | match_tags.py | directional top-3 tag candidates per unit, per granularity |
| `bidirectional_matches.json` | prune_bidirectional.py | mutual-match links only, per granularity |
| `quote_groups.json` | group_matches.py | connected-component groups of linked quotes (sections + paragraphs) |

## Epoch-based refinement

`refine_with_epoch_matrix1_reassign.py` only needs `quote_groups.json`'s paragraph
groups (the bidirectional-link connected components) — it recomputes its own
starting question from scratch (see "Pre-epoch" below) rather than relying on any
precomputed `overarching_question`. It writes its own output directory,
`$SME_OUTPUT_DIR/epoch_matrix1_reassign_refinement/`, without touching anything
written by Steps 1–7 above.

```bash
# Pre-epoch -- script: refine_with_epoch_matrix1_reassign.py
# For each of Step 7's connected-component paragraph groups, randomly pick
# ONE paragraph per paper (not all members), then ask Claude for an
# overarching_question from just those representatives -- each
# representative's own tag, its actual text, and its parent section's tag
# for context (not that section's full content). The random pick is seeded
# (RANDOM_SEED = 42) so re-runs select the same representatives and don't
# invalidate the per-group_id response cache.
# Output: epoch_matrix1_reassign_refinement/initial_groups.json

# Each epoch (repeated $SME_N_EPOCHS times -- set this to 3 to get to the
# epoch 3 results; defaults to 5 if unset):
#
# 1. Matrix 1 -- one Claude call per paragraph, ranking every current
#    candidate group's question best -> worst for that paragraph.
# 2. E-step (reassign) -- every paragraph is assigned directly to its
#    Matrix 1 #1-ranked group_id. No additional Claude call. Tallies how
#    many paragraphs changed group vs. the previous epoch. Any candidate
#    group left with zero members is dropped.
# 3. Matrix 2 -- one Claude call per (surviving question, paper) pair,
#    ranking that paper's own paragraphs best -> worst for the question.
# 4. M-step (re-summarize) -- for each surviving group, each paper's
#    Matrix-2 #1-ranked paragraph becomes that paper's representative (up
#    to 3 per group); summarize_group() recomputes the overarching_question
#    from just those representatives, discarding the old one.
#
# Output: epoch_matrix1_reassign_refinement/epoch<N>/matrix1.json,
#         epoch_matrix1_reassign_refinement/epoch<N>/estep.json,
#         epoch_matrix1_reassign_refinement/epoch<N>/matrix2.json,
#         epoch_matrix1_reassign_refinement/epoch<N>/mstep.json
#         for N = 1..$SME_N_EPOCHS
SME_N_EPOCHS=3 python3 refine_with_epoch_matrix1_reassign.py

# script: compute_epoch_group_balance.py [run_dir_name]
# For each epoch<N>/estep.json in a given run directory, counts how many
# papers have at least one paragraph in each surviving group -- balance =
# (papers represented) / (total papers), each paper counting at most once.
# No API call. The number of epochs is auto-detected from however many
# epoch<N> subdirectories exist. run_dir_name defaults to
# epoch_matrix_refinement -- pass epoch_matrix1_reassign_refinement to
# match the run above.
# Output: epoch<N>/group_balance.json for every available epoch
python3 compute_epoch_group_balance.py epoch_matrix1_reassign_refinement
```

Every Claude call above is cached per item under
`$SME_OUTPUT_DIR/_cache/epoch_matrix1_reassign_refinement/` — same staleness caveat as
Steps 2–3 above applies here too (the pre-epoch/epoch caches are keyed by group_id and
paragraph unit_id, both of which can silently point at different content after a
Step 1 rebuild). Delete the relevant `_cache/epoch_matrix1_reassign_refinement/`
subdirectory before re-running against rebuilt data.

### Epoch output files

| File | Produced by | Contents |
|---|---|---|
| `initial_groups.json` | refine_with_epoch_matrix1_reassign.py | pre-epoch groups: `{group_id, overarching_question, members, representative_members}` |
| `epoch<N>/matrix1.json` | refine_with_epoch_matrix1_reassign.py | `{"paper_id:unit_id": [group_id, ...]}` — that epoch's paragraph→question ranking |
| `epoch<N>/estep.json` | refine_with_epoch_matrix1_reassign.py | `{meta: {reassigned, total_assigned, dropped_groups}, candidates_used, groups: [{group_id, members}]}` |
| `epoch<N>/matrix2.json` | refine_with_epoch_matrix1_reassign.py | `{group_id: {paper_id: [unit_id, ...]}}` — that epoch's question→paragraph ranking |
| `epoch<N>/mstep.json` | refine_with_epoch_matrix1_reassign.py | `{groups: [{group_id, overarching_question, representative_members}]}` |
| `epoch<N>/group_balance.json` | compute_epoch_group_balance.py | for each group, its balance score (% of papers represented) — sorted highest first |

## Visualizing the results

```bash
python3 -m http.server 8743 --directory SME/pipeline
```

then open `http://localhost:8743/viz/tag_matches_viewer.html`. Edit the `base` const
near the top of `loadAll()` in that file to point at your `$SME_OUTPUT_DIR`
(relative to `viz/`, e.g. `"../output/my_paper_set/"`) before loading — there's no
UI or query-param control for this, it's a one-line edit. The **Epoch Groups** and
**Paper Map** tabs both read `epoch_matrix1_reassign_refinement/epoch3/` specifically
(`currentEpochPhase` is hardcoded near the top of the `<script>` block — change it to
`"epoch1"`/`"epoch2"`/etc. and reload if you want a different epoch instead; there's
no in-app toggle).

## Tuning knobs

- `TOP_K = 3` in `match_tags.py` — how many candidate matches to keep per unit
  before bidirectional pruning.
- `SIMILARITY_THRESHOLDS` in `group_matches.py` (`0.33` sections, `0.45` paragraphs)
  — links below this score are dropped *before* connected-components grouping, to
  keep groups from collapsing into one giant blob on a dense link graph. Raise these
  if groups still look too broad; lower them if you're getting too many
  tiny/singleton groups.
- Similarity itself (`text_similarity()` in `align_graphs.py`) is a 50/50 blend of
  Jaccard word-overlap and character-level sequence similarity — cheap and
  dependency-free, no embeddings or extra API calls involved.
- `SME_N_EPOCHS` (env var, defaults to `5`) — how many epochs
  `refine_with_epoch_matrix1_reassign.py` runs; set to `3` to reproduce the epoch 3
  results this README walks through.
