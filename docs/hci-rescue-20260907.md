# HCI rescue: 2026-09-07

## Completed dataset

The diagnostic run completed with only AbstractExplorer and CorpusStudio, in that
order, using the experiment's frozen content-only inputs. It contains all 221
paragraphs: 8 shared paragraph groups and 203 singleton questions. These are model
judgments, not validated equivalences or evidence of benchmark performance.

- Revision: `runs/hci-first-two-content-20260907-rescued/revisions/revision-0003`
- Viewer: `site/hci-first-two-rescued/public`
- Provenance: 471 attempts and 908 graph events.
- Graph hash: `66041cd3678679fe5ca10e377c97630904c6f877c934dab5f76ba2b9d486a02a`

## Repairs and boundaries

The dated helper `helpers/recover_hci_20260907.py` replays completed judgments and
repairs unambiguous, dataset-specific candidate handles. It is not imported by
the normal pipeline. Original run artifacts are preserved in separate revisions.

Two previously rejected handles were repaired: `corpusstudio-s0003` to `s0003`
and `corpusstudio.s0001` to `s0001`. The first rejection's original rationale and
raw response were not retained; its manual recovery explicitly records that
limitation. The second repair preserves the original response and rationale.
Neither repair invents a new matching rationale.

Future matching responses are constrained to the request's exact candidate IDs
or null using an `anyOf` response schema. Runtime validation remains strict and
native Skills remain native. The rescue alone permits a 1024-token paragraph
matching response after a 512-token response exhausted its output budget.

This is a mixed-policy diagnostic artifact, not a clean benchmark. It preserves
completed work from this experiment; future experiments should start fresh.

## Verification

- 70 Python tests passed, including schema and isolated recovery tests.
- Viewer TypeScript build and 8 viewer tests passed.
- Packaging validated two papers and 221 paragraphs.
- Manual browser checks verified expanded original passages, all 221 Paper Map
  paragraphs, and replay through event 908, with no browser errors observed.

The successful continuation also exercised the candidate-enum schema against
the live provider. An earlier nullable type-array encoding was rejected by the
provider; the separate string-enum and null branches worked.
