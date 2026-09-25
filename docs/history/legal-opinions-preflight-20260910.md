# Five-opinion offline cost preflight

Date: 2026-09-10. No graph, Skill, generation, or token-count API calls.

## Decision

The opinions are substantially smaller than the whole-story Sherlock workload.
The five measured workload scenarios project **$4.51-$7.70 in token charges**
if the calls behave like the completed HCI run. For planning, allow **$15-$20**
and stop to inspect actual spending after the first pair before continuing.
This is a reserve recommendation, not a guaranteed ceiling or authorization to
spend. No paid legal graph has been started.

The input set contains 173 paragraphs, 22,522 words, and 31 structural units
(24 sections plus 7 printed subsections). HCI had 459 paragraphs and 45,835 words.
Legal paragraphs average about 130 words versus HCI's 100, but there are far
fewer of them, and matching remains bounded by aligned section/subsection scope.

## Measured scenarios

| Synthetic structural selection | Synthetic paragraph selection | Unique judgments | HCI-calibrated token cost | No prompt-cache sensitivity |
| --- | --- | ---: | ---: | ---: |
| No matches | No matches | 292 | $4.51 | $11.70 |
| Even ordinals | Even ordinals | 481 | $7.27 | $19.00 |
| All compatible ordinals | All compatible ordinals | 541 | $7.70 | $19.66 |
| All compatible ordinals | No matches | 507 | $7.28 | $18.78 |
| All compatible ordinals | Even ordinals | 542 | $7.61 | $19.52 |

These are artificial workload probes, not predicted match rates. In particular,
the all-unmatched case performs no cross-document paragraph matching because
its structural units never share a scope. It is not a useful-result forecast.
Matching ordinal numbers is NOT introduced into the actual algorithm.

All generated prompts fit the existing 500,000-character guard. The largest
probe was a structural matching request with 151,157 characters. Applying the
HCI aggregate input-volume ratio suggests roughly 110,000 input tokens for that
call, below the default 200,000-token guard. This is not an API token count or
a guarantee against a future native Skill iteration exceeding the guard.
No limits were raised. Estimated total input volume was 5.6-9.2 million tokens
across the synthetic runs, below the 30-million session guard; judgments were
below the 3,000-response guard, assuming one response per judgment as typical
in the HCI calibration. Provider continuation responses can change that.

## Method and limits

`python -m helpers.preflight_legal_opinions` invokes the existing graph runner
and evidence/prompt encoder on the real content-only opinions with subsection
granularity. It starts the first two, then simulates appending each remaining
opinion. Each revision reloads fresh content; exact completed-request
fingerprints are reused across revisions. Synthetic graphs are temporary and
cannot seed a real run. Constructing an API client fails closed in this helper.

The probe replaces only the judgment provider with fixed generic questions and
ordinal-based selections. The runner still performs its normal reciprocal
reconciliation, group questions, paragraph scope assignment, and eligible
singleton checks after insertions. Synthetic singleton checks return no match;
accepted realignment merges and their additional questions are not modeled.
The HCI saved matching-policy hash still matches current code, prompts, Skills,
configuration assets, and dependencies. No production module or native Skill
was edited for this preflight.

Calibration reads 1,182 unique successful HCI matching responses and 752 question
responses. It uses observed input cost per rendered character and output cost
per judgment, separately for questions and matches. Their observed cache-read
shares were 82.4% and 67.3%, respectively. Native Skill/tool iteration token
overhead is included insofar as it appears in those saved usage totals. The
different legal prose and pool sizes can change tokenization and cache reuse.

The no-prompt-cache column charges the same estimated input volume at the
uncached rate. It still reuses completed judgments locally; it does not mean
rerunning paid judgments on every append. Neither column includes extraction
already completed, retries, tool fees, or unreported provider usage. Neither is
a bound on different grouping outcomes, changed questions, or repeated failures.

Rates were checked against [Anthropic's pricing table](https://platform.claude.com/docs/en/about-claude/pricing):
Sonnet 5 input $2, five-minute cache writes $2.50, one-hour writes $4, cache reads
$0.20, and output $10 per million tokens. The helper shares the existing
`helpers/usage_budget.py` rates, rather than duplicating a pricing implementation.

Detailed generated measurements: `output/legal-opinions-preflight-20260910.json`.
Before a paid run, agree a budget, use fresh content-only inputs, retain the
existing matcher and native Skills, and reuse the saved response ledger on retries.
