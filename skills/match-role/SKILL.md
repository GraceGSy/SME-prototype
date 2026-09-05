---
name: "match-role"
description: "Select one role-corresponding candidate for one focus unit or graph node, or abstain."
---

# Directional Role Matching

The caller supplies exactly one `focus`, the complete allowed `candidates`,
and a fixed `scope`. Return one `target_id` and one evidence-grounded `basis`.
The reverse judgment is a separate request. Do not batch, invent candidates,
generate questions, or mutate the graph.

## Evidence

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
- A node represents all its members. A candidate must fit their shared role;
  do not select it because one member resembles the focus.
- Sections and subsections are peers for structural matching. Paragraphs are
  restricted to the exact structural node supplied by the caller.
- Each paragraph window is ordered `previous_paragraph`,
  `paragraph_under_consideration`, `next_paragraph`. The neighbors are context
  only: use them to resolve references and understand the center's role, never
  as replacement evidence for it. Null neighbors mean the window boundary.
  Only `paragraph_under_consideration.full_text` is being matched. Apply this
  rule to the focus, each group member, and each candidate. A question does not
  become an answer merely because its next paragraph answers it.
- Selection IDs are opaque output handles, never semantic evidence.

## Decision

Choose the strongest defensible correspondence, not the least-bad candidate.
Return `null` when there is none. Different domains alone do not justify
abstention; a very broad shared theme alone does not justify a match.

In `basis`, state the shared role first, anchor it in a short exact excerpt from
each matched center (or actual structural unit), and explain the corresponding
participants and relations. For a node, every member must support that role.
Choose the abstraction level using judgment, not a fixed taxonomy, and make
that choice intelligible on both sides. Similar formatting or topic alone is
insufficient. Before selecting, check that your explanation describes the
centers rather than just their neighbors; otherwise reconsider or abstain.

Participant correspondence is relational, not moral: a hero can map to a villain
if each occupies the same role in the chosen relation. Different names, moral
status, or subject domains are not vetoes. But a mapping must preserve who acts
on whom and the relevant causal direction. Do not swap agent and recipient,
or claim that posing a question supplies the answer, to manufacture a match.

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
