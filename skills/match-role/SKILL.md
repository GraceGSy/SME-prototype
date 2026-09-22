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

- Judge role first, relational structure second, content similarity last.
  Role means the job the passage performs in its context: for example, posing
  a problem, supplying evidence, justifying a decision, or resolving a threat.
  Structure means how participants, claims, evidence, and consequences relate,
  not paragraph length, formatting, or location. Content similarity means shared
  vocabulary, entities, or topic, not whether you should read the source text.
  Read the text first to establish the role; topical similarity cannot rescue
  a role mismatch. Apply this priority across academic, legal, and narrative text.
- Read all supplied source text. Generated questions are fallible summaries,
  not identity and not substitutes for the underlying evidence.
- Sections and subsections are peers for structural matching. Paragraphs are
  restricted to the exact structural node supplied by the caller.

## Decision

Choose the strongest defensible correspondence, not the least-bad candidate.
Return `null` when there is none. Different domains alone do not justify
abstention; a very broad shared theme alone does not justify a match.

In `basis`, state the shared role first and explain the corresponding
participants and relations.
Choose the abstraction level using judgment, not a fixed taxonomy, and make
that choice intelligible on both sides. Similar formatting or topic alone is
insufficient.

Keep the final `basis` concise: target at most 100 words for a match and 60
words for an abstention. For an abstention, identify the decisive role mismatch
instead of cataloguing every candidate or quoting every member. For a match,
explain member coverage compactly; do not weaken the
per-paper role and member-contribution checks to shorten the answer.

Participant correspondence is relational, not moral: a hero can map to a villain
if each occupies the same role in the chosen relation. Different names, moral
status, or subject domains are not vetoes. But a mapping must preserve who acts
on whom and the relevant causal direction. Do not swap agent and recipient,
or claim that posing a question supplies the answer, to manufacture a match.

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
