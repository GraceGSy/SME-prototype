# Structural cross-paper matching pipeline

Extracts a hierarchical structure (sections → paragraphs) from a set of academic
papers, tags each unit with a free-text question describing its role, cross-matches
those tags between papers, groups the resulting links, and computes two ranking
matrices comparing every paragraph against the resulting set of candidate research
questions.

This README covers the pipeline from raw PDFs through generating those two ranking
matrices, plus the iterative paragraph-group refinement and group-balance metric
built on top of them, and a separate epoch-based refinement track built directly on
the bidirectional-link groups. (Further, more exploratory steps beyond that are in
the codebase too — balanced MILP reassignment, earlier epoch-refinement variants,
etc. — not documented here.)

Loosely inspired by Gentner's Structure-Mapping Engine (structural alignment between
papers), but implemented as a much simpler tag-matching pipeline rather than a full
entity/proposition graph aligner. (An earlier, more literal SME-style attempt lives in
`schema.py` / `extract_graph.py` / `align_graphs.py` / `align_trace.py` / `cli.py` and
`viz/index.html` / `viz/align_viewer.html` — **not used by the current pipeline**,
kept only for reference.)

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

Optionally override the model used for extraction/summarization calls (defaults to
`claude-sonnet-5`):

```bash
export SME_EXTRACT_MODEL=claude-sonnet-5
```

## Input papers

The pipeline expects PDFs in `SME/papers/`. Three example papers are checked in
there already:

```
SME/papers/examplore_chi18.pdf
SME/papers/mesotext.pdf
SME/papers/paralib_uist22.pdf
```

To use your own papers, drop PDFs into `SME/papers/` and either edit each script's
`DEFAULT_PAPERS` list or pass paths explicitly, e.g. `python3 extract_sections.py
my_paper.pdf`. The paper's filename stem (minus `.pdf`) becomes its `paper_id`
throughout the pipeline.

## Running the pipeline

Run these **in order** from `SME/pipeline/`. Each step reads the previous step's
output from `output/sections/`, so later steps will silently do nothing useful (or
crash) if run out of order. Every output file below lives in `output/sections/`.

