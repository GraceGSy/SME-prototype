# Sherlock Experiment: Judgment And Next Test

Assessed 2026-09-05 against the saved local artifacts, not a new paid model run.
The one-focus experiment was preserved in commit `5dd9496` before cleanup.

## Judgment

**Useful diagnostic, not a successful validation of a generalized SME method.**
One-focus calls improve isolation and auditability, but the saved judgments still
contain source-grounding and role-consistency failures. More matches would not,
by itself, establish improvement.

The reviewed local artifacts are ignored, not portable tracked fixtures:

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
2. **Inconsistent abstraction:** some rationales accept broad truth-revelation
   roles while others demand an exact conversational beat. The test lacks an
   adjudicated level of abstraction.
3. **Participant-role mismatch:** comparing Holmes securing the snake with
   villains deciding to murder someone as neutralizing danger overlooks who is
   acting, who is threatened, and the direction of the causal relation.
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

In this implementation, structural singletons can be reconsidered before the
paragraph pass. Later paragraphs are compared with existing paragraph nodes;
there is no general pass that rematches all old unmatched paragraph pairs.
A third paper can therefore create new correspondences without repairing the
original mistakes. It cannot turn Watson's question into Holmes's answer.

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

The domain-neutral prompt revision in this cleanup asks for center evidence and
preserved participant roles, and removes narrative-only/batched instructions.
Its semantic effectiveness is **unvalidated**. Deterministic tests cover
contracts and graph behavior; real users and live-model quality remain separate
evaluation requirements.
