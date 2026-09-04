# SME node graph

This repository contains the retained Structural Mapping Engine work: the
order-dependent node graph, its Claude Skills,
canonical HCI inputs, the Paper Map and Question Groups viewer, Graph Replay,
and the earlier proposition-graph SME.

## Layout

| Path | Purpose |
|---|---|
| `datasets/` | Tracked raw and canonical content corpora for HCI, Sherlock, and legal documents |
| `pipeline/document.py` | The sole nested document contract, validation, IDs, and candidate projection |
| `pipeline/incremental_graph/` | Incremental section and paragraph graph |
| `pipeline/skill_pipeline/` | YAML-driven extraction, question, and pairwise matching pipeline |
| `pipeline/study.py` | One-command document-to-graph-to-viewer study build |
| `pipeline/viewer/` | Paper Map, Question Groups, optional Graph Replay, and canonical snapshot packaging |
| `pipeline/graph_sme/` | Earlier proposition-graph SME retained as a separate implementation |
| `skills/` | Extraction, question, and matching Skills used by the retained pipelines |
| `tests/` | Unit and contract tests for the retained code |

Generated runs, model caches, and packaged sites are intentionally ignored.

See [`DATA_CONTRACTS.md`](DATA_CONTRACTS.md) for the canonical JSON and ID
contracts. See [`PIPELINE_FLOW.md`](PIPELINE_FLOW.md) for the streamlined stage
and outbound-call diagram.

The canonical document pipeline is documented separately in
`pipeline/skill_pipeline/README.md`. It prepares Sherlock/HCI inputs, generates
section and subsection questions, and runs either document-matching Skill. Both
matching modes use the same IDs and output schema.

The study builder sets graph granularity per corpus. Sherlock uses whole-story
paragraph mode, while HCI preserves sections and subsections. Paragraph
questions are generated in one bounded Skill call per paragraph. Paragraph
matching remains batched by direction.

Build a complete corpus graph and viewer without manually creating or handing
off a graph manifest:

```powershell
python -m pipeline.study --dataset sherlock
```

After all four study datasets have completed, `--dataset all` packages them
behind the participant-ID rule `^(SH|HC|LO|LD)[0-9]{3}$`: `SH` routes to
Sherlock, `HC` to HCI, `LO` to legal opinions, and `LD` to legal dissents.

## Setup

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Validate the checked-in papers without making API calls:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/hci-five-paper/manifest.yaml
```

The expected input is five papers, 52 top-level sections, 87 subsections, and
459 paragraphs. Every retained structural unit and paragraph already has a question, so a
graph run reuses those questions rather than paying to generate them again.

## Run the graph

```powershell
$env:ANTHROPIC_API_KEY = "your-key"
python -m pipeline.incremental_graph.cli run `
  datasets/hci-five-paper/manifest.yaml `
  runs/hci-two-paper `
  --paper-limit 2
```

This processes `abstractexplorer` and `corpusstudio`, the first two manifest
entries. Omit `--paper-limit 2` to process all five papers. Every language
judgment uses a configured Claude Skill; singleton nodes reuse their member
question without an API call. Results are immutable
under `runs/hci-two-paper/revisions/`; response cache entries are reused by
content hash.

The pipeline completes section/subsection matching for every selected paper
and regenerates the structural-node questions. It then runs one rerepresentation
pass in which structural singletons may join eligible non-singleton nodes, regenerating
the changed questions once. Paragraphs are matched only inside those finalized
structural nodes. From the third represented paper onward, each paper is
matched against existing multi-paper paragraph nodes rather than against one
paper at a time.

Retry one stage and replay the ordered corpus:

```powershell
python -m pipeline.incremental_graph.cli retry `
  runs/hci-two-paper `
  --paper-index 2 `
  --stage section_matching
```

## Open the viewer

Package the current revision:

```powershell
$run = Get-Content runs/hci-two-paper/run.json | ConvertFrom-Json
$dataset = Join-Path $run.current_revision_dir "dataset"
python -m pipeline.viewer.package `
  $dataset `
  site/hci-two-paper `
  --dataset-id hci-two-paper `
  --label "HCI Two-Paper Graph"
```

Serve it over HTTP, then open `http://localhost:8000`:

```powershell
python -m http.server 8000 --directory site/hci-two-paper/public
```

The viewer exposes Question Groups and Paper Map. Graph Replay appears only
when the packaged dataset contains a valid `graph-replay.json`. Its optional
`Show hierarchy` control reveals section-to-subsection edges and switches to an
ordered hierarchical layout.

Each run also writes `correspondences.json` and a human-readable
`correspondences.md`. Structural rows contain reciprocal matches plus accepted
rerepresentation merges. Paragraph
rows may also contain one-way matches immediately adjacent to a reciprocal anchor
within the exact same section or subsection node. Bold entries are reciprocal;
plain paragraph entries are accepted adjacent fan-in members. Other unrequited
matches remain audit-only provenance and never feed later matching or questions.

## Verification

```powershell
python -m unittest discover -s tests -v
```

The detailed graph contract is documented in
`pipeline/incremental_graph/README.md`.