```bash
# Step 1 -- script: extract_sections.py
# Extract each paper's high-level sections + a free-text role tag per section.
# One Claude call per paper.
# Output: <paper_id>.json (sections only, text not yet filled in) + manifest.json
python3 extract_sections.py

# Step 2 -- script: attach_section_text.py
# Fill in each section's actual text by slicing the raw PDF text locally.
# No API call. MUST run before step 3, and MUST be re-run any time step 1
# is re-run (extract_sections.py resets section text to "").
# Output: <paper_id>.json (sections now have real text)
python3 attach_section_text.py

# Step 3 -- script: extract_fine_grained.py
# Extract paragraphs within each section, each with its own free-text tag,
# prev/next discourse-relation tags, and the id of its parent section
# (section_id). One Claude call per section.
# Output: <paper_id>.json (paragraphs added)
python3 extract_fine_grained.py

# Step 4 -- script: match_tags.py
# For every section/paragraph, find its top-3 most similar tags in each
# OTHER paper (directional candidates). No API call -- pure lexical
# similarity.
# Output: tag_matches.json
python3 match_tags.py

# Step 5 -- script: prune_bidirectional.py
# Prune to only bidirectional (mutual top-3) matches. No API call.
# Output: bidirectional_matches.json
python3 prune_bidirectional.py

# Step 6 -- script: group_matches.py
# Group linked quotes into connected components (transitive), filtered to
# a per-granularity similarity threshold before grouping. No API call.
# Output: quote_groups.json (sections + paragraphs groups; no
# overarching_question yet)
python3 group_matches.py

# Step 7 -- script: summarize_groups.py
# For each paragraph group, ask Claude what overarching research question
# unifies its members -- given each member's own question, its actual
# paragraph text, AND its parent section's question (not the section's
# content). One Claude call per group.
# Output: quote_groups.json, updated in place (paragraph groups now have
# an overarching_question)
python3 summarize_groups.py

# Step 8 -- script: refine_paragraph_groups.py
# Iteratively refines quote_groups.json's paragraph groups over
# N_ITERATIONS = 5 rounds (quote_groups.json itself is left untouched).
# Each round: (1) reassign -- ask Claude, for EVERY paragraph in EVERY
# paper (not just already-grouped ones), which CURRENT group's
# overarching_question it fits best; one Claude call per paragraph,
# returning a single group_id directly rather than a score per candidate,
# to keep output small and cheap. (2) re-summarize -- recompute each
# surviving group's overarching_question from its new membership (reusing
# summarize_group() from step 7, same enriched prompt), discarding the old
# question. Groups that lose every member are dropped. ~236 paragraphs x 5
# iterations ~= 1,180 Claude calls on the example papers, but each call's
# output is tiny (a single group_id).
# Output: paragraph_groups_iter<N>.json for N = 1..5 (one full snapshot
#         per round), paragraph_groups_refined.json (the final iteration's
#         result)
python3 refine_paragraph_groups.py

# Step 9 -- script: compute_ranking_matrices.py
# Matrix 1: for every paragraph, rank all of step 7's candidate questions
# best -> worst. Matrix 2: for every (question, paper) pair, rank that
# paper's own paragraphs best -> worst for that question. One Claude call
# per paragraph (Matrix 1) plus one per question-paper pair (Matrix 2);
# the constant part of each prompt (the candidate list / the paper's
# paragraph list) is cached in the system prompt so it's only paid for
# once per batch, not once per call. Only depends on step 7's output, not
# on step 8.
# Output: paragraph_question_ranking.json (Matrix 1),
#         question_paragraph_ranking.json (Matrix 2)
python3 compute_ranking_matrices.py

# Step 10 -- script: compute_group_balance.py
# For every saved paragraph_groups_iter<N>.json snapshot, counts how many
# papers have at least one paragraph assigned to each group's QI-Prime.
# Each paper counts at most once regardless of how many of its paragraphs
# are assigned. Balance is that paper count divided by the total number of
# papers (100% = every paper has at least one paragraph assigned to the
# QI-Prime). No API call -- pure local computation over saved assignments.
# Groups are sorted by this metric, highest first within each iteration.
# Output: group_balance_iter<N>.json for every available iteration
python3 compute_group_balance.py
```

Steps 1, 3, 7, 8, and 9 are the only ones that call the Claude API (step 10 is pure
local computation). All of them cache their responses to disk (per
paper/section/group/paragraph id, under `output/sections/_cache/`) and check the
cache before calling again — safe to re-run a script after a crash or after running
out of credit; already-completed items are skipped. To force a full re-run of a
step, delete its cache subdirectory first (and remember step 2's note above about
re-running `attach_section_text.py` after step 1).

Anthropic prompt caching (`cache_control: ephemeral` on the system prompt) is also
used within steps 1/3/7/8/9 so that repeated calls in one run only pay full price
for the first call.

### Output files

