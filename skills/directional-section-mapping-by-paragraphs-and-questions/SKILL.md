---
name: "directional-section-mapping-by-paragraphs-and-questions"
description: "Maps every source section to all defensible target-section role correspondences, or none, using complete paragraphs and question metadata."
---

# Directional Section Matching

The caller supplies `source_candidates` and `target_candidates` in one canonical
candidate format. Every candidate is a whole section with a stable `unit_id`,
complete ordered `paragraphs`, and `question_this_text_answers` metadata.

## Judgment

For every source candidate, compare its full evidence against every target
candidate. Match document role, not shared topic, vocabulary, names, or section
numbers. Treat the question as useful metadata, never identity; complete
paragraph evidence controls when the two conflict.

For narrative documents, compare narrative functions such as establishing the
mystery, introducing evidence, redirecting the investigation, confronting a
suspect, explaining the solution, or closing the case.

A source may have multiple defensible target correspondences. Emit one record
per correspondence. If none is defensible, emit exactly one record with a null
`target_id`. Never emit both null and non-null records for the same source.

## Output

Return every supplied source ID at least once, using exactly this record shape:

```json
{
  "source_id": "one supplied source unit_id",
  "target_id": "one supplied target unit_id, or null",
  "basis": "brief evidence-grounded explanation"
}
```

The API schema wraps records in `{"matches": [...]}`. Do not generate
questions, alter identifiers, or add fields.
