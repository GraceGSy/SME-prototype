# One-shot corpus preparation

`python -m helpers.prepare_content_corpus MANIFEST OUTPUT [--whole-section]`
creates a content-only or whole-story derivative from valid canonical inputs.
Keep the source corpus unchanged. This helper is not imported by either runtime
pipeline, and does not accept or repair alternate document schemas.

## Five-story Sherlock experiment

- `prepare_sherlock_five.py` is the retained one-time source preparation helper.
  The committed corpus is already prepared; it refuses to overwrite it.
- `python -m helpers.preflight_sherlock_five` renders offline capacity scenarios
  without API calls. Reports are generated under ignored `output/`.
- `run_sherlock_five.py` starts or retries only with an explicit cumulative
  dollar allowance. `usage_budget.py` shares observed token-cost accounting with
  the earlier HCI helper. Neither changes the core matching contract.

Read [Sherlock readiness](../docs/sherlock-five-readiness.md) before launching:
the whole-story pools are materially more expensive than section-bounded HCI.
