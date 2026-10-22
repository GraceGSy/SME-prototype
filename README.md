# SMELTER: comparative reading with question-role graphs

SMELTER (Structural Mapping Engine for Long TExtual Reading) compares long
documents by the questions their sections and paragraphs answer. An LLM
proposes questions and local matches; Python applies fixed graph
rules and saves every judgment with its source evidence. A browser viewer shows
the resulting Question Groups and each document's Paper Map. The system is
experimental: a generated match is not a verified analogy or a complete
implementation of the canonical Structure-Mapping Engine.

**Start here:** use the prepared two-paper HCI example below. It requires Python
3.11, an Anthropic API key with credit, and network access. Running the graph
makes paid model calls. There is no provider-enforced spending cap in the core
CLI, so inspect the corpus and model configuration before starting a large run.

**Jev and run comparisons:** the [Jev guide](docs/jev.md) includes a much smaller
two-document smoke test, macOS/Windows key setup, recovery instructions, and
standalone comparisons of completed runs. Jev selects matches; the existing
generative provider still writes questions and quoted evidence. Both keys are
required. See the [detailed pipeline diagram](docs/diagrams/jev-pipeline.svg).

## Run the prepared example

From this repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "your-key"
python -m pipeline.incremental_graph.cli validate datasets/hci-five-paper/content/first-two.manifest.yaml
python -m pipeline.incremental_graph.cli start datasets/hci-five-paper/content/first-two.manifest.yaml runs/hci-first-two
```

`validate` checks the inputs without using the API. `start` creates a new run
directory and maps AbstractExplorer and CorpusStudio in that order. Do not
reuse an existing run directory for a new experiment. A failed run can be
resumed with `python -m pipeline.incremental_graph.cli retry runs/hci-first-two`.
This is not a cheap smoke test: the current example contains 66 structural
units and 221 paragraphs. Review the `validate` output before calling `start`.

To inspect a completed run, install Node.js 22 and build the static viewer:

```powershell
npm ci
npm run build:viewer
python -m pipeline.viewer.server runs --port 8073
```

Open `http://127.0.0.1:8073/`, select the run and a completed revision, then
use Question Groups, Paper Map, or Graphical Explorer. Serving the viewer makes
no model calls. The server exposes viewer data, not keys or judgment caches.

## Run your own documents

1. Prepare at least two canonical JSON documents. Extract each new PDF, UTF-8
   text, or XHTML source once with `pipeline.extraction`. It saves a pending
   source review and reuses the first response for identical source bytes.
2. Open each `.review.html`, check it against the original, and fix the saved
   JSON if necessary. Approve the review offline. Newly extracted content
   cannot enter the graph until approved; extraction never runs inside graph
   construction.
3. Create an ordered YAML manifest. Paths are relative to the manifest. Use
   `section`, `subsection`, or `paragraph` for `max_granularity`; paragraph
   mode requires one stored top-level section per document.
4. Validate the manifest, then start a new run. Use `add` with a manifest
   containing only new documents to extend it. `retry` uses frozen inputs
   after an interruption or failed judgment.

```powershell
python -m pipeline.extraction path/to/paper-a.pdf datasets/my-corpus/paper-a.json --domain academic --title "Paper A"
python -m pipeline.extraction path/to/paper-b.pdf datasets/my-corpus/paper-b.json --domain academic --title "Paper B"
```

After reviewing the HTML reports and original sources:

```powershell
python -m pipeline.source_review path/to/paper-a.pdf datasets/my-corpus/paper-a.json --approve --reviewer "Your name" --notes "Checked source text, headings, paragraph boundaries, and footnotes."
python -m pipeline.source_review path/to/paper-b.pdf datasets/my-corpus/paper-b.json --approve --reviewer "Your name" --notes "Checked source text, headings, paragraph boundaries, and footnotes."
python -m pipeline.incremental_graph.cli validate datasets/my-corpus/manifest.yaml
python -m pipeline.incremental_graph.cli start datasets/my-corpus/manifest.yaml runs/my-corpus
```

The checks detect missing/added tokens, reordered text or heading ownership,
and merged/split paragraph boundaries in authored TXT/XHTML. PDF/layout text
does not supply reliable authored boundaries, so approval requires reviewing
those against the original. If PDF text includes page chrome, interleaved
footnotes, or material intentionally outside the corpus, prepare an independent
paragraph transcript and pass `--reference path/to/reviewed-body.txt` to source
review. Record exclusions in the approval notes; never build that reference
from the extraction being checked.

