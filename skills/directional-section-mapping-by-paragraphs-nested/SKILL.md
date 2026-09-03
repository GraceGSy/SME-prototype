---
name: "directional-section-mapping-by-paragraphs-nested"
description: "Selects the single best structural-role match, or none, between one focus unit or node and a supplied candidate list. Sections and subsections are peers for matching; paragraph calls are limited to one exact section or subsection node."
---

# Directional Graph Matching

Use this Skill for one directional pass of the incremental node graph. The caller supplies one `focus`, every allowed `candidate`, and a fixed `scope`. Return one target ID or `null`. The reverse direction is a separate call.

## Evidence

- Compare function in the paper's argument, not topic or vocabulary.
- Different subject domains are expected and are never, by themselves, a reason to reject a role match. If two units do the same structural job, do not disqualify them because their concrete content differs.
- Read the complete text and question metadata for the focus and every candidate.
- Questions are reliable evidence but never identity. Complete text wins when a question is too narrow or conflicts with the source.
- A candidate node represents all of its members. Judge the node from the complete evidence of every member, not from its generated node question alone.
- Sections and subsections may match at any level: section-to-section, section-to-subsection, subsection-to-section, or subsection-to-subsection.
- In a structural rerepresentation call, the focus is a singleton group and every candidate is an established non-singleton group. This pass is one-way and does not require a reciprocal selection.
- For paragraph calls, trust the supplied exact structural-node scope. Do not infer or select a candidate from its parent, children, siblings, or wider family.

## Decision

Choose the single candidate with the strongest complete-role correspondence. Return `null` when no candidate is a defensible match. Never split one focus across multiple candidates and never choose a merely topical or least-bad match.

The caller's JSON schema is authoritative. Return exactly:

```json
{
  "target_id": "one supplied candidate ID, or null",
  "basis": "brief evidence-grounded explanation"
}
```

Do not create questions, graph edges, or nodes. Those are separate pipeline stages.
