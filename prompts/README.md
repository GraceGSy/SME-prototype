# Pipeline prompts

This directory contains the pipeline's Claude/OpenAI Skills, Jev prompts, graph
templates, examples, schemas, and request instructions. Python reads these files
directly. They are the runtime sources, not copies maintained for documentation.

## Start here: what are you asking the model to do?

| Task | Edit here | Where the inputs come from |
|---|---|---|
| Claude: describe one passage in the context of the full cleaned paper | [Section wording](graph/section-role-statement/v1/system.md) or [paragraph wording](graph/paragraph-role-statement/v1/system.md) | [Whole-paper preparer](../pipeline/prepare_roles.py): the system instruction, cached paper outline, and focus address. Units are addressed by printed heading (`section: 3 Formative Interview Study`, `paragraph 2 of 3 Formative Interview Study / 3.1 Procedure`), so the paper's own section numbers cannot conflict with the address. Only top-level sections and paragraphs receive roles. `--policy-from` reuses an earlier preparation's exact wording so new papers stay comparable. This path **does not** use an uploaded Skill. |
| Claude: label a matched group | [Group wording](graph/group-role-statement/v1/system.md) and [role-writing Skill](skills/generate-role-statement/SKILL.md) | The graph supplies every member's passage and role, plus the latest member's complete paper (`latest_paper`). Group labels do not decide membership. |
| Jev: decide if anything matches, then choose the best candidate | [Jev wording](requests/jev.json) | Python [selects the wording and constructs the request](../pipeline/incremental_graph/jev_selection.py). The [outline renderer](../pipeline/incremental_graph/jev_outline.py) supplies the focus, candidates and prior matches from the graph and source documents. |

### Which Jev wording should I edit?

There is one JSON **file**, not one generic prompt and not a single prompt per direction.
For top-level section matching in either direction, use the top-level
`has_match_question`, `ranking_question`, `policy`, `gate_example`, and `rank_example`.
For paragraph matching, choose a block by what is actually being compared:
`paragraph_to_paragraph`, `paragraph_to_group`, `paragraph_to_mixed`, or
`group_to_paragraph`. A one-member group counts as one paragraph. Each block
has its own `has_match`, `match`, and `guide`. Those **replace**, not extend,
the default questions and policy; the generic examples are not sent on these
routes. The fallback for other shapes uses the default wording.

