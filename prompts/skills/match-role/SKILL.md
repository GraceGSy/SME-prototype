---
name: "match-role"
description: "Select one role-corresponding candidate for one focus unit or graph node, or abstain."
---

# Directional Role Matching

Compare one focus unit or node with the supplied candidates. Apply the caller's
shared-role and evidence contracts.
The reverse judgment is a separate request. Do not batch, invent candidates,
generate questions, or mutate the graph.
Choose independently; do not predict the reverse vote or select a singleton
merely because it chose this group. Adjacency alone is insufficient for a match.

## Input And Candidate IDs

The user message may split the input across text blocks: shared `scope` and
`candidates` come first, and the single `focus` comes last. Read them together
as one request. The pool is complete and already filtered by the caller.

Copy the selected candidate's output handle exactly, using these input shapes:

| Candidate shape | Field to copy into `target_id` |
|---|---|
| Has an outer `selection_id` (paragraph matching or singleton realignment) | Outer `selection_id` |
| Structural graph node with `group_id` and `members` | Outer `group_id` |
| New structural unit with `paper_id` and `section_id` | Outer `section_id` |

Never use a member's ID, the focus ID, `paper_id`, `parent_unit_id`, `family_id`,
a label, an ordinal, or a generated question as the output handle. IDs are
opaque output handles, never semantic evidence: do not concatenate, prefix,
trim, reformat, or reconstruct them.
For example, a candidate with `paper_id: "corpusstudio"` and
`section_id: "s0003"` must be returned as `"s0003"`, NOT
`"corpusstudio-s0003"`. This example is not an additional candidate.

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
