# Run SMELTER with Jev and compare results

Jev now selects matches in every initial and singleton-recovery pass, including
paragraphs moved into a new structural scope. Python still controls candidate
eligibility, reciprocity, paragraph fan-in, evidence validation, and graph updates.
The existing generative provider still writes missing questions, group questions,
and explanations with source quotations. **A TypeSafe key alone is not enough:
the default Jev run needs both `TYPESAFE_API_KEY` and `ANTHROPIC_API_KEY`.**

The implementation and scripted end-to-end tests work offline. No live Jev run
has been verified here. Run the small fixture below before a real corpus.

## Detailed flow

The flow has two separate diagrams. Every step has a single responsibility:
purple for Jev selection, orange for generative LLM work, and green for
deterministic Python steps. No striped or mixed-responsibility boxes remain.

**A. Run lifecycle and document insertion:**
[PNG](diagrams/jev-pipeline.png), [zoomable SVG](diagrams/jev-pipeline.svg),
[Graphviz source](diagrams/jev-pipeline.dot).

![A. Run lifecycle, document insertion, and comparison](diagrams/jev-pipeline.png)

Read A's numbered columns in order. They separate question generation, Jev
selection, fixed-target explanations, validation, reconciliation, and recovery.
Named connectors continue execution in another column. Each matching sequence
runs once per directional request before Python reconciles the complete set.

**B. One directional match:**
[PNG](diagrams/jev-matching.png), [zoomable SVG](diagrams/jev-matching.svg),
[Graphviz source](diagrams/jev-matching.dot).

![B. Jev selection, fixed-target evidence, caching, and retry](diagrams/jev-matching.png)

B expands the common matching operation used by all initial, recovery, and
older-paragraph passes in A. Its three columns show complete-cache lookup,
recursive Jev selection, and fixed-target evidence. Unlike the earlier Decisions
API proposal, this implementation calls TypeSafe directly.

## Directory and setup

Run all commands from **`hypothesis/SME-prototype-elena-clean`**, the nested
repository containing `pipeline/`, `datasets/`, `requirements.txt`, and
`package.json`. Do not run them from the parent `hypothesis` directory or from
inside `pipeline/`. The module is `pipeline.incremental_graph.cli`, including
the final `.cli`.

Use Python 3.11. On macOS, substitute your checkout's location:

```bash
cd "/path/to/hypothesis/SME-prototype-elena-clean"
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On this Windows checkout, in PowerShell:

```powershell
cd "C:\HBS\Glassman Lab Research\hypothesis\SME-prototype-elena-clean"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If you already have the environment, activate it rather than recreating it.
The remaining `python` commands work in either activated environment.

## Credentials

On macOS Terminal (zsh or bash), set keys for this terminal session:

```bash
export TYPESAFE_API_KEY="your-typesafe-key"
export ANTHROPIC_API_KEY="your-anthropic-key"
```

In Windows PowerShell:

```powershell
$env:TYPESAFE_API_KEY = "your-typesafe-key"
$env:ANTHROPIC_API_KEY = "your-anthropic-key"
```

In Windows Command Prompt (`cmd.exe`):

```bat
set "TYPESAFE_API_KEY=your-typesafe-key"
set "ANTHROPIC_API_KEY=your-anthropic-key"
```

Replace the placeholders privately. Literal keys typed into a shell can remain
in its history. Do not paste keys into chat, commit them, or include them in reports.
These assignments affect that shell and its child processes, not other terminals.

Alternatively, keep plain `NAME=value` lines in an untracked `.env`. For each
key, the loader checks the process environment first, then `.env` in the nested
repository root, then each ancestor directory, nearest first. Thus a key in
`hypothesis/.env` can supply this repository if the closer file does not supply
it. This is a small key-value reader, not shell execution: omit `export`, variable
interpolation, and inline comments. `validate` does not load keys. `start --jev`
checks that both required keys exist before creating a run or making paid calls;
that check does not authenticate them with either service.

