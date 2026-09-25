# Legal corpus

`raw/` contains five opinion text files and their five paired dissent text
files. Each UTF-8 file contains only one authored body, beginning at the
authoring judge's attribution. Case captions, counsel lists, running headers,
and page numbers are excluded. Published line wrapping and printed structural
headings remain for the Claude extraction Skill.

The text was extracted once, without an LLM, from these public combined
decisions. The explicit author attribution and published page boundary define
each opinion/dissent split.

| Case | Public decision | Opinion pages | Dissent pages |
|---|---|---:|---:|
| Banuelos-Jimenez v. Garland | [Justia](https://law.justia.com/cases/federal/appellate-courts/ca6/22-3331/22-3331-2023-05-10.html) | 1-7 | 8-14 |
| Core Optical Technologies, LLC v. Nokia Corporation | [Justia](https://law.justia.com/cases/federal/appellate-courts/cafc/23-1001/23-1001-2024-05-21.html) | 3-23 | 25-26 |
| Lamb v. Kendrick | [Justia](https://law.justia.com/cases/federal/appellate-courts/ca6/21-3390/21-3390-2022-10-26.html) | 2-15 | 16-22 |
| Porter v. Board of Trustees of North Carolina State University | [Justia](https://law.justia.com/cases/federal/appellate-courts/ca4/22-1712/22-1712-2023-07-06.html) | 3-19 | 20-43 |
| Westmoreland v. Butler County | [Justia](https://law.justia.com/cases/federal/appellate-courts/ca6/21-5168/21-5168-2022-03-24.html) | 2-12 | 13-33 |

All ten opinions and dissents already have prepared content. Reuse these files;
the graph pipeline never extracts them again. New legal documents use the
explicit `pipeline.extraction` command with `--domain legal`.

Historical provenance: the first `porter_dissent` extraction omitted four final
body paragraphs after page-spanning footnotes. Those source paragraphs were
restored once under printed subsection `II.C`. This is not a runtime repair
path. New text extraction has a final-passage presence check, which is not a
complete fidelity assessment.

On 2026-09-10, `porter_opinion` was re-extracted with the unchanged native Skill
from PDF-layout text prepared during corpus curation. The previous
plain-text input had lost paragraph indentation. The refreshed content has 38
paragraphs instead of 14; the flagged 1,235-word unit is now a 149-word paragraph,
and the longest paragraph is 321 words. All 37 independently detected indented
PDF paragraph starts match the new boundaries. Body/footnote word counts match
the refreshed source after excluding printed headings and the author attribution.
The sole post-extraction curation removed that attribution from the introduction.
The response ID, usage, source hashes, and checks are recorded in
`content/porter_opinion.content.provenance.json`; the old content remains in Git
history. These checks apply to Porter, not to the other nine prepared documents.

Legal extraction uses only printed Roman-numeral and capital-letter divisions.
It does not infer doctrinal or topical sections. A document with no printed
division remains one `Opinion` or `Dissent` section.

Both graph manifests explicitly use `max_granularity: subsection`, as in the HCI
experiment. Printed subsections participate in structural alignment before the
unchanged paragraph pipeline runs within their assigned groups. Documents without
subsections retain their printed section structure; no divisions are invented.
The next planned legal experiment is the five opinions, before the dissents.

**Dissent repair completed:** the [2026-09-10 audit and repair](../../docs/history/legal-extraction-audit-20260910.md)
corrected merged paragraphs in Banuelos-Jimenez, Porter, and Westmoreland.
The corpus now contains 180 dissent paragraphs. All source words are retained
in the three repaired files, with judge metadata removed and source-verified
footnote boundaries/continuations restored once. Native responses and curation
provenance are preserved. The runtime still rejects malformed documents; no
repair adapter was added. This is not an exhaustive transcription certification.

The [historical five-opinion offline preflight](../../docs/history/legal-opinions-preflight-20260910.md)
is not a cost ceiling for a new run. No paid legal graph had started at the time
of that report.

After all ten files exist, validate the two content corpora without API calls:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/legal/opinions.manifest.yaml
python -m pipeline.incremental_graph.cli validate datasets/legal/dissents.manifest.yaml
```
