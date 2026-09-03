# Data contracts

The active section/subsection workflow has one source document contract, one
derived candidate contract, and one matching-output contract. Alternate flat,
pseudo-section, epoch, and question-only formats are not accepted.

This is an intentional contract reset. Start a new run directory rather than
resuming artifacts written by an older schema.

## Document

Content and question-annotated documents use the same nested JSON array:

```json
[
  {
    "section_name": "Results",
    "section_number": "4",
    "paragraphs": [
      {
        "paragraph_number": 0,
        "text": "Lead-in text.",
        "question_this_text_answers": "What frames the reported results?"
      }
    ],
    "subsections": [
      {
        "section_name": "Qualitative Findings",
        "section_number": "4.1",
        "paragraphs": [
          {
            "paragraph_number": 0,
            "text": "Finding text."
          }
        ],
        "question_this_text_answers": "What qualitative themes emerged?"
      }
    ],
    "question_this_text_answers": "What did the study find?"
  }
]
```

`question_this_text_answers` is the only question field and is optional until
question generation. Paragraph numbering is zero-based and restarts inside
each `paragraphs` array. A content file omits all question fields; a questioned
file requires the field on every section and subsection. Empty structural units
use `null`.

## Identity

Python derives IDs from array positions:

```text
s0001
s0001.p0001
s0001.ss0001
s0001.ss0001.p0001
```

Questions, titles, and section numbers are metadata, not identity. IDs remain
unchanged when that metadata changes. Reordering the source structure changes
IDs by design because document order is part of the representation.

## Candidate

Candidate views are created in memory and are never alternate document files:

```json
{
  "unit_id": "s0001.ss0001",
  "unit_type": "subsection",
  "name": "Qualitative Findings",
  "number": "4.1",
  "parent_unit_id": "s0001",
  "parent_name": "Results",
  "paragraphs": [
    {"paragraph_id": "s0001.ss0001.p0001", "text": "Finding text."}
  ],
  "question_this_text_answers": "What qualitative themes emerged?"
}
```

A whole-section candidate contains its lead paragraphs followed by all of its
subsection paragraphs in source order. `sections` and
`sections_and_subsections` differ only in which candidates are included.

## Matches

Both matching Skills return the same record:

```json
{
  "source_id": "s0001",
  "target_id": "s0002.ss0001",
  "basis": "Both units report the study's qualitative findings."
}
```

`target_id` is `null` when no candidate corresponds. Multiple non-null records
for one source are allowed; mixing null and non-null records is not. Every
source must appear. One file stores both directional passes:

```json
{
  "schema_version": 1,
  "dataset_id": "hci",
  "stage_id": "section_and_subsection_matching",
  "candidate_view": "sections_and_subsections",
  "directions": [
    {
      "source_document_id": "paper_a",
      "target_document_id": "paper_b",
      "matches": []
    },
    {
      "source_document_id": "paper_b",
      "target_document_id": "paper_a",
      "matches": []
    }
  ]
}
```

## Viewer projection

The graph exporter deterministically projects the canonical documents and node
state into `manifest.json`, paper JSON files, `bidirectional_matches.json`, and
`final_snapshot.json`. Optional `graph-replay.json` adds the Graph Replay tab.
These files are UI outputs, never alternate pipeline inputs.
