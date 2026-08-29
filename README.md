# SME question-group graph

This repository contains the retained Structural Mapping Engine work: the
order-dependent question-group graph, Claude extraction and matching harness,
canonical HCI inputs, the Paper Map and Question Groups viewer, Graph Replay,
and the earlier proposition-graph SME.

## Layout

| Path | Purpose |
|---|---|
| `datasets/hci-five-paper/` | Five canonical, question-decorated HCI papers and their ordered manifest |
| `pipeline/incremental_graph/` | Elena's incremental section and paragraph graph |
| `pipeline/skill_pipeline/` | Configurable Claude Skills API harness |
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

The expected input is five papers, 52 non-empty top-level sections, and 459
paragraphs. Every retained section and paragraph already has a question, so a
graph run reuses those questions rather than paying to generate them again.

## Run the graph

```powershell
$env:ANTHROPIC_API_KEY = "your-key"
python -m pipeline.incremental_graph.cli run `
  datasets/hci-five-paper/manifest.yaml `
  runs/hci-five-paper
```

The run processes papers in manifest order. It still makes model calls for both
matching directions and for regenerated group questions. Results are immutable
under `runs/hci-five-paper/revisions/`; response cache entries are reused by
content hash.

Inspect the current categories:

```powershell
python -m pipeline.incremental_graph.cli categories runs/hci-five-paper
```

Retry one stage and replay the ordered corpus:

```powershell
python -m pipeline.incremental_graph.cli retry `
  runs/hci-five-paper `
  --paper-index 3 `
  --stage section_matching
```

## Open the viewer

Package the current revision:

```powershell
$run = Get-Content runs/hci-five-paper/run.json | ConvertFrom-Json
$dataset = Join-Path $run.current_revision_dir "dataset"
python -m pipeline.viewer.package `
  $dataset `
  site/hci-five-paper `
  --dataset-id hci-five-paper `
  --label "HCI Five-Paper Graph"
```

Serve it over HTTP, then open `http://localhost:8000`:

```powershell
python -m http.server 8000 --directory site/hci-five-paper/public
```

The viewer exposes Question Groups and Paper Map. Graph Replay appears only
when the packaged dataset contains a valid `graph-replay.json`.

## Claude Skill harness

The harness is separate from the canonical incremental graph. It exercises the
retained extraction, annotation, and directional matching Skills against the
configured HCI pair:

```powershell
$env:ANTHROPIC_API_KEY = "your-key"
python -m pipeline.skill_pipeline.runner --dataset hci --stage all
```

Use `--stage questions`, `--stage section_matching`, or
`--stage section_and_subsection_matching` to run only one stage. Outputs go to
`runs/skill-pipeline/` and are not source-controlled.

## Verification

```powershell
python -m unittest discover -s tests -v
```

The detailed graph contract is documented in
`pipeline/incremental_graph/README.md`.