The default generative configuration remains `claude-sonnet-5`. To use the
existing OpenAI native-Skills route, supply `OPENAI_API_KEY` instead of the
Anthropic key and add `--provider openai --model YOUR_SKILLS_CAPABLE_MODEL` to
`start`. An arbitrary chat model will not work. That route also needs live
verification; Jev always uses the separate TypeSafe key.

## Minimal live Jev run

The fixture contains two synthetic documents with two sections and two paragraphs
each. Stored unit questions avoid unnecessary generation. One pair describes the
same interruption mechanism in different domains; the remaining units have
different roles. These inputs are manually authored, so no extraction is needed.

First validate offline, without keys or network:

```bash
python -m pipeline.incremental_graph.cli validate datasets/jev-smoke/manifest.yaml
```

Expect `water`, then `warning`, each with two sections, two paragraphs, and zero
missing questions. After setting both keys, run:

```bash
python -m pipeline.incremental_graph.cli start datasets/jev-smoke/manifest.yaml runs/jev-smoke-01 --jev --jev-model jev-1.14.0 --jev-max-calls 12 --max-api-responses 80
python -m pipeline.incremental_graph.smoke_check runs/jev-smoke-01
```

**`start` makes paid calls.** It requires a new run directory. Choose
`jev-smoke-02` for a separate experiment; do not delete a prior run to reuse its
name. The pinned Jev version is explicit because TypeSafe's aliases move.
See the [official model list](https://docs.typesafe.ai/models).

The smoke checker makes no API calls. It should print `"passed": true` and exit
zero. Expected memberships at both levels are one shared group containing the
two mechanism units and two singleton groups. A different completed graph is a
failed semantic smoke check, even if the API requests succeeded. The checker
also reports `selector: "jev"` or `"llm"`; verify that the Jev run says `jev`.
Passing this synthetic example does not establish corpus-level accuracy.

The scripted successful test uses six Jev requests and six generative Skill
invocations: four evidence explanations and two shared-group questions. Live
choices can change that count. Native Skill invocations can require multiple API
responses, and evidence repair can add more. The flags cap Jev requests and
generative responses separately **per process**. They are not dollar limits.
Usage-based token guards apply after receiving a response, and a timeout may
already have incurred a charge. Inspect usage before retrying.

## View the result

With Node.js 22 installed, build the existing viewer once:

```bash
npm ci
npm run build:viewer
python -m pipeline.viewer.server runs --port 8073
```

Open `http://127.0.0.1:8073/`, select `jev-smoke-01`, then its completed revision.
Use Question Groups for memberships and quotations, Paper Map for the individual
documents, or Graphical Explorer for the layout. Two documents are sufficient.
Keep the server terminal open; Ctrl+C stops it. The viewer makes no model calls
and exposes the exported dataset rather than credentials or private caches.

## Compare runs

The comparison command reads completed exports and creates a standalone HTML
report plus machine-readable JSON. It requires neither API keys nor a web server.
For a baseline using the original generative selector, omit `--jev`:

```bash
python -m pipeline.incremental_graph.cli start datasets/jev-smoke/manifest.yaml runs/llm-smoke-01 --max-api-responses 80
python -m pipeline.incremental_graph.compare runs/llm-smoke-01 runs/jev-smoke-01 output/comparisons/llm-vs-jev-smoke-01
```

Only the first command makes paid calls. Open
`output/comparisons/llm-vs-jev-smoke-01/index.html` in a browser. On macOS:

```bash
open output/comparisons/llm-vs-jev-smoke-01/index.html
```

On PowerShell, use
`Start-Process output/comparisons/llm-vs-jev-smoke-01/index.html`.
The output directory must be new; the command never overwrites an older report.

You can compare any compatible existing runs, two Jev configurations, or explicit
completed revision directories instead:

```bash
python -m pipeline.incremental_graph.compare runs/hci-section-medium-excerpts-20260917/revisions/revision-0008 runs/hci-section-medium-excerpts-20260917/revisions/revision-0013 output/comparisons/hci-0008-vs-0013
```

That historical example assumes those local runs are present. A run-directory
argument selects its last completed revision, even if the latest attempt failed.
The tool deliberately permits different historical policies; it does not require
the old run's code hash to match today's checkout.

The report shows changed source memberships and paragraph parent scopes, group
and singleton counts, added/removed co-member pairs, pair-set Jaccard agreement,
and changed group questions. Expand a changed unit to read its passage and both
assignments. `comparison.json` also lists every added and removed pair.

Comparisons ignore generated graph IDs. Shared papers must have the same source
IDs, authored text, and boundaries, and both runs must use the same granularity;
otherwise the tool refuses the comparison. When paper sets differ, pair metrics
cover shared papers only and counts cover the full runs. Parent-scope changes can
include added papers. No pairs in either result means Jaccard is not applicable,
not perfect agreement. Question-only differences appear separately. Neither run
is ground truth: agreement measures consistency, not accuracy or causality.
Keep source preparation, order, granularity, and generative settings constant
when testing the effect of Jev alone.

## Run a real corpus

Use existing canonical JSON and an ordered manifest. For new raw documents, follow
the [source preparation and review instructions](../README.md#run-your-own-documents)
before graph construction. Inspect the offline unit counts first:

```bash
python -m pipeline.incremental_graph.cli validate datasets/my-corpus/manifest.yaml
python -m pipeline.incremental_graph.cli start datasets/my-corpus/manifest.yaml runs/my-corpus-jev --jev --jev-model jev-1.14.0 --jev-max-calls 500 --max-api-responses 3000
```

Those are upper guards, not a recommended spending allowance or a completion
guarantee. The prepared two-paper HCI example has 66 structural units and 221
paragraphs; it is much larger than this smoke test. Review counts and account
limits before starting it. No live cost or accuracy estimate has been established.

To extend a successful run, use a manifest containing only new papers:

```bash
python -m pipeline.incremental_graph.cli add datasets/my-corpus/new.manifest.yaml runs/my-corpus-jev
```

`add` and `retry` retain the saved Jev and generative configuration, including
guards. To change models, limits, prompts, code, dependencies, or source data,
start a new run rather than editing `run.json` or frozen inputs.

## Recover a failed attempt

1. Read `run.json` to identify `latest_revision` and `current_revision`. Inspect
   `revisions/<latest_revision>/failure.json`. A killed process may not have written
   that file; also inspect the terminal error and saved responses. Preserve the
   entire run directory.
2. For missing credentials, set the appropriate environment variable. For an
   authentication, rate-limit, or service error, fix the account issue or wait
   for service recovery. Inspect provider usage before another paid attempt.
3. With unchanged inputs and policy, retry the run:

```bash
python -m pipeline.incremental_graph.cli retry runs/jev-smoke-01
```

Retry writes a new revision and replays the ordered stages, reusing valid saved
judgments. A saved Jev choice survives an evidence-generation failure, so an
ordinary retry need not buy that choice again. Failed attempts do not replace
the last completed revision. This is cached replay, not resuming a Python stack.

Jev HTTP failures other than explicit size rejections, malformed responses,
impossible request sizes, and exhausted evidence repairs stop the attempt.
There is no silent generative-selector fallback.
If a request times out without a saved valid response, retry may repeat a paid
request; the pipeline cannot prove the service did not bill it. Do not repeatedly
retry an unchanged contract or size error. Inspect the retained response and fix
the underlying issue in a new run if it requires a policy change. Do not delete
caches to bypass validation. Avoid `retry --stage` / `--paper-index` unless you
intend to force judgments and potentially pay again.

## Selection, evidence, and saved artifacts

The transport calls [TypeSafe System One](https://docs.typesafe.ai/api/system-one)
with one named Choice question per request. Each pool contains eligible candidate
handles plus `NO_MATCH`. It records the selected option, distribution, confidence,
model, and token usage. The response must satisfy the
[Choice contract](https://docs.typesafe.ai/primitives/choice); probabilities and
confidence do not become a new acceptance threshold.

There is no local 24,000-byte cap or bytes-to-tokens estimate. The local body check
uses TypeSafe's documented [32 MiB transport limit](https://docs.typesafe.ai/api/errors).
Within that limit and 254 candidates, the selector sends the full request first.
The service enforces its [token context limits](https://docs.typesafe.ai/models).
Only an explicit HTTP 400 `max_tokens_exceeded` or HTTP 413 size rejection triggers
size-based splitting; unrelated errors stop rather than causing more calls.

Too many candidates or a real size limit triggers recursive half-pool selection,
up to five retained candidate IDs from each half, then reranking with `NO_MATCH`.
Probabilities are only ranked within their own response distribution. A single
oversized candidate or an unshrinkable reranking pool stops the run. The
implementation never truncates source text or opts into long context. Shortlisting
can discard a candidate that a full-pool comparison would prefer. Rejected HTTP
requests count toward the call guard, and their response bodies are retained.

For every non-null directional choice, the existing generative Skill receives
only the chosen target and must return that same target with a basis and source
quotations. This happens before reciprocal reconciliation, preserving evidence
for rejected one-way choices too. Quote errors allow two repair attempts without
changing Jev's selection. `NO_MATCH` uses a deterministic basis and empty evidence,
with no generative call. Attribution checks do not independently establish the
semantic correctness of a match; the explanation model cannot veto the choice.

Within `runs/<name>/`:

| Location                              | Purpose                                                                        |
| ------------------------------------- | ------------------------------------------------------------------------------ |
| `run.json`                            | Frozen configuration, policy identity, last completed revision, latest attempt |
| `inputs/`                             | Frozen prepared source documents and manifest                                  |
| `cache/jev/<hash>.json`               | Exact Jev request and validated selection, independent of generated evidence   |
| `cache/jev/responses/`                | Raw response records, including responses rejected by validation               |
| `cache/<hash>.json`                   | Complete validated questions/matches, Jev traces, and generated evidence       |
| `cache/responses/`, `cache/rejected/` | Generative responses and rejected evidence for diagnosis                       |
| `revisions/revision-XXXX/`            | Attempt outputs; completed attempts include reports and `dataset/`             |

These records contain source text, so treat them as research data. The integration
does not save authorization headers or keys. Back up the full run, not only its
viewer export, if you need cached recovery.

Advanced configuration can add a `jev` mapping to a copy of
`pipeline/incremental_graph/configs/incremental-v1.yaml`, keeping that copy in
the same directory so relative policy paths stay correct. Use `--config` with it.
Supported fields are `model`, `max_calls`, `max_input_tokens`, and
`timeout_seconds`. Defaults are `jev-1.14.0`, 500, 2,000,000, and 120 respectively.
A configured `jev` mapping also enables Jev without the flag. Remove the obsolete
`max_request_bytes` field from older custom configuration files.

## Offline checks and outstanding live verification

Install the development dependencies and build the viewer contract before tests:

```bash
python -m pip install -r requirements-dev.txt
npm ci
npm run build:viewer
python -m unittest discover -s tests -p "test_jev*.py" -v
python -m unittest discover -s tests -p test_run_comparison.py -v
python -m unittest discover -s tests -q
```

All these tests use fixtures and mocked transports, with no paid API calls. They
cover Jev request/response validation, NO_MATCH, oversized pools, guards, caching,
fixed-target evidence, complete smoke orchestration, viewer export, failure/retry,
and membership-based comparisons. Existing graph tests cover reciprocal, recovery,
adjacency, and reparenting rules. They do not establish real model behavior.

Before scaling, still verify both accounts' model access and native Skills support,
complete the live smoke run and inspect its actual requests/usage, check its
memberships and quotations in the viewer, then compare Jev and baseline runs on
the same reviewed corpus. Human source-by-source evaluation is still necessary
to assess whether either model makes useful correspondences.

Regenerate both diagrams with Graphviz installed:

```bash
dot -Tsvg docs/diagrams/jev-pipeline.dot -o docs/diagrams/jev-pipeline.svg
dot -Tpng -Gdpi=144 docs/diagrams/jev-pipeline.dot -o docs/diagrams/jev-pipeline.png
dot -Tsvg docs/diagrams/jev-matching.dot -o docs/diagrams/jev-matching.svg
dot -Tpng -Gdpi=144 docs/diagrams/jev-matching.dot -o docs/diagrams/jev-matching.png
```
