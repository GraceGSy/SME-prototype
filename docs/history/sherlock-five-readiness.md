# Sherlock five-story readiness

Prepared 2026-09-09. **No paid API calls have been made for this run.**
Do not launch until the user approves a total dollar allowance and confirms the
personal account is funded. Credentials and provider balance were not checked
by the offline preflight.

## Experiment

Use `datasets/sherlock/famous-five/manifest.yaml`: five content-only stories,
1,161 source paragraphs, one whole-story scope per document. Generate fresh
concise role questions. Start with the first two stories, then insert the other
three in manifest order, within one five-story start operation. Existing native
Skills, role-first decisions, reciprocal top-one matching, source evidence, and
per-insertion paragraph singleton realignment are unchanged. No old question
inputs or completed-judgment cache are supplied.

Paragraph-only mode removes section gates, not paragraph matching. Treating every
paragraph as a section would instead activate a different hierarchy and is not
this experiment. Short dialogue turns and signatures remain separate units and
may validly fail to align; semantic coherence is not guaranteed by their printed
paragraph boundaries. This run tests that limitation rather than silently
merging or discarding source units.

## Offline checks and capacity

`python -m helpers.preflight_sherlock_five` renders the real prompts and deduplicated
evidence, with API-client construction forbidden. Its report goes to ignored
`output/sherlock-five-preflight.json`, never into the matching cache.

| Synthetic incoming alignment | Primary matching calls | Largest rendered prompt (characters) |
| --- | ---: | ---: |
| 0% | 3,262 | 756,333 |
| 50% | 2,602 | 675,990 |
| 100% | 1,938 | 595,173 |

The synthetic scenarios use 20-word placeholder questions and ordinal groupings,
not model decisions or expected match rates. They probe the largest focus in
each of eight directional insertion pools. Counts exclude 1,161 paragraph-question
calls, group-question regeneration, singleton realignment, and retries. They are
not complete upper bounds, especially for the later realignment pools.

The ordinary 500,000-character request guard is too small even with evidence
deduplication. The 3,000-response allowance is also insufficient. The dedicated
launcher therefore uses these explicit run-local guards:

| Guard | Allowance |
| --- | ---: |
| Prompt characters | 900,000 |
| Aggregate input-usage tokens per response | 1,000,000 |
| Responses per process | 12,000 |
| Aggregate input-usage tokens per process | 1,000,000,000 |
| Output tokens per process | 20,000,000 |

These are stop conditions, not spend targets or automatic escalations. The
separate observed-dollar guard is tighter. Default repository limits and
generation settings remain unchanged. Native Skill input usage can include
multiple internal passes; it is not the same as simultaneous context size.
[Sonnet 5 has a one-million-token context window](https://platform.claude.com/docs/en/models/overview).
Character probes are not provider token counts and do not prove every future
request will fit. Any exceeded guard requires inspection before retry.

## Cost warning

The earlier five-paper HCI run had 459 paragraphs and a recorded token-cost
estimate of $36.23. This corpus has 2.53 times as many paragraph units, and the
whole-story candidate pools are not bounded to HCI sections. HCI's price is not
a useful budget ceiling for this run.

At three characters/token, two to three input passes, and an **optimistic** mix
of 95% cache reads, 2% five-minute cache writes, and 3% uncached tokens, the
primary-matching **input-only** sensitivities are:

| Synthetic alignment | Two input passes | Three input passes |
| --- | ---: | ---: |
| 0% | $159.79 | $239.69 |
| 50% | $132.79 | $199.19 |
| 100% | $104.36 | $156.54 |

These exclude all output, paragraph/group questions, singleton realignment,
retries, and tool fees. They are neither expected totals nor upper bounds.
Across the prior HCI matching response records, the observed cache-read share
of aggregate input was approximately 82.5%, not 95%. At that lower hit rate,
input alone can be substantially more expensive. A full unrestricted run may
cost several hundred dollars; a $25 or HCI-sized top-up is not a credible
completion budget. Actual cost must be calibrated during execution before
promising a total.

Rates verified against [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing):
Sonnet 5 is $2/M uncached input, $10/M output, $2.50/M five-minute cache writes,
$4/M one-hour writes, and $0.20/M cache reads. Native code-execution charges
depend on container hours and organization allowances, which saved token usage
does not establish. No web tools are added to alter billing.

Candidate pools and scope are already stable cache prefixes; only focus changes
within a directional pass. Full-text chunks are deduplicated without dropping
evidence. Native Skills stay native. Exact completed judgments are reused on
retry. API prompt caches are temporary, so retrying later can require new cache
writes even when local completed judgments are reused. Offline rendering cannot
verify the provider's actual hit rate.

## Launch and recovery

From the repository root, after explicitly selecting the authorized personal
credential and setting `$ApprovedBudget` to the agreed **total** allowance:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/sherlock/famous-five/manifest.yaml
python -m helpers.preflight_sherlock_five
python -m helpers.run_sherlock_five start --budget-usd $ApprovedBudget
```

The run path is `runs/sherlock-famous-five-20260909`. Start refuses an existing
directory. The launcher freezes the scoped configuration through the normal run
API. It records every saved paid response, including rejected outputs, and stops
before another call when observed token cost leaves less than a $3 reserve.
`budget.json` records that estimate and whether the last attempted call supplied
usage. The reserve is not a provider-enforced hard cap; unknown usage and tool
fees remain outside it. Do not launch another process against the same run.

Inspect failures rather than automatically repairing responses, broadening
schemas, raising limits, or changing policy. Reconcile unknown billed attempts
with the provider before resuming. A transport error can lack usage even when
the provider did work. Completed cached judgments are replayed by:

```powershell
python -m helpers.run_sherlock_five retry --budget-usd $ApprovedBudget
```

Retry's allowance is cumulative, not additional dollars. Monitor recorded
cost, response counts, real cache reads/writes, failed attempts, per-insertion
realignment, and active stage. Review question concision and source fidelity
before trusting later matches. Stop and discuss a materially worse cost rate
rather than spending through an optimistic estimate. There is no new recurring
monitor or paid process until launch is authorized.

After completion, validate the export and inspect all five stories in the run
viewer. Passing deterministic tests establishes orchestration and contracts,
not the quality of live Claude judgments or cross-domain theoretical validity.

Preparation verification: canonical manifest validation passed; the full Python
suite passed 90 tests, including source/hash fidelity, offline capacity, and a
mocked paid-failure test proving the dollar guard stops the next call. No live
generation or provider cache-hit test was performed.
