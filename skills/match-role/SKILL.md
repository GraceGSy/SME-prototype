---
name: "match-role"
description: "Select one structurally corresponding candidate for one focus unit or graph node, or abstain."
---

# Directional Role Matching

The caller supplies exactly one `focus`, the complete allowed `candidates`,
and a fixed `scope`. Return one `target_id` and one evidence-grounded `basis`.
The reverse judgment is a separate request. Do not batch, invent candidates,
generate questions, or mutate the graph.

## Evidence

- Compare the relation or function performed in the document, not shared
  vocabulary, entities, topic, title, or position. The same rule applies to
  academic arguments, legal reasoning, and narratives.
- Read all supplied source text. Generated questions are fallible summaries,
  not identity and not substitutes for the underlying evidence.
- A node represents all its members. A candidate must fit their shared role;
  do not select it because one member resembles the focus.
- Sections and subsections are peers for structural matching. Paragraphs are
  restricted to the exact structural node supplied by the caller.
- In paragraph windows, neighbors may resolve a reference or explain context.
  The matched function must be performed by the center text itself. A question
  does not become an answer merely because its neighbor answers it.
- Selection IDs are opaque output handles, never semantic evidence.

## Decision

Choose the strongest defensible correspondence, not the least-bad candidate.
Return `null` when there is none. Different domains alone do not justify
abstention; a very broad shared theme alone does not justify a match.

In `basis`, identify evidence in both centers (or the actual structural units),
state the relation/function being compared, and explain who plays each role.
Keep the abstraction equally specific on both sides. Do not equate opposing
participant roles, reversed causal direction, asking with answering, or causing
harm with preventing harm just by choosing a broader label.

Structural rerepresentation compares a singleton with established non-singleton
nodes in one direction; the caller deliberately does not require reciprocity
for that pass. All other acceptance rules are applied by deterministic code
after these independent judgments.

The caller's JSON schema is authoritative. For example, an abstention is:

```json
{"target_id": null, "basis": "No candidate performs the focus unit's relation or function."}
```

These local judgments are not a global SME alignment. Do not claim that a
candidate has passed one-to-one relational consistency or systematicity checks.
