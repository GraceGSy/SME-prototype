# Five HCI papers

`raw/` holds the source PDFs. `content/` holds one content-only canonical JSON
file per paper. `content/manifest.yaml` lists all five in insertion order;
`content/first-two.manifest.yaml` selects AbstractExplorer and CorpusStudio for
a smaller first run. The graph generates missing questions from these files.
Do not re-extract unchanged PDFs or reuse judgments from a different run.

The stored corpus has 52 top-level sections, 87 subsections, and 459
paragraphs. Source-marked subsections remain structural units; each paragraph
has one exact owner. Validate the full prepared corpus without API calls:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/hci-five-paper/content/manifest.yaml
```

An older question-annotated variant was removed from the active checkout. It
remains in Git history and is not a gold standard. See the
[main README](../../README.md) to run the content-only example.