Every route appends `outline_rule`. The yes/no criteria use `has_match_true`
and `has_match_false`; ranking criteria are just the eligible option labels.
The two phases send identical **Focus**, **Context**, and **Candidates** blocks.
Each participating node contributes its latest member's complete paper and its
earlier members' own passages; see [node representation](../docs/jev.md#node-representation).
Section records show only Section, Role, and Content: subsection and paragraph text
stays inside its parent section. Only the top-level sections are options.
From the third paper, each request asks about exactly one node, and ties are
ranked separately; see [pairwise matching](../docs/jev.md#pairwise-matching-from-the-third-paper).
With an empty pool there is no
call; at a yes/no score of 0.5 or less there is no ranking. Above 0.5, a single
candidate wins directly; otherwise Jev ranks the pool (oversized pools can split).
The result is a directional vote, not a group assignment.

**Shared wording:** the paragraph `guide` is also used by the generative paragraph
comparison/explanation builder. Editing it can affect Claude as well as Jev.
Editing `outline_rule` affects all Jev requests, but not Claude's role-writing prompt.

## Other prompt assets

| What to read or edit | Location |
|---|---|
| Role statement-writing Skill | [skills/generate-role-statement/SKILL.md](skills/generate-role-statement/SKILL.md) |
| Matching and explanation Skill | [skills/match-role/SKILL.md](skills/match-role/SKILL.md) |
| Generative selector policy | [skills/match-role/references/selection.md](skills/match-role/references/selection.md) |
| Shared role across all papers in a group | [graph/shared/group-role.md](graph/shared/group-role.md) |
| Jev Choice/Noul questions, criteria, and policy additions | [requests/jev.json](requests/jev.json) |
| Generative matching demonstrations | [graph/shared/role-matching-examples.md](graph/shared/role-matching-examples.md) |
| Claude/OpenAI top-level instructions | [requests/providers.json](requests/providers.json) |
| Extraction instructions and domain-specific Skills | [requests/extraction.json](requests/extraction.json), [skills/extract-section-and-subsection-paragraphs/](skills/extract-section-and-subsection-paragraphs/) |
| Shared-context and text-reference instructions | [requests/evidence.json](requests/evidence.json) |
| Evidence-repair and retry instructions | [requests/evidence-repair.json](requests/evidence-repair.json) |

The `requests/*.json` files preserve whitespace inside strings because it is part
of the rendered request. Fields such as `{title}` or `{error}` are filled by
Python with the current document title or validation result. Source text is data;
Python does not treat braces inside that text as template instructions.

## Graph stages

For the graph runner, each template below has a `v1/system.md`. Despite the filename, the generative
adapters send its rendered text as a user-message prefix. The actual top-level
provider instruction comes from `requests/providers.json`.

| Stage | Template |
|---|---|
| Section role statements | [graph/section-role-statement/](graph/section-role-statement/v1/system.md) |
| Paragraph role statements | [graph/paragraph-role-statement/](graph/paragraph-role-statement/v1/system.md) |
| Shared-group and regenerated role statements | [graph/group-role-statement/](graph/group-role-statement/v1/system.md) |
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
| [jev_selection.py](../pipeline/incremental_graph/jev_selection.py), `JevSelector` | Reads the short policy and phase-specific examples in `requests/jev.json`. Sends the existence question first, then ranking only when needed. |
| [judgments.py](../pipeline/incremental_graph/judgments.py), `CachedJudgments` | Registers the configured Skill, renders evidence, binds candidate IDs into the schema, adds Jev's fixed selection, and applies repair prompts when needed. |
| [evidence_encoding.py](../pipeline/incremental_graph/evidence_encoding.py) | Adds `requests/evidence.json` instructions to the shared-text representation. |
| [match_evidence.py](../pipeline/incremental_graph/match_evidence.py) | Fills `requests/evidence-repair.json` templates with validation diagnostics. |
| [providers/anthropic.py](../pipeline/providers/anthropic.py) and [providers/openai.py](../pipeline/providers/openai.py) | Read `requests/providers.json` and attach the registered Skills, tools, and output schema. |
| [extraction.py](../pipeline/extraction.py) | Reads `requests/extraction.json` and registers the extraction Skill from this directory. Extraction runs separately from graph construction. |
| [evidence.py](../pipeline/incremental_graph/evidence.py) and [runner.py](../pipeline/incremental_graph/runner.py) | Supply dynamic source text, focus, candidate IDs, scope, and role statement metadata. Python retains graph rules and validation; those are not prompt instructions. |

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

New graph-provider receipts store SDK parameters, including the system instruction
where applicable; older receipts may contain only messages, schema and policy.
They do not embed the uploaded Skill files. The judgment records identify the Skill
version and source hash. Whole-paper preparation instead saves one `responses.jsonl`
beside the prepared manifest: the first record stores the shared parameters, paper
prefixes and prompts, and each subsequent response identifies its focus. Claude's
adapter also removes unsupported schema constraints before sending the schema.

Caches can include multiple revisions, failed attempts, or responses reused from
another run. A cache hit does not mean a new API call occurred. Deterministic
inherited matches record provenance but send no model request.

The completed two-paper Jev example is
`runs/hci-first-two-jev-uncapped-20261025-01/revisions/revision-0001/`.
Its caches live in the parent run's `cache/` directory. Reading them makes no API
calls. They contain source passages; keep them local unless you intend to publish
that content.
