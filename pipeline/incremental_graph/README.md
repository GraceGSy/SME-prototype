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

Each paper file may use the existing extracted-sections format:

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

## Kanishk's First Draft of the Psuedocode

This is the rough algorithm I implemented.

For each paper, in insertion order:
1. Generate one concise question for every section using its full text.
2. Compare every new section with the existing question groups:
   - The section selects its best group or none.
   - Each existing group selects its best new section or none.
   - Save every selection as provenance.
3. Update the graph:
   - If a section and group select each other, add the section to that group.
   - If only one selects the other, create a new node for the section and add a directed alignable difference edge.
   - If neither selects the other, create an isolated node for the section.
4. Reclassify every node deterministically:
   - Common structure: bidirectional matches represented in a majority of eligible papers.
   - Alignable difference: not a majority bidirectional match, but has multiple papers or is a unidirectional match.
   - Non-alignable difference: everything else, which is typically singletons that are unconnected.
5. Generate a concise question describing everything contained in each node.
6. Repeat the same process for paragraphs, but only compare paragraphs belonging to sections within the same section node.
7. Save the graph, classifications, matches, provenance, and replay events.

# Elena notes:

1. Revise extraction skills to only extract non-appendix section & paragraph content (no question generation) into JSON with format specified above; document invocation here and archive in /skills folder
2. (Pyfile that calls Claude API) Decorate sections (or paragraphs) with questions; add to existing JSON. The following revised instructions can be used (but this can be tweaked):

```
Identify the function this section serves in the paper's argument — not its topic, not
a summary of its content, not a restatement of its title. Ask: what job is this section
doing? What does the reader need answered here before moving to the next part of the
paper?

Write the question so it names enough context to stand alone — avoid bare "this"/"here"
that only resolve if the reader already has the section's text open.

The question must not answer itself (no parenthetical or clause that gives the answer
away), must not mention section numbering or labels, and must not assert an outcome or
claim the section's text doesn't actually establish.

Return exactly one question, for every section with real text — including short ones
(Acknowledgments, Preface). Never return null, "N/A", or a generic placeholder for a
section that has content.

Section text:
{text}
```

Ideally this takes a section of paragraphs or a single paragraph so it's reused. To do this, it would likely need a new prompts section.
3. Instantiate empty graph for collecting section groups; add each section of first paper to graph as a new node.
4. Direction 1: Iterate over each section in next paper; ask which node it matches in the graph best or none.
5. Direction 2: Iterate over each node in the graph; ask which section it matches in the next paepr best or none.
6. Update the graph with an entire paper's sections:
  - If a section and node select each other, add the section to that node.
  - If only one selects the other, create a new node for the section and add a directed alignable difference edge. (Edge points from the selecting node/section to selected node/section.)
  - If neither selects the other, create an isolated node for the section.
7. Spit out the graph and/or update node metadata. Iterate over nodes in graph:
  - if # of sections in node >= 50% # of papers (Implicit constraint: 1 section per paper per node) then it's a 'common structure' node.
  - elif node is alignable difference node if it has any directed edges to any other common structure node
  - otherwise: it's a non-alignable difference node, e.g., a section no other paper has or a group of sections that are in a minority of papers
  Consider TODO: add directed edges based on relative position w.r.t. other nodes (requires capturing node order messy...) which could turn non-alignable nodes (on the basis of role) to alignable differences (on the basis of position)
8. Re-run question generation on each node
9. Repeat the same process for paragraphs, but only compare paragraphs belonging to sections within the same section node.
10. Save the graph