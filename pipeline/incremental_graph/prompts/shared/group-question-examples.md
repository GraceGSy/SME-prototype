## Constructed group-question examples

These invented examples illustrate abstraction, not a fixed set of roles.

### A procedure split across paragraphs

Paper A, one accepted paragraph: "Readers pin a passage and place a second
passage beside it. This lets them compare the original wording directly."
Paper B, first accepted paragraph: "The interface places selected excerpts in
two columns." Paper B, second accepted paragraph: "Keeping both excerpts visible
avoids switching screens while checking their wording."

Expected output:
```json
{"question_this_text_answers":"How does the interface support direct comparison of source passages?"}
```
Each paper explains support for comparison. B divides operation and purpose
across two accepted paragraphs; neither must repeat the other's explanation.

### Different details of an evaluation

Paper A: "We timed participants as they compared passages using each interface."
Paper B: "Readers performed the same comparison task with each tool; we recorded
completion time and errors."

Expected output:
```json
{"question_this_text_answers":"How was the tool's support for the comparison task evaluated?"}
```
Both describe evaluation procedure. Do not ask whether the tool improved
performance: neither paper supplies a result here.
