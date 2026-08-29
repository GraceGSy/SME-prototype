# SME question-group graph

This repository contains the retained Structural Mapping Engine work: the
order-dependent question-group graph, its Claude matching Skill,
canonical HCI inputs, the Paper Map and Question Groups viewer, Graph Replay,
and the earlier proposition-graph SME.

## Layout

| Path | Purpose |
|---|---|
| `datasets/hci-five-paper/` | Five canonical, question-decorated HCI papers and their ordered manifest |
| `pipeline/incremental_graph/` | Incremental section and paragraph graph |
| `pipeline/questions/` | Direct question-annotation commands |
| `pipeline/viewer/` | Paper Map, Question Groups, Graph Replay, and dataset packaging |
| `pipeline/graph_sme/` | Earlier proposition-graph SME retained as a separate implementation |
| `skills/` | Only the extraction and matching Skills used by the retained pipelines |
| `tests/` | Unit and contract tests for the retained code |

Generated runs, model caches, and packaged sites are intentionally ignored.

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
entries. Omit `--paper-limit 2` to process all five papers. Directional matching uses the
checked-in Claude Skill; only multi-member group questions use structured Anthropic calls.
Singleton groups reuse their member question without an API call. Results are immutable
under `runs/hci-two-paper/revisions/`; response cache entries are reused by
content hash.

Inspect the current categories:

```powershell
python -m pipeline.incremental_graph.cli categories runs/hci-two-paper
```

Retry one stage and replay the ordered corpus:

```powershell
python -m pipeline.incremental_graph.cli retry `
  runs/hci-two-paper `
  --paper-index 3 `
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

Each run also writes `correspondences.json`, a deterministic report combining
reciprocal groups with section- and paragraph-level fan-in claims. One-way
claims remain provenance only and never become graph edges.

## Verification

```powershell
python -m unittest discover -s tests -v
```

The detailed graph contract is documented in
`pipeline/incremental_graph/README.md`.
