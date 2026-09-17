# One-shot corpus preparation

## Fresh section-level HCI run

`python -m helpers.run_hci_sections --budget-usd 20` starts the content-only
pair, then adds each remaining paper separately. It uses the standard graph
pipeline and a fresh run cache. The observed-cost guard reserves $3 for
uncertainty; it is not a provider-enforced cap. Inspect failures before using
`--retry`; unreported usage requires reconciliation before resuming.

## Corpus preparation

`continue_hci_excerpt_contract.py` records the one-time 2026-09-17 transition
from the paused medium-thinking HCI run to the excerpt evidence contract.
It replays and validates completed judgments offline, preserves their original
provenance and costs in a separate run, and refuses to overwrite its destination.
The result is a mixed-contract continuation, not a fresh evaluation. Normal
`run_hci_sections --run-dir runs/hci-section-medium-excerpts-20260917 --budget-usd 17.64 --retry`
continues it; the budget includes the inherited spend.

`python -m helpers.prepare_content_corpus MANIFEST OUTPUT [--whole-section]`
creates a content-only or whole-story derivative from valid canonical inputs.
Keep the source corpus unchanged. This helper is not imported by either runtime
pipeline, and does not accept or repair alternate document schemas.

`prepare_porter_layout.py` is the retained one-time Porter opinion input refresh.
It requires `pdfplumber`, preserves printed indentation, and removes verified
page-number footers. It writes a new input under `output/`, not canonical content;
the normal extraction pipeline and a separate fidelity review follow.

`audit_legal_extractions.py` uses `pdfplumber` for a read-only comparison of all
ten legal PDFs with prepared content. It writes diagnostic candidates under
`output/`; indentation flags require human review and never repair inputs.

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
