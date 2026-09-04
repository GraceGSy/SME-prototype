# Incremental node graph

This package builds the order-dependent section/subsection and paragraph graph.
Python owns identity, insertion order, candidate scope, reciprocity, mutation,
provenance, replay, and exports. Configured Claude Skills make only question and
matching judgments.

## Input

An ordered YAML manifest points to documents in the sole nested contract in
[`DATA_CONTRACTS.md`](../../DATA_CONTRACTS.md):

```yaml
schema_version: 1
papers:
  - paper_id: paper_a
    title: Paper A
    file: paper_a.json
```

The shared loader derives section, subsection, and paragraph IDs from source
positions. It accepts no flat, pseudo-section, or viewer JSON variants.

The manifest may set `max_granularity`:

- `section` is the default. Only top-level sections become structural nodes;
  explicit subsection paragraphs remain ordered within their parent section.
- `subsection` preserves both section and subsection structural nodes.
- `paragraph` requires one top-level section per document. The runner places
  those sections in one deterministic shared root, skips every structural
  judgment, and starts with paragraph questions and matching.

## Ordered algorithm

For each paper in manifest order, the structural phase:

1. Reuses or generates one question for every section and subsection.
2. Matches each new unit to one existing node or none.
3. Separately matches each existing node to one new unit or none.
4. Adds reciprocal units to existing nodes and creates singleton nodes for all
   other units.
5. Adds deterministic section-to-subsection `contains` edges.
6. Reuses a singleton member question or generates a shared question for every
   multi-member node.

After all papers, one structural rerepresentation pass lets singleton nodes
select eligible established nodes. Accepted selections merge node membership;
same-paper conflicts remain provenance. No projected match edge is created.

The paragraph-question stage sends every missing paragraph in its own
schema-validated Skill call with a 256-token output ceiling. It sends the focus
paragraph, its immediate neighbors, and document and parent-section metadata,
not the full parent text. Multi-member node questions also use one bounded call
per node. Paragraph matching remains batched with one call per direction inside
each exact finalized structural node. Reciprocal matches form node cores. A one-way paragraph may
join only when it is immediately adjacent to a reciprocal anchor; all other
paragraphs remain singletons. Unabsorbed projected selections remain provenance
and never become edges.

The matching Skill returns `target_id` and `basis` for each source. The question
Skill returns `question_this_text_answers`. Questions remain metadata, not
identity.

## Configure

[`configs/incremental-v1.yaml`](configs/incremental-v1.yaml) lists every stage in
execution order and names its Skill, prompt template, context policy, and
handler. Its model block also fixes low-effort, non-thinking Skill-call limits,
including input-token and prompt-size ceilings. Every judgment is one Messages
API request; `pause_turn` fails rather than replaying model output in another
request. The same block caps cumulative API responses and tokens per process;
its higher response allowance intentionally accommodates per-question calls for
the five-story corpus. Prompt and context files are adjacent under `prompts/`
and `contexts/`.
The stable system and prompt instructions precede five-minute cache breakpoints;
per-judgment context follows them.
Changing those files changes judgment behavior without changing graph rules.

## Commands

Validate canonical inputs without model calls or writes:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/hci-five-paper/manifest.yaml
```

Run an immutable revision:

```powershell
$env:ANTHROPIC_API_KEY = "your-key"
python -m pipeline.incremental_graph.cli run `
  datasets/hci-five-paper/manifest.yaml `
  runs/hci-five-paper
```

Retry one paper-stage pair by replaying the same ordered corpus:

```powershell
python -m pipeline.incremental_graph.cli retry `
  runs/hci-five-paper `
  --paper-index 2 `
  --stage section_matching
```

Each attempt is content-addressed by Skill, prompt, context, schema, model, and
input evidence. Cached attempts bypass outbound APIs unless the selected stage
is forced. The configured `max_tokens` value is used as written; the adapter no
longer silently raises every graph judgment to a 4,096-token minimum. This is an
output ceiling, not forced consumption; each attempt records actual input,
cache, and output usage from Claude under `raw_response.usage`.

## Outputs

Successful revisions are immutable under `<run>/revisions/revision-NNNN/`.
They include stage checkpoints, complete attempt records, append-only graph
events, correspondences, and one `dataset/` viewer projection. `run.json` moves
to the new revision only after success.

Viewer packaging accepts only that projection's `final_snapshot.json` contract.
`graph-replay.json` is optional and controls whether Graph Replay appears. The
Paper Map and Question Groups tabs remain the two core UI views.

The current implementation does not yet classify nodes as `common_structure`,
`alignable_difference`, or `non_alignable_difference`; that deterministic
traversal remains a separate future graph rule.