Approved receipts bind the source and prepared content by hash. Formatting
JSON or changing generated question metadata does not invalidate source
approval; changing authored text or ownership does. Approvals travel with
frozen run inputs. Identical raw source bytes reuse approved content even at a
new path or with a different requested model. Existing manually curated corpora
remain usable but are not automatically marked verified; certify them with the
same source-review command without re-extracting.

Keep `_cache/source-extractions/` backed up. It freezes the original source
and retains the first extraction and approved copy, including responses rejected
by local content validation.
An interrupted extraction with an uncertain outcome refuses an automatic
second call; inspect retained provider responses or curate the saved source.

To extend that run later, put only the additional documents in another
manifest and call
`python -m pipeline.incremental_graph.cli add datasets/my-corpus/new.manifest.yaml runs/my-corpus`.

Example `datasets/my-corpus/manifest.yaml`:

```yaml
schema_version: 1
max_granularity: subsection
papers:
  - paper_id: paper-a
    title: Paper A
    file: paper-a.json
  - paper_id: paper-b
    title: Paper B
    file: paper-b.json
```

The extraction domains are exactly `academic`, `legal`, and `narrative`; select
one explicitly. Existing prepared corpora are under `datasets/`. Do not
re-extract them for a new graph experiment. A manifest's order is the graph's
insertion order and can affect the result. The [data contract](docs/data-contracts.md)
defines every accepted field and the paragraph-only constraint.

The configured default model is `claude-sonnet-5` with the settings in
[`incremental-v1.yaml`](pipeline/incremental_graph/configs/incremental-v1.yaml).
For a different provider/model, set its API key and pass both flags on `start`:

```powershell
$env:OPENAI_API_KEY = "your-key"
python -m pipeline.incremental_graph.cli start datasets/my-corpus/manifest.yaml runs/my-openai-run --provider openai --model YOUR_SKILLS_CAPABLE_MODEL
```

The selected provider and model remain fixed for `add` and `retry`. Both routes
require native Skills support; an arbitrary chat model will not work. Offline
tests verify the OpenAI transport contract, but a live OpenAI graph run has not
been verified here. Provider usage limits are acceptance guards, not guaranteed
cost ceilings. Raw extraction with OpenAI also needs `--provider openai --model`.

## What the pipeline saves

The graph processes documents in order. For each document it compares
structural roles in both directions, accepts reciprocal choices, revisits
eligible singletons, then repeats the process for paragraphs inside their
assigned structural groups. Paragraphs may join an adjacent accepted core
under a limited fan-in rule. Each match request chooses one candidate or null;
Python controls the final mapping. The [flow diagrams](PIPELINE_FLOW.md) show
the stage order, including paragraph-only mode and reparented sections.

Each `start`, `add`, or `retry` attempt writes a new immutable revision under
`runs/<name>/revisions/`. A successful revision contains the graph, source
passages, correspondence reports, a singleton report, event/provenance records,
and a viewer dataset. `run.json` points to the last completed revision and the
latest attempt. Unchanged model judgments may be reused when an addition or
retry replays the ordered sequence. Code, prompt, Skill, configuration, or
dependency changes require a new run rather than mixing policies.

## Find the code

| Path | Responsibility |
| --- | --- |
| [`pipeline/extraction.py`](pipeline/extraction.py) | One-time extraction of a new source |
| [`pipeline/document.py`](pipeline/document.py) | Canonical document schema and positional IDs |
| [`pipeline/source_review.py`](pipeline/source_review.py) | Offline coverage/boundary checks, review reports, and approval receipts |
| [`pipeline/incremental_graph/`](pipeline/incremental_graph/) | Ordered graph, judgments, deterministic rules, revisions, and export |
| [`pipeline/providers/`](pipeline/providers/README.md) | Anthropic/OpenAI native Skill transports |
| [`skills/`](skills/) | Maintained extraction, question, and matching instructions |
| [`pipeline/viewer/`](pipeline/viewer/) | Browser views, local server, and static packaging |
| [`datasets/`](datasets/) | Raw sources, prepared content, manifests, and provenance |
| [`helpers/`](helpers/README.md) | Optional one-time content preparation and report regeneration |
| [`tests/`](tests/) | Offline contract, graph, and viewer checks |

The [architecture guide](docs/architecture.md) explains matching and recovery
rules. The [Sherlock assessment](docs/sherlock-experiment.md) records observed
semantic failures and limits; passing tests does not establish mapping quality.

## Verify changes

```powershell
python -m pip install -r requirements-dev.txt
npm ci
npm run build:viewer
python -m ruff check pipeline tests helpers
python -m ruff format --check pipeline tests helpers
python -m unittest discover -s tests -q
npm run test:viewer
npm run format:check
```

These checks use scripted judgments and make no paid model calls. A live run
and source-by-source review are still needed before interpreting its mappings.
