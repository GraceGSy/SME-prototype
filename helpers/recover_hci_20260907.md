# HCI Dataset Rescue

User authorized the exact correction `corpusstudio-s0003` -> `s0003` on
2026-09-07 to preserve the current experiment, then authorized broader ID repair
for this dataset. The helper is never imported by the normal graph pipeline.
It removes whitespace and known HCI paper qualifiers (`.`, `-`, `:`, `/`) only
when they identify exactly one eligible candidate. It does not infer a selection
from a label, rewrite the reasoning, or choose among ambiguous candidates.

The source is `runs/hci-first-two-content-20260907`, revision 0002. It contains
206 completed judgments. The rejected response was not saved before the old
validator raised: only the selected ID survives in `failure.json`. The helper
therefore records an explicitly manual, ID-only recovery with no original
rationale, response ID, or usage claim. It never fabricates Claude's explanation.

The first continuation retained those results and the manual correction, then
completed three judgments and rejected `corpusstudio.s0001`. Its full response
and rationale are available. This rescue preserves all 210 recorded judgments
and repairs that rejected ID without modifying its original raw response or basis.

Run `python -m helpers.recover_hci_20260907` for offline replay and validation.
Add `--execute` to continue with native Skills and enum-constrained outputs.
Repeated execution creates a new revision and reuses this rescue's recorded work.
Use the authorized personal key only in the process environment. Do not launch
two copies concurrently. The previous single-correction output stays untouched.

Output goes to `runs/hci-first-two-content-20260907-rescued`; the original runs
are unchanged. The output has copied inputs, a new judgment cache, explicit
`corrections/` records, and standard exports under `revisions/revision-NNNN/`.
Each revision includes `recovery.json`. It is a **mixed-policy diagnostic**,
not a clean benchmark or a normal resumable run.
Do not feed it to the ordinary `add` or `retry` commands. Its source Skill hashes
remain attached to reused responses; they are not relabeled as fresh judgments.

This exception preserves work from the current experiment only. New experiments
still start with content-only documents and empty judgment caches.
