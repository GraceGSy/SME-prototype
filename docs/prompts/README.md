# Prompts and sent requests

Most graph prompts already live in
[`pipeline/incremental_graph/prompts/`](../../pipeline/incremental_graph/prompts/).
Jev also builds instructions in Python, and the generative providers attach
Skills. Use this index to find all of these sources without maintaining duplicate
copies of the instructions.

To inspect what a saved run sent, start with the request records below. Current
templates alone cannot tell you what an older run sent.

## Prompt sources

| Purpose | Authoritative source |
|---|---|
| Section and subsection questions | [section-question/v1/system.md](../../pipeline/incremental_graph/prompts/section-question/v1/system.md) |
| Paragraph questions | [paragraph-question/v1/system.md](../../pipeline/incremental_graph/prompts/paragraph-question/v1/system.md) |
| Shared-group questions, including regenerated questions | [group-question/v1/system.md](../../pipeline/incremental_graph/prompts/group-question/v1/system.md) |
| Forward structural matching | [section-to-group-match/v1/system.md](../../pipeline/incremental_graph/prompts/section-to-group-match/v1/system.md) |
| Reverse structural matching | [group-to-section-match/v1/system.md](../../pipeline/incremental_graph/prompts/group-to-section-match/v1/system.md) |
| Forward paragraph matching | [paragraph-to-group-match/v1/system.md](../../pipeline/incremental_graph/prompts/paragraph-to-group-match/v1/system.md) |
| Reverse paragraph matching | [group-to-paragraph-match/v1/system.md](../../pipeline/incremental_graph/prompts/group-to-paragraph-match/v1/system.md) |
| Forward singleton recovery | [singleton-to-group-match/v1/system.md](../../pipeline/incremental_graph/prompts/singleton-to-group-match/v1/system.md) |
| Reverse singleton recovery | [group-to-singleton-match/v1/system.md](../../pipeline/incremental_graph/prompts/group-to-singleton-match/v1/system.md) |
| Shared-role rules, evidence rules, examples, output schemas | [prompts/shared/](../../pipeline/incremental_graph/prompts/shared/) |
| Matching policy shared by Jev and the LLM Skill | [skills/match-role/references/selection.md](../../skills/match-role/references/selection.md) |
| LLM matching and explanation Skill | [skills/match-role/SKILL.md](../../skills/match-role/SKILL.md) |
| Question-writing Skill | [skills/generate-question/SKILL.md](../../skills/generate-question/SKILL.md) |
| Extraction Skill and domain instructions | [skills/extract-section-and-subsection-paragraphs/](../../skills/extract-section-and-subsection-paragraphs/) |

The [pipeline configuration](../../pipeline/incremental_graph/configs/incremental-v1.yaml)
maps stages to prompt, context, and Skill names.

## Instructions assembled in Python

| Source | What it adds |
|---|---|
| [jev_selection.py](../../pipeline/incremental_graph/jev_selection.py), `JevSelector.__init__` and `build_request` | Jev policy composition, Choice/Noul questions, candidate criteria, abstention wording, and the `model`, `state`, `questions` request body. It combines the shared selection policy, group-role rules, and adapted matching examples. Jev does not receive the full Claude Skill or the LLM's quotation-output contract. |
| [configuration.py](../../pipeline/incremental_graph/configuration.py), `PromptRepository.render` | Expands examples, appends shared rules, loads the output schema, and serializes context according to [contexts/](../../pipeline/incremental_graph/contexts/). The name `system.md` describes a template; the generative adapters send its rendered text as a user-message prefix. |
| [judgments.py](../../pipeline/incremental_graph/judgments.py), `render_request`, `judge`, `_judge_once` | Binds candidate IDs into the schema, supplies Jev's `fixed_target_id` to the explanation model, and appends evidence-repair feedback when needed. |
| [match_evidence.py](../../pipeline/incremental_graph/match_evidence.py) | Supplies the quotation and attribution error messages used in repair prompts. |
| [evidence_encoding.py](../../pipeline/incremental_graph/evidence_encoding.py), `encode_evidence` | Adds the instructions for reading `full_text_refs` through `source_texts`. Text is shared without truncating it or merging candidate identities. |
| [evidence.py](../../pipeline/incremental_graph/evidence.py) and [runner.py](../../pipeline/incremental_graph/runner.py) | Build the per-call source evidence, focus, candidate pool, scope, and generated-question metadata. These values change for each judgment. |
| [providers/anthropic.py](../../pipeline/providers/anthropic.py), `CACHEABLE_SYSTEM` and `_run` | Adds the actual Claude system instruction, registered Skill references, tools, and API output schema. |
| [providers/openai.py](../../pipeline/providers/openai.py), `INSTRUCTIONS` and `_run` | Adds the OpenAI instruction, Skill references, hosted-shell tool, and any required result-wrapper instruction. This applies only when OpenAI is selected. |
| [extraction.py](../../pipeline/extraction.py), `_extract_source` | Adds the extraction request, document title, and domain instruction. Extraction runs separately from graph construction. |

## Exact saved requests

Paths below are relative to the repository root. Open a completed revision's
`provenance/attempts.jsonl` first to identify the stage and request fingerprint.

| Saved record | What to inspect |
|---|---|
| `runs/<run>/cache/jev/<fingerprint>.json` | `request` contains the complete cached Jev body: `model`, `state`, and `questions`. Read `questions.match` and, when present, `questions.has_match`; their `instructions` and `criteria` contain the rendered prompt. |
| `runs/<run>/cache/jev/responses/*.json` | `request` records the body for each HTTP attempt, including retained HTTP errors. `response_text` stores the provider response. These records exclude authentication headers. |
| `runs/<run>/cache/responses/*.json` | `messages` contains the actual generative request's text blocks in order, including prompt prefixes, evidence, and repair feedback. `schema` contains the local output contract; `api_schema`, when present, records the provider-specific version. |
| `runs/<run>/revisions/<revision>/provenance/attempts.jsonl` | Each completed judgment records its stage, prompt and Skill references, `rendered_system`, `rendered_user`, model/Skill metadata, cache status, and result. Follow `raw_response.jev.calls[].fingerprint` to the Jev cache bodies. |

The generative response files are not complete HTTP-request dumps: they do not
embed the provider's top-level system instruction or the uploaded Skill files.
The judgment records identify the Skill version and source hash. Use the matching
code/Skill revision when auditing historical calls; today's files may differ.
For Anthropic, `_run` removes unsupported schema constraints before sending the
schema, so the saved local `schema` is not byte-for-byte the API schema.

Caches belong to the whole run and may include multiple revisions, failed
attempts, or responses reused from another run. Use a revision's provenance to
identify its accepted judgments. A cache hit does not mean a new API call took
place. Deterministic inherited matches also have rendered provenance, but send
no prompt to a model.

The completed two-paper Jev example is
`runs/hci-first-two-jev-uncapped-20261025-01/revisions/revision-0001/`.
Its request caches live in the parent run's `cache/` directory. Reading these
files makes no API calls. They include source passages; keep them local unless
you intend to publish that content.
