# Few-shot role matching: legal pair

## Change and checks

Prompt change: `7b27f19`. Four invented demonstrations live in `pipeline/incremental_graph/prompts/shared/role-matching-examples.md`: cross-topic rule application, capability versus evaluation, prediction versus evidence with neighbor leakage, and a corresponding causal dependency. Two demonstrate matches and two abstentions. They contain no passages from the legal, HCI, or Sherlock evaluation corpora.

All six directional matching templates include the same fixed placeholder. The prompt renderer expands it into the existing cacheable instruction block and includes its contents in the prompt hash. No generic inclusion framework, output normalization, acceptance-rule changes, question-generation changes, or native Skill edits were introduced. Actual decoding remains restricted to actual candidate handles, not example handles.

TDD: the new tests first failed without the shared examples and rendering support. After implementation, `python -m unittest discover -s tests` passed all 102 tests. Tests cover every matching direction, exclusion from question generation, balanced/schema-valid demonstration outputs, separate held-out evidence, prompt-hash invalidation, missing-file rejection, and invalid demonstration handles in live output schemas.

## Live sanity check

Four separate invented pairs in `tests/fixtures/role_matching_holdout.json` were judged in both directions through the real provider and native match-role Skill. Expected labels were not passed to the model. These are small author-constructed checks, not an independently adjudicated benchmark.

- Seven of eight directional target decisions matched expectations.
- A reverse judgment falsely matched a scheduling-board evaluation to a capabilities description, citing shared participants and the fact that only one candidate was available. The forward direction correctly abstained.
- Both positive pairs were reciprocal and both negative pairs were not: four of four final pair decisions were correct under the existing reciprocal rule.
- The initial strict directional gate stopped the launcher. After inspecting the failure, the legal run was allowed to proceed on the correct reciprocal outcomes. The failure is retained; this was not a perfect directional pass or a pre-registered stopping rule. No examples or expected labels were changed in response to the failure.
- Eight paid responses cost an estimated $0.1166871. The inspected check was reused from its completed-call cache when launching the legal run, without buying another set of judgments.

Evidence: `output/legal-fewshot-holdout-20260910/results.json`, its `cache/`, and the initial `output/legal-opinions-section-fewshot-pair-20260910.stderr.log`.

## Legal rerun

Run: `runs/legal-opinions-section-fewshot-pair-20260910`, revision-0001. Banuelos-Jimenez followed by Core Optical, section granularity. Identical fresh content-only inputs to the preceding section-only baseline, including all 65 paragraph IDs and their text/order; saved input hash `b3d656ee70423420b206292d65cd39840620ba9e3eb39be724837b02ac0dd1b3`. Questions and judgments were regenerated in a separate run cache. Personal API key; combined local token threshold $5 with $1 reserve.

Policy hash: `0feffdaa423762c1d19990b82f997a76d583cd51cf716a494d6ed61255cedeb5`.

| Metric | Section-only baseline | Section-only with examples |
| --- | ---: | ---: |
| Shared structural groups | 3 | 3 |
| Shared paragraph groups | 2 | 3 |
| Paragraphs in shared groups | 4 | 6 |
| Singleton paragraph groups | 61 | 59 |
| Banuelos-Jimenez paragraphs exposed to comparison | 4 / 15 | 13 / 15 |
| Core Optical paragraphs exposed to comparison | 15 / 50 | 33 / 50 |
| Total paragraph comparison coverage | 19 / 65 | 46 / 65 |
| Paragraph matching judgments | 19 | 46 |
| Paid responses | 107 | 135 |
| Estimated run token cost | $1.6012902 | $2.1138551 |

All 55 real matching judgments contained the examples; the 80 question-generation judgments did not. All 135 graph judgments completed without validation failure, normalization, or retries. Both output datasets passed strict viewer validation; the browser displayed three shared groups and 59 singleton questions.

Rerun usage: 190,087 uncached input tokens, 429,811 cache-creation tokens, 1,833,868 cache-read tokens, 29,238 output tokens. Cache reads were 74.74% of total input tokens. Combined check plus rerun cost: $2.2305422. Estimates use the repository token-rate helper and exclude native tool fees and unreported usage; they are not provider-enforced caps or invoices.

## Interpretation and remaining risks

The main analysis sections now align, opening all 40 of their paragraphs to comparison. The additional shared paragraph group links passages stating statutory criteria: Banuelos-Jimenez's cancellation/crime-of-violence criteria and Core Optical's quotation of the invention-assignment exception. The other two groups represent opinion-opening summaries and final disposition; the latter again uses Core Optical's full concluding sentence rather than its separate terminal label. These are plausible role correspondences, not human-validated equivalences.

Topic-sensitive abstention persists: Core Optical's background chose null even while its explanation recognized the analogous factual/procedural role (`attempt-000026`); the reverse direction selected it. Consequently, the two Banuelos-Jimenez background paragraphs and 11 Core Optical background paragraphs were not compared. Core Optical's separate six-paragraph standards section also remained unmatched. Nineteen paragraphs were unexamined, not demonstrated differences.

Rationale fidelity is also imperfect. The accepted reverse analysis judgment (`attempt-000032`) incorrectly characterized both sections as performing a force-clause categorical-approach analysis, although Core Optical concerns contract interpretation. The later comparison of competing interpretations is more plausible, but a valid target ID does not validate all claims in its explanation.

Conclusion: larger comparison coverage and one additional plausible paragraph alignment, but few-shot examples have not eliminated topical vetoes or inaccurate explanations. One fresh stochastic rerun cannot isolate their causal effect from regenerated questions and model variation. HCI was not rerun. Investigate these residual judgment errors before treating the prompt as validated across domains.

Detailed read-only comparison: `output/legal-fewshot-comparison-20260910.json`. Raw evidence and candidate pools remain in the run's revision `provenance/` and `stages/` directories. Earlier runs are unchanged.

Viewer: <http://127.0.0.1:8073/?run=legal-opinions-section-fewshot-pair-20260910&revision=latest>
