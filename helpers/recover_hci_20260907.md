# One-Time HCI Recovery

User authorized the exact correction `corpusstudio-s0003` -> `s0003` on
2026-09-07 to preserve the current experiment. This helper is not imported by
the graph pipeline and does not implement a general prefix normalizer.

The source is `runs/hci-first-two-content-20260907`, revision 0002. It contains
206 completed judgments. The rejected response was not saved before the old
validator raised: only the selected ID survives in `failure.json`. The helper
therefore records an explicitly manual, ID-only recovery with no original
rationale, response ID, or usage claim. It never fabricates Claude's explanation.

Run `python -m helpers.recover_hci_20260907` for an offline replay that checks
all 206 source judgments still match their context, prompt, schema, and candidate
pool, then validates the exact correction against a unique eligible candidate.
Add `--execute` to continue with native Skills and the updated ID instructions.
Use the authorized personal key only in the process environment.

Output goes to `runs/hci-first-two-content-20260907-recovered`; the original run
is unchanged. The output has `recovery.json`, `correction.json`, copied inputs,
new judgment cache, and a standard revision export under `revision/`. It is a
**mixed-policy diagnostic**, not a clean benchmark or a normal resumable run.
Do not feed it to the ordinary `add` or `retry` commands. Its source Skill hashes
remain attached to reused responses; they are not relabeled as fresh judgments.

This exception preserves work from the current experiment only. New experiments
still start with content-only documents and empty judgment caches.
