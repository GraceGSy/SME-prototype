---
name: "directional-section-mapping-by-paragraphs-nested"
description: "Selects the single best structural-role match, or none, between one focus unit or question group and a supplied candidate list. Sections and subsections are peers for matching; paragraph calls are limited to a precomputed section family."
---

# Directional Graph Matching

Use this Skill for one directional pass of the incremental question-group graph. The caller supplies one `focus`, every allowed `candidate`, and a fixed `scope`. Return one best candidate ID or `null`. The reverse direction is a separate call.

## Evidence

- Compare function in the paper's argument, not topic or vocabulary.
- Read the complete text and question metadata for the focus and every candidate.
- Questions are reliable evidence but never identity. Complete text wins when a question is too narrow or conflicts with the source.
- A candidate question group represents all of its members. Judge the group from the complete evidence of every member, not from its generated group question alone.
- Sections and subsections may match at any level: section-to-section, section-to-subsection, subsection-to-section, or subsection-to-subsection.
- For paragraph calls, trust the supplied family scope. Do not infer or select a candidate outside it.

## Decision

Choose the single candidate with the strongest complete-role correspondence. Return `null` when no candidate is a defensible match. Never split one focus across multiple candidates and never choose a merely topical or least-bad match.

The caller's JSON schema is authoritative. Return exactly:

```json
{
  "best_match_id": "one supplied candidate ID, or null",
  "reason": "brief evidence-grounded explanation"
}
```

Do not create questions, graph edges, groups, or classifications. Those are separate pipeline stages.
