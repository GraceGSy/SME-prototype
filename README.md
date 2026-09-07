# Question Atlas: Experimental Structure-Mapping Graph

This repo compares documents by the roles their passages play, not just by topic.
It uses Claude Skills for language judgments and deterministic Python for graph
membership, ordering, provenance, and replay. The viewer lets a researcher inspect
shared questions alongside the original passages.

It is an experimental, SME-inspired matcher, **not an implementation or validation
of Gentner's complete Structure-Mapping Engine**. There have been no real-user
evaluations. Start with [the Sherlock assessment](docs/sherlock-experiment.md).

## Two Pipelines

1. **Extract new documents once:** raw PDF, UTF-8 text, or XHTML -> canonical
   content JSON and extraction provenance. Existing outputs are never overwritten.
2. **Build the ordered graph:** prepared documents -> questions, directional
   judgments, deterministic graph, correspondence report, and viewer dataset.
   Start with at least two papers; append another paper or an ordered manifest.

Packaging the static viewer is an offline export operation, not a third model
pipeline. No command implicitly extracts a document during graph construction.

## Setup

Python 3.11 and Node 22 are the tested runtimes. From this repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci
npm run build:viewer
```

Model commands use `ANTHROPIC_API_KEY`, or the nearest ancestor `.env`.
Tests and manifest validation do not need a key.

## Extract A New Document

```powershell
python -m pipeline.extraction path/to/new-paper.pdf datasets/my-corpus/content/new-paper.json --domain academic --title "New Paper"
```

The domain must be exactly `academic`, `legal`, or `narrative`. It is not inferred
from the extension. Extraction returns content only, not questions.
The attachment bounds are 20 MB for PDF and 500 KB for text/XHTML.
A valid schema is not proof of faithful extraction: inspect new content against
the raw document before including it in a graph.

The checked-in corpora are already prepared. Do not extract them again.

## Start, Add, Retry

```powershell
python -m pipeline.incremental_graph.cli validate datasets/hci-five-paper/manifest.yaml
python -m pipeline.incremental_graph.cli start datasets/hci-five-paper/manifest.yaml runs/hci
python -m pipeline.incremental_graph.cli add path/to/additions.manifest.yaml runs/hci
python -m pipeline.incremental_graph.cli retry runs/hci
```

The manifest order is the insertion order. A start manifest needs at least two
papers; additional entries extend the initial pair in order. An add manifest
contains only new paper IDs and must retain the existing granularity.

Each document completes structural matching, reciprocal singleton realignment,
then the same operations for paragraphs within their exact section nodes before
the next document is inserted. Paragraph-only mode still runs paragraph realignment.

`add` replays this ordered sequence with cached judgments into a new revision;
it does not mutate the previous revision in place. A structural merge moves any
existing paragraph nodes into the new scope without changing their IDs.
Successful and failed revisions remain separate. A failed latest revision must
be retried before another add.

A targeted retry can force a stage for one paper:
`retry runs/hci --paper-index 2 --stage section_matching`.
This forces that stage's requests, not an arbitrary downstream invalidation.
Unchanged downstream inputs reuse their existing cached judgments.

Saved input hashes and code/prompt/Skill/config/dependency fingerprints are
checked before adding or retrying. If policy changed, start a new run. Old run
formats and legacy caches are not migrated at runtime.

## Package And Inspect

```powershell
$state = Get-Content runs/hci/run.json | ConvertFrom-Json
$dataset = Join-Path runs/hci/revisions (Join-Path $state.current_revision dataset)
python -m pipeline.viewer.package $dataset site/hci --dataset-id hci --label "HCI Graph"
python -m http.server 8000 --directory site/hci/public
```

Open `http://localhost:8000`. Question Groups and Paper Map show the final
snapshot. Graph Replay is available when the export includes a valid replay.
Malformed present replay data is an error, not a silently hidden tab.
Packaging requires the viewer build and refuses a nonempty output directory.

## Where Things Live

| Path | Responsibility |
|---|---|
| `pipeline/extraction.py` | New-document extraction entry point |
| `pipeline/document.py` | Canonical source validation and positional IDs |
| `pipeline/incremental_graph/` | Ordered graph orchestration and deterministic rules |
| `pipeline/llm/client.py` | Shared Claude transport and observed usage guards |
| `pipeline/viewer/` | Typed static viewer and offline packaging |
| `datasets/` | Raw sources, canonical content, explicit prepared variants |
| `skills/` | Extraction, question generation, and local role matching |
| `helpers/` | Explicit one-shot preparation; never imported by runtime pipelines |
| `tests/` | Offline algorithm, boundary, failure-recovery, and browser tests |

See [architecture](docs/architecture.md), [data contracts](docs/data-contracts.md),
and [Sherlock findings and next experiment](docs/sherlock-experiment.md).

## Verification

```powershell
npm run build:viewer
python -m unittest discover -s tests -v
python -m ruff check pipeline tests helpers
python -m ruff format --check pipeline tests helpers
npm run test:viewer
npm run format:check
```

Browser tests use installed Microsoft Edge. CI is configured for these checks on Windows.
No test makes a paid model call. Offline correctness does not establish match
quality. Input-token limits are post-response acceptance guards, not guaranteed
spend caps; a single request may incur cost before an observed-usage rejection.
