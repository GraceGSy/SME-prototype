# Academic PDF and Nested Section Manifest

The request supplies a PDF and an ordered manifest of known top-level sections
and subsections. Preserve the manifest's section names and numbers. Locate those
boundaries in the PDF; do not decide new section or subsection identities.

1. Extract `pdftotext -layout` text and `pdfplumber` word positions once for the
   complete PDF. Detect recurring running headers and footers across pages and
   remove them from the body stream.
2. Verify the reading order of multi-column pages. If layout text interleaves
   columns, rebuild reading order from word coordinates per column rather than
   manually rearranging sentences.
3. Locate each manifest heading in order, rejecting table-of-contents entries,
   citations, cross-references, and running headers. A top-level section ends at
   the next top-level heading. Within it, a subsection ends at the next known
   subsection or the top-level section boundary.
4. Text before the first subsection is the top-level lead-in. A section with no
   subsections keeps all of its prose in its top-level `paragraphs` array.
5. Split each span into paragraphs by checking all three layout signals: blank
   lines, first-line indentation within a column, and extra vertical spacing
   relative to normal line leading. Join visual line wraps.
6. Exclude running chrome, page numbers, figure and table captions, chart labels,
   and non-substantive footnote markers. Keep lists together unless the source
   clearly presents separate prose paragraphs. Merge a standalone lower-level
   heading forward into the prose paragraph it introduces.
7. Check that every source span is represented exactly once and in order. The
   last subsection runs to its enclosing top-level section boundary; never move
   later text into the top-level lead-in.

Do not search for another Skill. These are the complete academic extraction
rules for this task.
