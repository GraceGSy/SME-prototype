# Question Atlas refinement prototype

This repository turns academic papers into question-tagged sections and paragraphs,
finds initial cross-paper correspondences, and then runs an inspectable sequence of
Claude-backed refinement epochs. The active implementation is a question-mapping
experiment inspired by structure mapping; it is not yet a literal implementation of
Gentner's Structure-Mapping Engine.

## Setup

```powershell
cd pipeline
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Set `ANTHROPIC_API_KEY` in the environment or in a `.env` file anywhere from the
repository directory up through its ancestors, or enter a key for one run in the
local run menu. A run-menu key is passed only to the child analysis process, is
cleared from the form after launch, and is never written to run state or artifacts.

## Run the application

```powershell
cd pipeline
python analysis_server.py
```

The server opens `http://127.0.0.1:8743/` automatically and restores the newest
completed saved run. Pass `--no-browser` to suppress automatic opening. Do not use
`python -m http.server`: the viewer depends on the local API to load saved runs and
start Claude-backed analyses securely. Analysis jobs use `pipeline/.venv` when it is
available, even if the server was launched with global Python.

The UI lets a user:

- select any combination of reusable library PDFs and newly uploaded PDFs;
- configure the model, epoch count, context/chunk sizes, assignment batch size,
  candidate count, every grouping/merge/stability threshold, paragraph-labeling
  context, and assignment evidence;
- start the complete analysis and follow its stage log;
- inspect the initial section and paragraph comparisons;
- visually replay initial groups, the initial supergroup merge, and every immutable
  epoch on one pan-and-zoom canvas, with stable origin labels such as `0-1` for an
  initial group and `2-1` for the first group created in epoch 2;
- switch between all Claude-selected memberships and each paragraph's strongest
  deterministic ranking;
- inspect newly assigned and orphaned paragraphs with complete provenance;
- click any question marked as revised to compare its previous and revised wording,
  lexical similarity, and the newly assigned paragraphs considered in that revision;
- read the complete papers side by side in a synchronized-scroll `Paper Map`, where
  every paragraph is colored by its best-one group at the selected replay step,
  groups can be pinned for cross-paper scanning, and a wordless skeleton shows
  paragraph-length color bands as they change across merges and assignments;
- show every unmatched or unassigned paragraph rather than silently pruning it.

Each run is stored under `pipeline/output/runs/<run_id>/`. The most recent completed
run is reopened when the server restarts, and any completed run can be reopened from
the run menu. Every run stores copies of its input PDFs, their hashes, all settings,
the exact prompt templates/tool schemas, runtime versions, Git/source-file hashes,
and the generated artifacts. Generated output is gitignored.

The run menu also supports controlled ablations. `fixed paragraph corpus` copies
verified paragraph ids, boundaries, text, and relations from a saved run before
rerunning downstream stages. It can preserve the questions, relabel each fixed
paragraph with one complete section as context, or relabel it with one complete paper
as context. `fixed pre-epoch state` additionally reuses all initial matching and group
artifacts so an assignment-prompt treatment changes no upstream state. Reuse is
allowed only when paper ids and PDF SHA-256 hashes match exactly; the source run,
scope, copied-artifact hash, and paragraph-id hash are recorded.

## Active pipeline

The server runs these stages in order:

1. `extract_sections.py` extracts high-level section headings and complete question
   tags with one Claude call per paper. The default sends the complete extracted
   paper; the run menu can impose an explicit character limit when needed.
2. `attach_section_text.py` deterministically slices complete source section text
   between the extracted headings.
3. `extract_fine_grained.py` sends each complete section to Claude. It identifies
   paragraph boundaries, a complete question per paragraph, adjacent discourse
   relations, and a stable `parent_section_id`. Oversized sections are split at
   deterministic text boundaries using the configured chunk size; they are never
   silently collapsed into one fallback paragraph.
   In the optional context treatments, `relabel_section_context.py` gives Claude the
   fixed paragraphs from one complete section per request, while
   `relabel_full_paper.py` gives it every fixed paragraph in one complete paper
   context. Both change only paragraph questions. Text, ids, order, section
   membership, and relations remain fixed, with every old/new question recorded in
   `paragraph_context_relabel.json`.
4. `match_tags.py` finds the configured number of question-tag matches in every other
   paper by a deterministic lexical score. `prune_bidirectional.py` keeps reciprocal candidates.
