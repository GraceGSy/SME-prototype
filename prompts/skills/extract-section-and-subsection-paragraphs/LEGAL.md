# Judicial Opinion or Dissent Text

The supplied UTF-8 file contains one already-separated authored opinion or
dissent. Do not perform PDF extraction or request page geometry.

1. Start at the authored body, normally marked by `OPINION`, `DISSENT`, or the
   authoring judge's attribution. Exclude captions, counsel lists, filing
   metadata, running case-name headers, page numbers, court chrome, signatures,
   and certificates.
2. A printed Roman-numeral division such as `I.` or `II. Discussion` is a
   top-level section. A printed capital-letter division such as `A.` or
   `B. Protected Speech` inside it is a subsection. Confirm headings from their
   placement and sequence; do not promote lists, citations, record references,
   footnote numbers, or sentence-initial abbreviations.
3. Preserve heading wording. Put the marker without trailing punctuation in
   `section_number`. If a marker has no title, use `Part I`, `Part II`, `Part A`,
   and so on as `section_name`.
4. Put authored prose before the first Roman-numeral division in a top-level
   `Opinion` or `Dissent` section with `section_number: null`. If there are no
   Roman-numeral divisions, use one such section for the complete authored body.
5. The schema has two structural levels. Keep lower printed divisions as text
   inside their enclosing subsection rather than creating a third level.
6. Reconstruct paragraphs from blank lines, indentation, and prose continuity.
   Do not treat each wrapped line or page-break gap as a paragraph.
7. Preserve all authored body prose, including substantive footnotes,
   quotations, and the disposition. A footnote interruption is not the end of
   the body; resume the prose after it and verify that the source's final
   authored sentence appears in the result.

Never infer sections from changes in legal issue, doctrine, speaker, or topic.
