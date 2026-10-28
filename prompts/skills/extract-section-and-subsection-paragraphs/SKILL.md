---
name: "extract-section-and-subsection-paragraphs"
description: "Extracts source-backed sections, subsections, and paragraphs from an academic PDF plus section manifest, narrative XHTML with explicit divisions, or one judicial opinion or dissent in plain text. Produces the same strict nested JSON contract for every domain."
---

# Extract Section and Subsection Paragraphs

The request names exactly one mode. Read only its directly bundled guide:

- Narrative XHTML: `NARRATIVE.md`
- Judicial opinion or dissent text: `LEGAL.md`
- Academic PDF plus nested section manifest: `ACADEMIC.md`

Do not look for or invoke another Skill. The relevant guide and the supplied
source are the complete task context.

The caller supplies a strict structured-output schema and writes the result.
Read the source, then return the JSON value directly. Do not create, reread, or
attach an output file. Do not return a prose summary.

## Canonical output

Return one array of top-level sections in source order:

```json
[
  {
    "section_name": "string",
    "section_number": "string or null",
    "paragraphs": [
      {"paragraph_number": 0, "text": "string"}
    ],
    "subsections": [
      {
        "section_name": "string",
        "section_number": "string or null",
        "paragraphs": [
          {"paragraph_number": 0, "text": "string"}
        ]
      }
    ]
  }
]
```

Use exactly these fields. `section_number` is a string or `null`.
`paragraph_number` is an integer starting at `0` independently in every
`paragraphs` array. Use `[]`, never `null`, when a section, lead-in, or
subsection has no prose. Preserve source wording and reading order, normalizing
only markup, line wrapping, hyphenation artifacts, encoding artifacts, and
whitespace needed to form plain paragraphs.

When `subsections` is empty, a top-level section's `paragraphs` contains all of
that section's prose. When `subsections` is non-empty, it contains only prose
before the first subsection. Do not add questions, summaries, page numbers,
word counts, warnings, or any other fields.
