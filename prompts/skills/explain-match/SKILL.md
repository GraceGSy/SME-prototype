---
name: "explain-match"
description: "Document a fixed Jev selection with source-bound evidence."
---

Jev selected the supplied target. Explain what the texts support; do not
choose a target or infer why Jev chose it.

In basis, state what each passage does and which specific role or relationship
they share. If they share only a topic or support only part of the proposed
correspondence, say so plainly. Do not change the selected ID.

Use source text, not generated questions. For paragraphs, neighbors clarify
meaning but only the center is evidence. For groups, read each paper's accepted
members together; identify any paper that does not support the correspondence.

Return target_id (copy fixed_target_id), a brief basis, and evidence with focus
and target arrays. In each array give one short contiguous verbatim quote per
member, in input order, from that member's center or structural text. Keep each
quote within 240 characters. Quotes may document differences; do not repeat
them in basis.
