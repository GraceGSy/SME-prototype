# Sherlock Experiment: Judgment And Next Test

Assessed 2026-09-05 against the saved local artifacts, not a new paid model run.
The one-focus experiment was preserved in commit `5dd9496` before cleanup.

## Judgment

**Useful diagnostic, not a successful validation of a generalized SME method.**
One-focus calls improve isolation and auditability, but the saved judgments still
contain source-grounding and role-consistency failures. More matches would not,
by itself, establish improvement.

The reviewed artifacts are archived, not portable tracked fixtures. The verified
local archive is `../../archives/SME-prototype-elena-clean/20260905T185723Z/`
relative to this document's directory. It contains `runs.zip`, `site.zip`, and
`index.json` with per-file SHA-256 hashes. Originals were moved into
`originals/runs/` and `originals/site/` because deletion was blocked; generated
clutter was also moved outside the checkout. The paths below are their original
checkout locations, not active run directories:

| Run | Observed result |
|---|---|
| `runs/diagnostics/sherlock-last15-neighbor-match/graph/revisions/revision-0003` | 31 attempts; 1 shared paragraph node and 28 singleton nodes |
| `runs/studies/sherlock/graph/revisions/revision-0009` | 509 attempts; 4 shared paragraph nodes and 495 singleton nodes |

The diagnostic compared 15 final paragraphs from each of the first two stories.
These are not parallel slices: one includes live discovery/climax, while the
other includes testimony, aftermath, and debrief. The older full run used a
different matching setup. These numbers are not a controlled accuracy comparison,
and neither run has a human-labeled gold set.

## What Was Actually Broken

1. **Neighbor leakage:** attempts `attempt-000019` and `attempt-000022`
   select Wisteria Lodge `s0001.p0009`, describing it as Holmes's explanation.
   In the diagnostic input, that center is Watson's question; Holmes's answer
   is `s0001.p0010`. Correct neighboring context did not guarantee correct
   center attribution.
2. **Variable abstraction:** some rationales accept broad truth-revelation roles
   while others demand an exact conversational beat. This is not automatically a
   defect: the intended method permits LLM judgment. Evaluate whether each chosen
   abstraction is supported on both sides rather than enforcing a fixed taxonomy.
3. **Insufficiently justified role correspondence:** attempt `attempt-000023`
   compares Holmes securing the snake with villains deciding to murder someone
   as neutralizing danger. Hero-to-villain mapping is not inherently wrong; both
   could occupy an agent role in a threat-removal relation. The rationale does
   not establish that mapping carefully and describes both as immediate physical
   resolution although one is retrospective plotting. This is a disputed
   judgment to adjudicate, not proof that different moral roles prohibit analogy.
4. **Fragmented units:** a printed paragraph can contain only a question, a
   response, or part of a causal explanation. Neighbor windows help interpret
   it but do not change the unit being aligned.
5. **Local selection is not global alignment:** independent top-1 decisions can
   discard useful alternatives before consistency between relations is checked.

These are reasons to tweak representation and evaluate the method, not reasons
to indiscriminately lower the abstention threshold.

## Theoretical Backing And Limits

