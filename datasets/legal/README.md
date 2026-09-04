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

`pipeline/skill_pipeline/pipeline.yaml` pins every text file by SHA-256. The
pipeline sends these files, rather than PDFs, to the configured legal extraction
Skill:

```powershell
python -m pipeline.skill_pipeline.runner --dataset legal_opinions --stage extraction
python -m pipeline.skill_pipeline.runner --dataset legal_dissents --stage extraction
```

All ten configured opinions and dissents have canonical content files. Ordinary
reruns skip them. The first `porter_dissent` response omitted four final body
paragraphs after page-spanning footnotes; those exact source paragraphs were
restored under printed subsection `II.C`, and the harness now rejects any legal
extraction that does not preserve its source's final passage.

Legal extraction uses only printed Roman-numeral and capital-letter divisions.
It does not infer doctrinal or topical sections. A document with no printed
division remains one `Opinion` or `Dissent` section.

After all ten files exist, validate the two content corpora without API calls:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/legal/opinions.manifest.yaml
python -m pipeline.incremental_graph.cli validate datasets/legal/dissents.manifest.yaml
```