| File | Produced by | Contents |
|---|---|---|
| `<paper_id>.json` | extract_sections.py, attach_section_text.py, extract_fine_grained.py | one paper's sections + paragraphs, each with `id`, `title`, `tag`, `text`, `prev_relation`, `next_relation`; paragraphs also have `section_id` (their parent section's id) |
| `manifest.json` | extract_sections.py | `[{paper_id, title, file}, ...]` for every paper in `output/sections/` |
| `tag_matches.json` | match_tags.py | directional top-3 tag candidates per unit, per granularity |
| `bidirectional_matches.json` | prune_bidirectional.py | mutual-match links only, per granularity |
| `quote_groups.json` | group_matches.py, summarize_groups.py | connected-component groups of linked quotes (sections + paragraphs); paragraph groups also get an `overarching_question` |
| `paragraph_groups_iter<N>.json` | refine_paragraph_groups.py | snapshot of `{meta: {reassigned, total_assigned}, groups: [...]}` after refinement round N (N = 1..5) |
| `paragraph_groups_refined.json` | refine_paragraph_groups.py | final refined paragraph groups after all 5 rounds |
| `paragraph_question_ranking.json` (Matrix 1) | compute_ranking_matrices.py | `{"paper_id:unit_id": [group_id, group_id, ...]}` — for each paragraph, its own best→worst ranking of all candidate questions |
| `question_paragraph_ranking.json` (Matrix 2) | compute_ranking_matrices.py | `{group_id: {paper_id: [unit_id, unit_id, ...]}}` — for each question, that one paper's own paragraphs ranked best→worst for it |
| `group_balance_iter<N>.json` | compute_group_balance.py | for each group in iteration N, its balance score (% of papers with at least one paragraph assigned to that group's QI-Prime) — sorted highest first |

`viz/tag_matches_viewer.html` presents the paragraph groups in `quote_groups.json`
as **Iteration 0 · QI-Primes**, followed by refinement iterations 1–5. The Groups,
Paper Map, and Skeleton views share this iteration selector; numeric balance is
shown for every refinement iteration.

### Swappable viewer datasets

The user-study viewer loads one normalized static package from `/data`; it does
not contain a paper-set-specific path. `manifest.json` controls paper order, and
the package descriptor selects the available epochs and defaults to the last
one. A compatible source directory contains the ordered manifest, its listed
paper JSON files, `bidirectional_matches.json`, `quote_groups.json`, and the
`epoch_matrix1_reassign_refinement/` outputs.

Build a standalone site from any compatible output directory without changing
the frontend:

```bash
python pipeline/viewer_dataset.py \
  pipeline/output/sections_skills_hybrid_core \
  tmp/question-atlas-hci \
  --dataset-id hci --label "HCI SME Viewer"

python -m http.server 8743 --directory tmp/question-atlas-hci/public
```

The `--label` value sets the browser-tab and visible viewer title. The packager
validates paper/unit references and epoch completeness, copies only
runtime files (not PDFs, matrices, or model caches), and writes the generated
`data/dataset.json` contract used by the unchanged viewer.

### Final snapshots from nested question mappings

The nested-mapping adapter builds a final-snapshot dataset from an ordered
manifest, one `*-sections-with-paragraphs-and-questions-no-appendices*.json`
file per paper, and a nested paragraph-question mapping. Exact question text
defines a group; questions represented in two or more papers are shared, while
one-paper questions are singletons. Paragraphs without an explicit paragraph
question or mapping remain visible as unassigned rather than inheriting their
section question.

```bash
python pipeline/build_nested_snapshot_dataset.py \
  path/to/all-matched-paragraph-structure-nested.json \
  path/to/sme2-paper-json-directory \
  pipeline/output/sections_skills_hybrid \
  tmp/hci-sme2-snapshot
```

### Counterbalanced two-phase study

Package two compatible datasets behind one participant-ID gate:

```bash
python pipeline/build_counterbalanced_study.py \
  pipeline/output/sections_skills_hybrid_papers3_core \
  pipeline/output/sections_stage0_snapshot_viz2_clean2 \
  tmp/question-atlas-viz-study

python -m http.server 8743 --directory tmp/question-atlas-viz-study/public
```

Participant IDs beginning with `1` receive SME 1 then SME 2; IDs beginning
with `2` receive the reverse order. The current phase is kept in browser
session storage across refreshes, and switching phases loads a fresh viewer.
Opening the site with `?reset=1` clears the current participant session.

Add an HCI pair to the same deployment without changing the frontend:

```bash
python pipeline/build_counterbalanced_study.py \
  pipeline/output/sections_skills_hybrid_papers3_core \
  pipeline/output/sections_stage0_snapshot_viz2_clean2 \
  tmp/question-atlas-study \
  --hci-sme1-dir pipeline/output/sections_skills_hybrid_core \
  --hci-sme2-dir tmp/hci-sme2-snapshot \
  --title "SME Study"
```

With the HCI pair present, participant prefix `3` receives HCI SME 1 then HCI
SME 2, and prefix `4` receives the reverse order. Prefixes `1` and `2` retain
the Viz orders above.

`output/sections/_cache/` holds the raw per-item Claude responses (safe to delete to
force a re-run; checked into git alongside everything else so collaborators can skip
re-running expensive steps entirely).

### Visualizing the matrices

```bash
python3 -m http.server 8743 --directory SME/pipeline
```

then open `http://localhost:8743/viz/ranking_heatmap.html` — one row per paragraph
(grouped and color-coded by paper), one column per question, three views side by
side: Matrix 1 alone, Matrix 2 alone, and a combined view (Matrix 1 = fill color,
Matrix 2 = outline color, same scale). Hover any cell for the exact question,
paragraph, and rank.

## Epoch-based refinement

`refine_with_epoch_matrix1_reassign.py` is a separate refinement track, an
alternative to step 8's `refine_paragraph_groups.py`. It only depends on step 6's
`quote_groups.json` (the bidirectional-link connected components) — it does NOT
need step 7's precomputed `overarching_question`, or steps 8–10's output, since it
recomputes its own starting question from scratch (see "Pre-epoch" below). It
writes its own output directory, `output/sections/epoch_matrix1_reassign_refinement/`,
without touching anything from the main pipeline above.

```bash
# Pre-epoch -- script: refine_with_epoch_matrix1_reassign.py
# For each of step 6's connected-component paragraph groups, randomly pick
# ONE paragraph per paper (not all members), then ask Claude for an
# overarching_question from just those representatives (reusing
# summarize_group()'s enriched prompt from step 7). The random pick is
# seeded (RANDOM_SEED = 42) so re-runs select the same representatives and
# don't invalidate the per-group_id response cache.
# Output: epoch_matrix1_reassign_refinement/initial_groups.json

# Each epoch (repeated N_EPOCHS = 5 times):
#
# 1. Matrix 1 -- one Claude call per paragraph (236 total), ranking every
#    current candidate group's question best -> worst for that paragraph.
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
#         for N = 1..5
python3 refine_with_epoch_matrix1_reassign.py

# script: compute_epoch_group_balance.py [run_dir_name]
# For each epoch<N>/estep.json in a given run directory (defaults to
# epoch_matrix_refinement; pass epoch_matrix1_reassign_refinement to match
# the current run above), counts how many papers have at least one
# paragraph in each surviving group -- same formula as step 10's
# compute_group_balance.py (paper count / total papers). No API call. The
# number of epochs is auto-detected from however many epoch<N>
# subdirectories exist, so this works unmodified on any epoch-refinement
# run directory.
# Output: epoch<N>/group_balance.json for every available epoch
python3 compute_epoch_group_balance.py epoch_matrix1_reassign_refinement
```

Every Claude call above is cached per item under
`output/sections/_cache/epoch_matrix1_reassign_refinement/`, distinct from the main
pipeline's cache and from earlier epoch-refinement variants still in the codebase
(`refine_with_epoch_matrices.py`, `refine_with_epoch_random_seed.py` — not
documented here).

### Epoch output files

| File | Produced by | Contents |
|---|---|---|
| `initial_groups.json` | refine_with_epoch_matrix1_reassign.py | pre-epoch groups: `{group_id, overarching_question, members, representative_members}` |
| `epoch<N>/matrix1.json` | refine_with_epoch_matrix1_reassign.py | `{"paper_id:unit_id": [group_id, ...]}` — that epoch's paragraph→question ranking |
| `epoch<N>/estep.json` | refine_with_epoch_matrix1_reassign.py | `{meta: {reassigned, total_assigned, dropped_groups}, candidates_used, groups: [{group_id, members}]}` |
| `epoch<N>/matrix2.json` | refine_with_epoch_matrix1_reassign.py | `{group_id: {paper_id: [unit_id, ...]}}` — that epoch's question→paragraph ranking |
| `epoch<N>/mstep.json` | refine_with_epoch_matrix1_reassign.py | `{groups: [{group_id, overarching_question, representative_members}]}` |
| `epoch<N>/group_balance.json` | compute_epoch_group_balance.py | for each group, its balance score (% of papers represented) — sorted highest first |

`viz/tag_matches_viewer.html`'s **Epoch Groups** tab visualizes this run — Pre-epoch
through Epoch 5, each group card showing its balance badge (sorted highest first)
and one filled square per paragraph, per paper.

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
