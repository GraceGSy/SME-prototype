# Provider Transports

This directory owns API requests, native skill registration, prompt-cache controls,
attachments, response parsing, and provider usage. It does not import graph or
extraction logic.

- `contracts.py`: request limits, registered skill references, results, and the
  `SkillClient` interface.
- `factory.py`: selects the provider client.
- `settings.py`: strict provider/model selection and saved call limits.
- `registry.py`: credentials, account-scoped registration state, source hashing,
  cache reuse, and saving successful uploads. Each adapter supplies its upload call.
- `anthropic.py`: Claude Messages and native Skills transport.
- `openai.py`: OpenAI Responses, native Skills, and hosted shell transport.
- `limits.py`: shared prompt limits and process-local usage guards.
- `responses.py`: saved paid responses, usage records, JSON validation, and API
  schema projections. Each adapter extracts its own final response text.

The OpenAI transport targets models supporting native Skills and explicit prompt
caching (GPT-5.6 and later). It uploads the same skill files, pins their versions,
and puts cache breakpoints after shared instructions and candidate evidence, before
the changing focus. OpenAI input-token totals already include cached tokens;
Anthropic reports uncached input, cache reads, and cache writes separately.
Both adapters preserve raw usage before rejecting an incomplete or invalid result.
`thinking: adaptive` maps to OpenAI's configured reasoning effort;
`thinking: disabled` maps to `reasoning.effort: none`. The output allowance includes
reasoning tokens. Anthropic's tool-context clearing option does not trigger
OpenAI truncation; both routes keep the complete candidate evidence.

OpenAI requires an object at the root of structured output. The adapter wraps
array-shaped extraction output in a `result` field on the wire and unwraps it
before canonical validation. It does not repair malformed JSON or source evidence.

API references: [Skills](https://developers.openai.com/api/docs/guides/tools-skills),
[prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching), and
[structured output](https://developers.openai.com/api/docs/guides/structured-outputs).

To understand SMELTER, start with `../incremental_graph/runner.py` for stage order,
`match_rules.py` for acceptance, and `judgments.py` for prompts, completed-call
caching, evidence checks, and bounded correction retries. Those rules are shared
by transports. Extraction lives separately in `../extraction.py`.
