# Narrative XHTML

Use only structural markers present in the XHTML. Never infer a boundary from
plot, time, location, speaker, point of view, topic, or whitespace.

1. Read the XHTML source once and identify its narrative content container.
2. Each explicit `h3` division is a top-level section. If there is no `h3`, use
   one top-level section named from the story's `h2` title.
3. Each `hr` divides its top-level section into scenes. `n` separators create
   `n + 1` scene subsections. Number them `Scene 1`, `Scene 2`, and so on in
   document order, continuing across titled divisions. Scene numbers are
   metadata; the boundaries come only from `hr` elements.
4. If a top-level section contains an `hr`, put all of its prose in scene
   subsections and use an empty top-level `paragraphs` array. If it has no `hr`,
   create no scenes and keep all its prose in the top-level array.
5. Preserve each prose paragraph in reading order, including paragraphs inside
   block quotes. Strip inline XHTML while retaining its text.
6. Exclude navigation, headings, colophon material, and other document chrome.

A leading, trailing, or consecutive `hr` is an input-integrity error; do not
fabricate an empty scene. If the document has no `hr` anywhere, do not invent
scenes.
