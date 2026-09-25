# Five-story Sherlock corpus

Content-only inputs for whole-story-scoped **paragraph matching**. The whole story
is one scope, not one matching unit. Source paragraphs are kept intact; paragraphs
are not turned into artificial sections. No generated questions or old matching
results are included.

| Insertion order | Story | Words | Paragraphs |
| --- | --- | ---: | ---: |
| 1 | A Scandal in Bohemia | 8,526 | 259 |
| 2 | The Redheaded League | 9,144 | 215 |
| 3 | The Adventure of the Blue Carbuncle | 7,827 | 214 |
| 4 | The Adventure of the Speckled Band | 9,812 | 251 |
| 5 | The Adventure of the Beryl Coronet | 9,717 | 222 |
| Total | | 45,026 | 1,161 |

These well-known stories have a longest/shortest word-count ratio of 1.25.
The order follows their order in the collection. Word counts use whitespace
splitting, not model tokenization. Similar word lengths do not imply equal
paragraph counts or equal matching costs.

## Source and fidelity

Source: [Standard Ebooks, The Adventures of Sherlock Holmes](https://standardebooks.org/ebooks/arthur-conan-doyle/the-adventures-of-sherlock-holmes),
pinned [source revision](https://github.com/standardebooks/arthur-conan-doyle_the-adventures-of-sherlock-holmes/tree/48ec456ea50987a81f564821457b9fb32cc2bfc6).
`raw/` contains the five source XHTML files. `provenance.json` records each URL,
raw/content SHA-256 digest, and counts.

The stored content was prepared once from literal XHTML paragraph elements,
including quoted letters and signatures, in reading order. Inline text is
preserved; outer whitespace, heading markup, and scene separators are omitted.
The one-time preparation script was retired; its commit remains in Git history.
The graph consumes the prepared files directly. The other Sherlock corpus
remains unchanged.

Fresh here means newly prepared source-only inputs and newly generated questions
in a separate run, not stories unseen during the model's training. Familiarity
with Sherlock is a limitation of this experiment, not eliminated by fresh inputs.

The [dated run-readiness report](../../../docs/history/sherlock-five-readiness.md)
documents an earlier cost analysis, not a current budget or launch procedure.
