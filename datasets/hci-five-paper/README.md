# HCI five-paper dataset

`raw/` contains the five source PDFs. `manifest.yaml` defines the canonical
insertion order for the existing question-annotated extractions. Each root file
is named `<paper_id>.json` and contains
non-appendix top-level sections, optional subsections, paragraphs in reading
order, and precomputed `question_this_text_answers` metadata.

`content/` is the tracked content-only baseline; the root JSON files retain
precomputed questions for reproducible question-reuse tests. These are deliberate
prepared variants, not interchangeable input schemas. Precomputed questions are
not a human gold standard.

New experiments use `content/manifest.yaml`, not the question-annotated root
manifest. For the first pair only, use `content/first-two.manifest.yaml`
(AbstractExplorer, then CorpusStudio). Start in a new run directory to generate
fresh questions and judgments. Do not re-extract the unchanged source PDFs.

No preparation runs automatically. The one-shot utility is retained under
`helpers/prepare_content_corpus.py`; existing content should be reused.

The incremental graph represents every top-level section and subsection as a
structural unit. Whole-section matching evidence includes its descendants, but
each paragraph has exactly one owner. The checked-in corpus contains 52
top-level sections, 87 subsections, and 459 paragraphs.

Run the non-network validation from the repository root:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/hci-five-paper/manifest.yaml
```