Gentner's structure-mapping account concerns relational correspondences, not
just shared object attributes or a common topic. Consistent mappings of relational
arguments and connected higher-order structure matter. The SME work explicitly
constructs and evaluates structural alignments; a graph of paragraphs grouped by
generated questions does not automatically supply those constraints.
See the [Northwestern SME overview](https://www.qrg.northwestern.edu/ideas/smeidea.htm)
and [Gentner's 1983 structure-mapping paper](https://groups.psych.northwestern.edu/gentner/papers/Gentner83.2b.pdf).

The current reciprocal top-1 rule is a conservative local acceptance heuristic.
It does not enforce one-to-one mapping of entities across a system of relations,
parallel connectivity, or a systematicity preference for an interconnected causal
explanation. Paragraph fan-in is an engineering accommodation for segmentation,
not the same thing as a formally justified many-to-one relational mapping.

Progressive alignment can help abstraction: easier comparisons can support later,
less superficially similar ones. That benefit is conditional on the comparisons
and representations, not on merely increasing corpus size.
See [Gentner's progressive-alignment discussion](https://onlinelibrary.wiley.com/doi/10.1111/j.1551-6709.2010.01114.x).
Sequential learning work such as SEQL compares a new exemplar with retained
generalizations and exemplars; its relational representations and comparison
process are substantive parts of the method.
See [SEQL, CogSci 2000](https://www.qrg.northwestern.edu/papers/Files/SEQL_CogSci2000.pdf).

## Will A Third Paper Fix It?

**Not reliably, and not by itself.** A third story might provide a useful bridge
when it shares a coherent relational system with both earlier stories. It can
also reinforce a mistaken abstraction.

The archived implementation ran structural singleton matching once after the
full insertion sequence, in one direction, and skipped it in paragraph-only
mode. That did not implement the intended algorithm. These Sherlock runs
therefore do not test per-insertion reciprocal realignment at paragraph level.

The corrected implementation now completes both levels after each document.
Each singleton and established group independently selects its best eligible
counterpart, and only mutual choices merge. Paragraph realignment is the same
algorithm inside one exact section node, including paragraph-only mode. Old
singletons are revisited, and structural merges preserve/reparent existing
paragraph nodes. Offline regressions demonstrate an older singleton joining a
group established by a third document before the fourth document is inserted.

This mechanism can recover a missed correspondence when common structure
emerges. It does not split an incorrectly accepted shared group or change the
source evidence. Retain top-1 reciprocity and evaluate a missed bridge, an
incorrect early group, and a no-match control before adding new machinery.
Semantic quality of the corrected algorithm remains untested with live models.

## Three Fragmentation Strategies

1. **Keep paragraphs; interpret centers in context.** Strengthen center labels
   and evidence attribution while leaving paragraph membership unchanged. This
   is the cheapest baseline and avoids segmentation errors, but a question and
   its separately printed answer still cannot be aligned as one explanatory act.
2. **Match minimal functional blocks.** Prepare a separate, stored view of
   small contiguous spans such as question/answer, claim/justification, or
   observation/inference. Preserve every original paragraph ID and exact text;
   define non-overlapping ownership for the first experiment. Start with a small
   maximum span and compare against the paragraph baseline, not automatic merging
   whenever matching fails. This can handle all three domains without a fixed
   domain-specific role taxonomy, but misses nonlocal dependencies and clauses
   with multiple roles inside one paragraph.
3. **Match explicit relational representations.** Represent predicates, argument
   bindings, and links such as causes/justifies/contradicts, each grounded in
   exact source spans. Align these relations and their connected systems rather
   than treating printed paragraphs as the basic units. This is closest to
   Gentner's representation and systematicity assumptions, but adds extraction
   errors and consistency machinery. It is an experiment, not a reason to
   resurrect the deleted proposition pipeline.

Strategy 3 is the closest theoretical fit; strategy 2 is my best practical
hypothesis across narrative, academic, and legal data, not a measured result.
Test strategy 1 first with the revised prompts, then strategy 2 only on failures
where the intended function actually spans a paragraph boundary. Keep canonical
source extraction unchanged and store any accepted derived representation once.

## Smallest Useful Next Experiment

1. Select a small reviewable set from narrative, academic, and legal documents,
   including clear matches, genuine no-matches, and hard counterexamples.
   Agree on annotation rules before measuring output.
2. Annotate center evidence, relation/function, participant roles, causal
   direction, and justified abstraction level. Allow multiple defensible
   candidates where the task genuinely permits them.
3. Compare the frozen one-focus baseline with the revised domain-neutral,
   center-grounded prompt. Hold documents, candidate pools, and model settings
   fixed. Score center attribution, role correctness, false positives,
   abstention, and cost separately.
4. If segmentation remains the dominant error, test small reversible functional
   blocks with original paragraph IDs retained as provenance. Do not silently
   merge or rewrite the canonical source.
5. If incompatible local choices remain, test a minimal explicit relation/role
   representation and a small candidate set checked for global consistency.
   Do not build a generalized solver before this comparison justifies it.
6. Only then test third-document additions and insertion-order permutations.
   Measure whether bridges repair adjudicated failures, not just whether the
   shared-node count rises.

The revised prompts prioritize role, relational structure, then content similarity.
Here content similarity means topic/vocabulary overlap, not ignoring source
meaning; relational structure is not document formatting. Matching windows now
render in previous/under-consideration/next order rather than alphabetical order.
The basis asks for exact center excerpts and corresponding relational roles,
while permitting differing moral status and judgment about abstraction level.
Its semantic effectiveness is **unvalidated**. Deterministic tests cover
contracts and graph behavior; real users and live-model quality remain separate
evaluation requirements.
