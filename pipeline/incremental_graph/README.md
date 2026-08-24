# Incremental Question-Group Graph

This package builds an order-dependent graph from papers that have already been
split into sections and paragraphs. LLM calls make bounded judgments; Python
owns IDs, graph mutations, classification, provenance, replay, and export.

## Graph rules

For every newly added paper, the pipeline generates section questions, runs a
new-section-to-group sweep and a group-to-new-section sweep, and reconciles the
two directions:

| Result | Graph operation |
|---|---|
| Neither direction selects a match | Add an isolated node |
| Exactly one direction selects a match | Add a node and directed `alignable_difference` edge |
| The same new section and existing group select each other | Add the section to that group |

An existing group selecting a section that was reciprocally absorbed into a
different group is saved as `projected_edge_ignored` provenance. It does not
create a group-to-group edge.

After each paper, deterministic Python recomputes node classifications:

```text
common_structure:
    at least two eligible papers exist, and paper coverage is over half

alignable_difference:
    not common, and either coverage is at least two or the node has an edge

non_alignable_difference:
    everything else
```

For sections, all inserted papers are eligible. For paragraphs, only papers
represented in the parent section question group are eligible. The first paper
therefore produces non-alignable nodes rather than making every node common.

Paragraph mapping repeats the same process independently inside each section
question group. Paragraphs are never compared across section groups.

## Install

From the repository root:

```powershell
python -m pip install -r pipeline/requirements.txt
$env:ANTHROPIC_API_KEY = "..."
```

The default provider is Anthropic because the surrounding pipeline already uses
that SDK. Model settings are in
[`configs/incremental-v1.yaml`](configs/incremental-v1.yaml).

## Input

Create an ordered YAML manifest. Insertion order is part of the model.

```yaml
schema_version: 1
papers:
  - paper_id: paper-a
    title: Paper A
    file: papers/paper-a.json
  - paper_id: paper-b
    title: Paper B
    file: papers/paper-b.json
```

Each paper file may use the existing pseudo-section format:

```json
[
  {
    "section_name": "Introduction",
    "section_number": "1",
    "paragraphs": [
      {"paragraph_number": 1, "text": "Complete paragraph text."}
    ]
  }
]
```

The existing canonical `{paper_id, title, sections, paragraphs}` format is also
accepted. IDs are normalized but never derived from generated questions.

## Run and extend

Run all papers in manifest order:

```powershell
python -m pipeline.incremental_graph.cli run `
  path/to/papers.yaml `
  path/to/run-directory
```

To add a paper, append it to the manifest and run the same command again. Every
run creates an immutable `revision-NNNN`; content-addressed LLM results are
reused when prompt, context, model, schema, and source evidence are unchanged.

List the current deterministic categories:

```powershell
python -m pipeline.incremental_graph.cli categories path/to/run-directory
```

Retry a stage for one insertion and replay the ordered corpus:

```powershell
python -m pipeline.incremental_graph.cli retry `
  path/to/run-directory `
  --paper-index 3 `
  --stage section_matching
```

The retry creates a new revision. Prior attempts remain intact. Calls before the
forced stage reuse their cache; later calls reuse the cache only if their full
contexts remain identical.

## Prompts and stages

The pipeline file lists every stage in execution order. Deterministic handlers
are implemented in Python; YAML selects and orders known handlers rather than
embedding business logic.

Prompt bundles live under `prompts/<purpose>/<version>/`:

```text
system.md
user.md
output.schema.json
```

Context profiles live under `contexts/`. They control which top-level evidence
fields are rendered. Optional dotted `exclude` paths support `*` for list items,
such as `candidates.*.generated_question_metadata`. Complete source text is the
default. Overflow fails rather than silently truncating evidence.

To test new wording, copy a prompt version, point a copied pipeline YAML at it,
and use a separate run directory. Do not edit a prompt version after treating it
as an experimental condition.

## Outputs and provenance

Each revision contains:

```text
provenance/attempts.jsonl   Exact prompts, contexts, candidates, model output, and hashes
provenance/events.jsonl     Ordered graph and non-graph events
stages/                     Human-readable output from every configured stage
events.json                 Replay-ready event array
dataset/graph.json          Final NetworkX graph projection
dataset/graph_categories.json
dataset/graph-replay.json   Optional third-view contract
dataset/final_snapshot.json Question Groups and Paper Map contract
summary.json
```

The event and attempt records are authoritative evidence. `graph.json`, category
lists, snapshots, and replay data are deterministic derived artifacts.

Package a successful revision with the existing viewer packager:

```powershell
python pipeline/viewer_dataset.py `
  path/to/run-directory/revisions/revision-0001/dataset `
  path/to/site `
  --dataset-id graph-experiment `
  --label "Graph Experiment"
```

When `graph-replay.json` validates, the viewer shows a third **Graph Replay**
button. If the file is absent or cannot load, the button is not rendered and the
Question Groups and Paper Map views continue normally.

## Why this is not an agent skill

No Codex or Claude agent skill is required. This is a reproducible application
pipeline with explicit inputs, prompts, schemas, API calls, and replay rules. An
agent skill would duplicate those instructions in an agent-specific execution
layer and make provenance harder to compare. A skill may be useful later only as
a thin convenience wrapper that invokes this CLI; it should not contain graph or
matching logic.
