# Pipeline prompts

This directory contains the pipeline's Claude/OpenAI Skills, Jev prompts, graph
templates, examples, schemas, and request instructions. Python reads these files
directly. They are the runtime sources, not copies maintained for documentation.

## Start here

| What to read or edit | Location |
|---|---|
| Question-writing Skill | [skills/generate-question/SKILL.md](skills/generate-question/SKILL.md) |
| Matching and explanation Skill | [skills/match-role/SKILL.md](skills/match-role/SKILL.md) |
| Semantic matching policy shared by Jev and the LLM | [skills/match-role/references/selection.md](skills/match-role/references/selection.md) |
| Shared role across all papers in a group | [graph/shared/group-role.md](graph/shared/group-role.md) |
| Jev Choice/Noul questions, criteria, and policy additions | [requests/jev.json](requests/jev.json) |
| Matching demonstrations | [graph/shared/role-matching-examples.md](graph/shared/role-matching-examples.md) |
| Claude/OpenAI top-level instructions | [requests/providers.json](requests/providers.json) |
| Extraction instructions and domain-specific Skills | [requests/extraction.json](requests/extraction.json), [skills/extract-section-and-subsection-paragraphs/](skills/extract-section-and-subsection-paragraphs/) |
| Shared-context and text-reference instructions | [requests/evidence.json](requests/evidence.json) |
| Evidence-repair and retry instructions | [requests/evidence-repair.json](requests/evidence-repair.json) |

The `requests/*.json` files preserve whitespace inside strings because it is part
of the rendered request. Fields such as `{title}` or `{error}` are filled by
Python with the current document title or validation result. Source text is data;
Python does not treat braces inside that text as template instructions.

## Graph stages

Each template below has a `v1/system.md`. Despite the filename, the generative
adapters send its rendered text as a user-message prefix. The actual top-level
provider instruction comes from `requests/providers.json`.

| Stage | Template |
|---|---|
| Section and subsection questions | [graph/section-question/](graph/section-question/v1/system.md) |
| Paragraph questions | [graph/paragraph-question/](graph/paragraph-question/v1/system.md) |
| Shared-group and regenerated questions | [graph/group-question/](graph/group-question/v1/system.md) |
| Forward structural matching | [graph/section-to-group-match/](graph/section-to-group-match/v1/system.md) |
| Reverse structural matching | [graph/group-to-section-match/](graph/group-to-section-match/v1/system.md) |
| Forward paragraph matching | [graph/paragraph-to-group-match/](graph/paragraph-to-group-match/v1/system.md) |
| Reverse paragraph matching | [graph/group-to-paragraph-match/](graph/group-to-paragraph-match/v1/system.md) |
| Forward singleton recovery | [graph/singleton-to-group-match/](graph/singleton-to-group-match/v1/system.md) |
| Reverse singleton recovery | [graph/group-to-singleton-match/](graph/group-to-singleton-match/v1/system.md) |

[graph/shared/](graph/shared/) owns shared rules, examples, and output schemas.
[contexts/](contexts/) specifies which evidence fields each stage receives.
The [pipeline configuration](../pipeline/incremental_graph/configs/incremental-v1.yaml)
connects stage names to these templates, contexts, and Skills.

## Python wiring

| Consumer | Files it reads or assembles |
|---|---|
| [pipeline/prompts.py](../pipeline/prompts.py) | Locates this directory and loads the request JSON files. |
| [configuration.py](../pipeline/incremental_graph/configuration.py), `PromptRepository.render` | Reads graph templates and context definitions, expands examples, appends shared rules, and loads output schemas. |
| [jev_selection.py](../pipeline/incremental_graph/jev_selection.py), `JevSelector` | Reads `requests/jev.json`, the shared selection policy, group-role rules, and matching examples. Builds the `model`, `state`, and `questions` body. Jev receives adapted examples and selection rules, not the full Claude Skill or its quotation-output instructions. |
| [judgments.py](../pipeline/incremental_graph/judgments.py), `CachedJudgments` | Registers the configured Skill, renders evidence, binds candidate IDs into the schema, adds Jev's fixed selection, and applies repair prompts when needed. |
| [evidence_encoding.py](../pipeline/incremental_graph/evidence_encoding.py) | Adds `requests/evidence.json` instructions to the shared-text representation. |
| [match_evidence.py](../pipeline/incremental_graph/match_evidence.py) | Fills `requests/evidence-repair.json` templates with validation diagnostics. |
| [providers/anthropic.py](../pipeline/providers/anthropic.py) and [providers/openai.py](../pipeline/providers/openai.py) | Read `requests/providers.json` and attach the registered Skills, tools, and output schema. |
| [extraction.py](../pipeline/extraction.py) | Reads `requests/extraction.json` and registers the extraction Skill from this directory. Extraction runs separately from graph construction. |
| [evidence.py](../pipeline/incremental_graph/evidence.py) and [runner.py](../pipeline/incremental_graph/runner.py) | Supply dynamic source text, focus, candidate IDs, scope, and question metadata. Python retains graph rules and validation; those are not prompt instructions. |

Start a new Python process after editing prompt files. Existing saved runs retain
their original metadata and request caches. This relocation changes code and
configuration paths, so old runs can fail the policy check on `retry` or `add`.
Use the matching code revision to resume those runs; do not rewrite their saved
policy hashes or inputs to bypass the check. Completed-run viewing and comparison
do not need the old prompt paths. Skill registrations remain in the repository's
`_cache/`; moving an unchanged Skill reuses its existing uploaded version.

## Inspect what was sent

Paths below are relative to the repository root. Current templates alone cannot
show what an older run sent.

| Saved record | Fields to inspect |
|---|---|
| `runs/<run>/cache/jev/<fingerprint>.json` | `request` is the complete cached Jev body: `model`, `state`, and `questions`, including rendered instructions and criteria. |
| `runs/<run>/cache/jev/responses/*.json` | `request` records each retained HTTP attempt, including errors. Authentication headers are excluded. |
| `runs/<run>/cache/responses/*.json` | `messages` contains the generative request's text blocks in order, including evidence and repair feedback. `schema` is the local output contract; `api_schema`, when present, records the provider-specific version. |
| `runs/<run>/revisions/<revision>/provenance/attempts.jsonl` | Stage, prompt and Skill references, `rendered_system`, `rendered_user`, model/Skill metadata, cache status, and result. Follow `raw_response.jev.calls[].fingerprint` to the Jev cache bodies. |

Generative response files do not embed the provider's top-level system instruction
or uploaded Skill files. The judgment records identify the Skill version and
source hash; use the matching code/Skill revision for historical audits. Claude's
adapter also removes unsupported schema constraints before sending the schema.

Caches can include multiple revisions, failed attempts, or responses reused from
another run. A cache hit does not mean a new API call occurred. Deterministic
inherited matches record provenance but send no model request.

The completed two-paper Jev example is
`runs/hci-first-two-jev-uncapped-20261025-01/revisions/revision-0001/`.
Its caches live in the parent run's `cache/` directory. Reading them makes no API
calls. They contain source passages; keep them local unless you intend to publish
that content.
