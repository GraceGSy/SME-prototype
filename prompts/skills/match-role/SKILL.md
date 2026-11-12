---
name: "match-role"
description: "Select one role-corresponding candidate for one focus unit or graph node, or abstain."
---

# Directional Role Matching

Compare one focus unit or node with the supplied candidates. Apply the caller's
shared-role and evidence contracts.
The reverse judgment is a separate request. Do not batch, invent candidates,
generate role statements, or mutate the graph.
Choose independently; do not predict the reverse vote or select a singleton
merely because it chose this group. Adjacency alone is insufficient for a match.

## Input And Candidate IDs

Read all supplied paper blocks together. Only the labeled focus and candidates
are being compared. Return the option label exactly as supplied (for example,
"Group A" or "Paragraph B"). A context-only passage cannot be selected. Member numbers specify quote
order within a group, not semantic similarity. Positions are not output IDs.

## Matching Rules

Read and apply `references/selection.md`. That file owns the semantic selection
policy shared by this Skill and the Jev selector.

## Decision

Return `null` for an abstention.

When the caller supplies `fixed_target_id`, Jev has already selected the target.
Return that exact value; do not select a different candidate or change it to null.
Document the selection using source-bound quotations and a faithful explanation.
Report unsupported aspects honestly rather than inventing a rationale. This mode
documents a selection; it is not another selector or a semantic approval gate.

In `basis`, state the shared role first and explain the corresponding
participants and relations.
Make the chosen abstraction level intelligible on both sides.

Keep the final `basis` concise: target at most 100 words for a match and 60
words for an abstention. For an abstention, identify the decisive role mismatch
instead of cataloguing every candidate or quoting every member. For a match,
explain member coverage compactly; do not weaken the
per-paper role and member-contribution checks to shorten the answer.

Singleton rerepresentation uses the same reciprocal top-1 rule at both levels.
After each document insertion, each singleton selects its best eligible
established node or null, and each established node independently selects its
best eligible reciprocal-core singleton or null. The reverse pool contains all
eligible core candidates, not only proposers. Mutual choices establish cores;
at most one new reciprocal core joins each group per pass. At paragraph level
only, an immediately adjacent singleton that selects the group may join as
fan-in beside an accepted core, including one from its own paper. Fan-in cannot
chain through another fan-in member. The caller checks adjacency and membership;
do not infer them from prose. Section nodes never admit fan-in.

These local judgments are not a global SME alignment. Do not claim that a
candidate has passed one-to-one relational consistency or systematicity checks.