5. `group_matches.py` forms thresholded connected components.
6. `summarize_groups.py` gives Claude the **complete source text and provenance of
   every paragraph** in each group, rather than only its question tags.
7. `match_groups.py` asks Claude for directional conceptual equivalence judgments
   between group questions. `prune_group_bidirectional.py` keeps only reciprocal
   judgments, and `group_groups.py` applies the deterministic lexical threshold.
   Every nonmerged group remains as a singleton. `summarize_super_groups.py`
   synthesizes actual merges from all complete paragraphs and copies singleton
   questions without another model call.
8. `refine_epochs.py` performs zero or more alternating refinement epochs.

## Epoch semantics

Epoch 0 records every initial paragraph group and every paragraph outside those
groups. Every later epoch performs these monotonic substeps:

1. Claude judges directional conceptual equivalence between the current group
   questions. A merge edge exists only when Claude selects both directions and the
   deterministic lexical score passes the configured threshold. Connected groups
   merge; all other groups carry forward unchanged.
2. Claude receives only the currently unassigned complete paragraphs, current group
   questions, and source-section provenance. It returns zero, one, or many groups for
   every supplied paragraph. The prompt explicitly prohibits force-fitting. An
   evidence treatment can accompany each question with either all assigned
   paragraphs or a deterministic TF-IDF medoid sample, selected per paper with exact
   paragraph-id provenance and explicit user-configured limits.
3. A corpus-local TF-IDF cosine score is computed for every paragraph/question pair.
   Same-section cohesion counts only peers from the exact section in the same source
   paper. Claude-selected memberships are ranked by
   `(1 - section_weight) * TF-IDF + section_weight * cohesion`; the UI can show all
   selected memberships or rank one only.
4. Only groups that gained paragraphs are reconsidered. Claude receives every complete
   paragraph in that group and either preserves or revises its complete question.
5. The run stops at the configured maximum or when there are no merges, no new
   assignments, and no material question revisions.

Membership is sticky: an assigned paragraph is never removed or reconsidered by a
later assignment step. Groups can merge but never split, retire, or disappear, so
assigned-paragraph coverage can only increase and group count can only decrease or
stay constant.

The lexical merge score is deterministic:
`0.5 * token-set Jaccard + 0.5 * SequenceMatcher ratio`, using lowercased question
text. It is a gate after reciprocal Claude judgment, not a model-reported confidence.

`epoch_history.json` records configuration, full group lineage, Claude assignment
decisions, deterministic component scores, source membership, newly added paragraphs,
synthesis prompt hashes, model names, and stopping evidence. Source paragraph text
remains in each paper JSON and is joined by stable `paper_id`/`unit_id` provenance.
Every substep also stores `unassigned_paragraphs`. The viewer exposes these by paper
without changing their total when `changed only` is selected. Initial section,
paragraph, and group views likewise expose unmatched units behind the
`show unassigned` control.

## Important interpretation

Claude makes conceptual merge and membership judgments. Deterministic lexical
similarity gates reciprocal merge judgments; deterministic TF-IDF and section scores
rank Claude-selected memberships. None of these values are calibrated probabilities.
A many-to-many display is the complete model output, while "best one" is only a
viewer filter over those Claude-selected memberships.

Initial paragraph matching is still lexical and structurally shallow. Epochs add
iterative question merging, orphan assignment, and non-splitting lineage, but they do
not yet construct or align Gentner-style within-paper relational trees.

## Tests

```powershell
cd pipeline
.venv\Scripts\python -m unittest discover -s tests -v
```

The focused suite checks full-paragraph prompt inclusion, the two-gate merge contract,
deterministic scoring, same-section weighting, singleton survival, append-only
membership, and lossless batching.

Regenerate the quantitative audit from every saved operational run with:

```powershell
cd pipeline
.venv\Scripts\python build_run_analysis_report.py
```

The command writes `output/pdf/question_atlas_run_analysis.pdf` at the repository
root and includes failed attempts explicitly while using only completed runs for
final treatment comparisons.

## Earlier implementations

`schema.py`, `extract_graph.py`, `align_graphs.py`, `align_trace.py`, `cli.py`,
`viz/index.html`, and `viz/align_viewer.html` contain an older entity/proposition SME
experiment. The active pipeline reuses only `align_graphs.text_similarity()` for
legacy lexical matching and stability reporting.
