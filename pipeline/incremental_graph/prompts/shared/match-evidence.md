## Authoritative response contract

The caller's schema replaces the Skill's older two-field output examples.
Return exactly target_id, basis, and evidence. Keep the same role-first selection
criteria and concise basis. Evidence verifies attribution, not shared wording:
quotes from the two sides need not use the same words.

For a match, evidence.focus and evidence.target are arrays of short verbatim
quotations. Supply exactly one quote per member in that side's supplied members
order; a single unit has an array of length one. Each quote must occur in that
specific paragraph_under_consideration.full_text (or actual structural unit's
full_text). Never quote a neighbor or another member in its place. Resolve
full_text_refs before quoting. Copy punctuation, capitalization, and whitespace
exactly; choose a short contiguous excerpt, preferably 3-12 words, at most 240
characters. Do not insert ellipses, normalize, paraphrase, or concatenate spans.

For target_id null, return evidence: {"focus": [], "target": []}. Do not invent
a target for an abstention. Exact quotations do not make different roles match,
and different topics do not make corresponding roles incompatible.
