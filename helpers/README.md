# Optional preparation and inspection

The graph CLI does not import these utilities. Use them only when the input or
inspection task requires them.

- `python -m helpers.prepare_content_corpus MANIFEST OUTPUT` strips precomputed
  questions into a new content-only corpus. Add `--whole-section` to store
  each document's paragraphs under one section for paragraph-only graphing.
  The prepared output is explicit; the graph never flattens inputs at runtime.
- `python -m helpers.report_singletons EVENTS_JSON OUTPUT_DIR` regenerates a
  singleton report from saved events without making model calls. The output
  directory must not exist.

`curate_dissent_outputs.py` and `prepare_porter_layout.py` remain at their
recorded paths because the legal corpus provenance cites their exact source
edits. They are one-time historical scripts, not steps for a new run.

Other HCI recovery, cost-preflight, legal curation, and Sherlock source
preparation scripts were retired. Their commits remain in Git history. See the
[main README](../README.md) for the supported path.
