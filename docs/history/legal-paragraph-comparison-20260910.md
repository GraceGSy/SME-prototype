# Legal pair: paragraph-only matching

## Setup and verification

Run: `runs/legal-opinions-paragraph-fewshot-pair-20260910`, revision-0001. Same two opinions in the same order: Banuelos-Jimenez, then Core Optical. Baseline: `runs/legal-opinions-section-fewshot-pair-20260910`, revision-0001.

The existing `helpers.prepare_content_corpus --whole-section` preparation mode copied all paragraphs into one synthetic section per opinion. No original paragraph was split, merged, deleted, or text-normalized. All 15 and 50 paragraphs retain their exact text and source reading order. Original nested inputs remain unchanged. Derived positional paragraph IDs differ; `source-map.json` in the completed run maps every derived ID to its original paragraph and top-level section ID.

The graph uses the existing paragraph-only path with a deterministic shared document root. This root is a comparison container, not evidence of a semantic section alignment. It skips all structural judgments but runs the existing paragraph matching, reconciliation, group-question generation, and singleton realignment stages. Neighbor windows now cross former section boundaries. Fresh paragraph questions were generated from these derived inputs; old generated questions or decisions were not seeded into the run.

No production code, prompts, native Skills, model settings, or graph acceptance rules changed. Both runs have policy hash `0feffdaa423762c1d19990b82f997a76d583cd51cf716a494d6ed61255cedeb5`. Test-only commit `76f01dd` adds three regressions for lossless preparation, full-pool matching with no structural judgments, and malformed-input rejection. All 105 tests passed.

Offline rendering, with API client construction disabled, verified 65 question requests and 65 matching requests in the all-abstain workload. Forward pools contained 15 candidates, reverse pools 50. Largest synthetic rendered prompt: 66,391 characters, within existing limits. Synthetic artifacts did not seed the live run.

## Results

| Metric | Section plus few-shot | Paragraph-only plus few-shot |
| --- | ---: | ---: |
| Paragraphs exposed to comparison | 46 / 65 | 65 / 65 |
| Shared paragraph groups | 3 | 3 |
| Paragraph members in shared groups | 6 | 8 |
| Reciprocal core members | 6 | 6 |
| Adjacent fan-in members | 0 | 2 |
| Singleton paragraph groups | 59 | 57 |
| Structural matching judgments | 9 | 0 |
| Paragraph matching judgments | 46 | 65 |
| Paid responses | 135 | 133 |
| Estimated token cost | $2.1138551 | $1.8894355 |

Every paragraph appeared as the focus or a candidate in actual paragraph matching. Exposure does not mean a successful match. There were 65 fresh paragraph-question calls, 65 directional matching calls, and three shared-group-question calls. No completed-judgment cache reuse, validation failure, normalization, or retry occurred. Paragraph singleton realignment executed but had no eligible targets: all established mixed groups already contained both papers.

Usage: 159,790 uncached input tokens, 319,935 cache-creation tokens, 2,315,590 cache-read tokens, and 30,690 output tokens. Cache reads were 82.84% of total input. The Personal API key was used with the existing $5 local token threshold and $1 reserve. Cost is an estimate excluding native tool fees and unreported usage, not an invoice or provider-enforced cap.

The dataset passed strict viewer validation. The live browser displayed three shared groups and 57 singleton questions. The original section-based runs remain available in the same viewer.

## Match inspection

The three groups represent standard of review, governing eligibility/standing criteria, and final disposition. The standard-of-review alignment connects the two passages announcing de novo review. Core Optical's standards section was excluded by the previous structural gate, so this is a useful recovered correspondence. The criteria group now pairs Banuelos-Jimenez's eligibility criteria with Core Optical's standing requirements, rather than the earlier statutory quotation. The reciprocal disposition pair again connects the two full concluding sentences.

The opening-summary pair was lost. Core Optical's opening abstained because the candidates concerned a different case and legal topic (`attempt-000066`), while the reverse judgment selected that opening on shared procedural-posture/disposition role (`attempt-000122`). Thus the same topical-veto problem persists without section matching.

Two additional members joined the disposition group through the existing adjacent fan-in rule: Core Optical's last analysis paragraph about judge-versus-jury fact-finding on remand, and its costs-allocation sentence. They flank the reciprocal concluding-sentence anchor in the flattened input. These are not two additional reciprocal matches and should not be counted as clear quality gains.

The first fan-in judgment (`attempt-000112`) incorrectly attributed the focus's neighboring vacate/remand sentence to the candidate center. Inspection of the encoded request confirmed that the candidate actually contained Banuelos-Jimenez's deny-the-petition sentence. This is evidence misattribution in the model response, not a source-text substitution in the request. The costs judgment (`attempt-000114`) conflated costs allocation with final merits disposition. Those decisions were preserved, not repaired after the fact.

## Conclusion and artifacts

Paragraph-only mode removes the coverage bottleneck completely for this pair and recovers an obvious standards correspondence. It does not establish a uniformly better alignment: the number of reciprocal groups is unchanged, a previous opening alignment was lost, and the extra memberships are questionable fan-in expansions. A single fresh stochastic rerun, with broader context windows and regenerated questions, does not isolate a causal effect of removing the section gate. Nor does it establish that section alignment works only in HCI; judgment errors remain at paragraph level too.

Prepared inputs: `output/legal-opinions-paragraph-pair-20260910-inputs/`. Source-ID map: `runs/legal-opinions-paragraph-fewshot-pair-20260910/source-map.json`. Detailed comparison with original IDs: `output/legal-paragraph-comparison-20260910.json`. Raw judgments and candidate pools remain in the completed revision's `provenance/` and `stages/` directories.

Viewer: <http://127.0.0.1:8073/?run=legal-opinions-paragraph-fewshot-pair-20260910&revision=latest>
