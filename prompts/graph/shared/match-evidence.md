## Authoritative response contract

The caller's schema is authoritative for every matching direction.
Return exactly one JSON object with target_id, basis, and evidence. Do not return
a list, Markdown fences, a string containing JSON, extra fields, or the string
"null". Evidence verifies attribution, not shared wording: quotes from the two
sides need not use the same words.
Put quotations only in evidence, never repeat them in basis.

Each paragraph window is ordered previous_paragraph, paragraph_under_consideration,
next_paragraph. Only paragraph_under_consideration.full_text is being matched;
neighbors are context only, not replacement evidence. Apply this to the focus,
each member, and each candidate. Null neighbors mark a window boundary.
A question does not become an answer because its next paragraph answers it.
For structural units, compare their complete source text.

For a match, evidence.focus and evidence.target are arrays of short verbatim
quotations or excerpts. Supply exactly one per member in that side's supplied
members order; a single unit has an array of length one. Evidence must come from that
specific paragraph_under_consideration.full_text (or actual structural unit's
full_text). Never quote a neighbor or another member in its place. Resolve
full_text_refs before quoting. Copy punctuation, capitalization, and whitespace
exactly. Prefer a short contiguous quotation of 3-12 words. If a longer passage
is needed, quote its first five and last five whitespace-separated words, joined
by exactly ` ... ` (space, three periods, space). Both parts must appear verbatim,
in that order, in the same center, with at least one word omitted between them.
For example, source "The wolf was blowing loudly while the brick walls held firm. And therefore the pigs survived."
permits "The wolf was blowing loudly ... And therefore the pigs survived."
This is a locator for the full passage: read the
omitted text too, and do not hide qualifications or reversals that undermine the basis.
The entire returned quotation or excerpt must fit within 240 characters, including
spaces and the omission marker. Do not paraphrase, normalize, or join different centers.

For target_id null, return evidence: {"focus": [], "target": []}. Do not invent
a target for an abstention. Exact quotations do not make different roles match,
and different topics do not make corresponding roles incompatible.
