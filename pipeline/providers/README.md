# Provider Transports

This directory owns API requests, native skill registration, prompt-cache controls,
attachments, response parsing, and provider usage. It does not import graph or
extraction logic.

- `contracts.py`: request limits, registered skill references, results, and the
  `SkillClient` interface.
- `factory.py`: selects the provider client.
- `registry.py`: loads credentials and validates account-scoped registration state.
- `anthropic.py`: Claude Messages and native Skills transport.

To understand SMELTER, start with `../incremental_graph/runner.py` for stage order,
`match_rules.py` for acceptance, and `judgments.py` for prompts, completed-call
caching, evidence checks, and bounded correction retries. Those rules are shared
by transports. Extraction lives separately in `../extraction.py`.
