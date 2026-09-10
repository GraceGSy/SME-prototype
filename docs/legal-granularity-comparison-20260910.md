# Legal pair: section versus subsection granularity

## Setup and verification

Completed September 10, 2026. Banuelos-Jimenez followed by Core Optical; no other documents or HCI reruns.

- Baseline: `runs/legal-opinions-first-pair-20260910`, revision-0001, subsection granularity.
- Rerun: `runs/legal-opinions-section-pair-20260910`, revision-0001, section granularity.
- Identical content-only inputs, paragraph IDs, text, and order: 15 and 50 paragraphs, respectively.
- Existing section-mode loader includes descendant paragraphs under top-level sections. Original subsection data is retained in the frozen inputs. No production code, prompts, native Skills, or reconciliation policy changed.
- Both saved policy hashes: `4cf8d2ebb15a527fcafef086bdec9d3230572cab78f3ca1919f5dc4363320dc0`.
- Fresh questions and judgments, separate cache, Personal API key, existing $5 local token threshold with $1 reserve. This is not a provider-enforced spending cap.
- `python -m unittest discover -s tests`: 96 passed. Both output datasets passed strict viewer validation. Local catalog and dataset endpoints returned the completed rerun; the browser displayed two shared groups and 61 singleton questions.
- Rerun: 107 successful recorded judgments/responses, zero completed-judgment cache hits, no failure artifact or stderr output. No output normalization or retry was needed.

## Results

| Metric | Subsection baseline | Section rerun |
| --- | ---: | ---: |
| Shared structural groups | 4 | 3 |
| Shared paragraph groups | 1 | 2 |
| Paragraphs in shared groups | 2 | 4 |
| Singleton paragraph groups | 63 | 61 |
| Banuelos-Jimenez paragraphs exposed to comparison | 13 / 15 | 4 / 15 |
| Core Optical paragraphs exposed to comparison | 6 / 50 | 15 / 50 |
| Total paragraphs exposed to comparison | 19 / 65 | 19 / 65 |
| Paragraph matching judgments | 19 | 19 |
| Recorded API responses | 115 | 107 |
| Estimated token cost | $1.7928379 | $1.6012902 |

Exposure counts a paragraph appearing as the focus or a candidate in an actual paragraph-level judgment. Merely appearing as section evidence or neighboring context does not count. Empty pools for the first seed paper are expected; final exposure includes later reverse judgments against that seed.

Rerun usage: 146,723 uncached input tokens, 356,384 cache-creation tokens, 1,097,621 cache-read tokens, and 19,736 output tokens. Cache reads represented 68.57% of total input tokens. Cost uses the repository's observed Sonnet 5 token rates and excludes native tool fees or unreported usage; it is not an invoice.

## Interpretation

Section-only routing worked: all 11 Core Optical background paragraphs, formerly isolated under its two subsections, entered the matched background pool. None acquired a reciprocal paragraph match. The new accepted paragraph alignment connects the two opinion-opening summaries, which both introduce the dispute and announce its disposition.

The other shared paragraph group still represents final disposition, but its Core Optical member changed from the full concluding sentence to the separate `VACATED AND REMANDED` line. The full sentence also selected the Banuelos-Jimenez disposition; the reverse judgment preferred the terminal line. A costs paragraph lies between them, so they do not form a contiguous fan-in extension. This is not evidence of broader substantive alignment.

The major remaining bottleneck is the section judgment. Core Optical's analysis selected the Banuelos-Jimenez analysis, but the reverse judgment abstained because the candidates did not perform the same specific immigration-law analysis (`attempt-000032`). Consequently, Core Optical's 29 analysis paragraphs and Banuelos-Jimenez's 11 analysis paragraphs received no comparisons. Core Optical's separate six-paragraph standards section also remained unmatched.

Semantic consistency problems remain despite valid output schemas. One reverse background judgment rejected candidates based heavily on legal subject matter. Another returned a candidate ID while ending its explanation with a contradictory abstention (`attempt-000101`). That latter choice did not form a reciprocal match. No decisions were altered after inspection.

This is one fresh stochastic rerun, not an isolated causal estimate of granularity: regenerated questions and judgments can change independently of the setting. Structural group counts also use different candidate universes. More groups alone do not establish better quality.

## Decision

Section granularity is operationally sound and removes the confirmed subsection-routing exclusion. This run offers only a modest local improvement, not improved overall comparison coverage. Hold off on rerunning HCI until role-versus-topic judgment behavior is investigated and tested. Preserve both runs unchanged as baselines; do not label unexamined paragraphs as demonstrated non-alignable differences.

The read-only comparison audit and detailed membership evidence are in `output/compare_legal_granularity_20260910.py` and `output/legal-granularity-comparison-20260910.json`. Raw judgments and candidate pools remain in each revision's `provenance/attempts.jsonl` and `stages/` directories.

Viewer: <http://127.0.0.1:8073/?run=legal-opinions-section-pair-20260910&revision=latest>
