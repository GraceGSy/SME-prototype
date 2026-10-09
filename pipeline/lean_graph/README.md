# Lean incremental question-group graph

A third implementation of the same idea as `pipeline/incremental_graph/`, built from
your own pseudocode, after `incremental_graph` started to feel more complicated than
necessary. The core design principle: **every deterministic operation is a plain Python
function; the LLM is only called for the two genuinely fuzzy judgments** -- "what
question does this passage/group address" and "does this passage belong with that
group." Everything else (ID generation, graph mutation, classification, caching) is
ordinary, inspectable code with no framework underneath it.

Dropped relative to `incremental_graph`, deliberately:

- **pydantic** -- plain `dataclasses` instead (`models.py`). There's one accepted input
  shape and no config/request/response objects that need runtime schema validation.
- **networkx** -- a plain `Graph` dataclass (`paper_order` / `nodes` dict / `edges`
  list). The only graph query this pipeline needs -- "does this node touch any edge" --
  is a one-line scan, not worth a graph library.
- **Dual input format support** -- only the skills pipeline's own extracted-sections
  format (`[{section_name, section_number, paragraphs}, ...]`) is accepted. If you have
  data in the other, "canonical" shape, convert it first; this pipeline won't silently
  guess which parser to run.
- **Provenance / replay / revisions / retry** -- no event journal, no immutable revision
  directories, no `retry --stage` command. `run()` always replays the full paper list
  from an empty graph; the judgment cache (below) is what keeps that cheap, not partial
  resumption.

Kept:

- The same deterministic classification formula (`graph_ops.classify`): a node is
  `common_structure` if a strict majority of eligible papers are represented,
  `alignable_difference` if it has multiple papers or any edge, else
  `non_alignable_difference`.
- The same reconciliation rule (`graph_ops.reconcile`): reciprocal picks become
  memberships; one-directional picks become a node plus a directed edge; no pick at all
  becomes an isolated node.
- A judgment cache (`judge.JudgmentCache`), so re-running after adding a paper doesn't
  re-pay for content already judged -- this is plain bookkeeping (a JSON file keyed by a
  content hash), not the provenance/replay system above.

## Files

| File | Role |
|---|---|
| `models.py` | `Paper`/`Section`/`Paragraph` and `Node`/`Edge`/`Graph` dataclasses, plus `Graph.to_json`/`from_json`. |
| `input_data.py` | `load_paper()` -- the one accepted input shape only. |
| `graph_ops.py` | `reconcile()` and `classify()` -- no LLM calls, no networkx. |
| `judge.py` | `Judge` -- the only two LLM-call sites (`generate_question`, `match_unit`), plus the cache. `anthropic` is imported lazily inside `Judge.__init__`, so this module (and `runner.py`, which imports it) stays importable without the package installed, as long as nothing constructs a real `Judge`. |
| `runner.py` | `run(papers, judge)` -- sequences steps 1-6 of the pseudocode over a paper list. Depends only on the `generate_question`/`match_unit` interface, so tests can swap in a scripted fake judge. |
| `cli.py` | `python -m pipeline.lean_graph.cli run <manifest.yaml> <graph_dir>`. |

## Running it

```bash
python -m pipeline.lean_graph.cli run \
  pipeline/incremental_graph/runs/hci-five-paper-corpus/manifest.yaml \
  pipeline/lean_graph/runs/hci-five-paper-corpus
```

Reuses the same manifest format as `incremental_graph` (a YAML list of `paper_id` /
`title` / `file`), so the manifest we already built for the other pipeline works here
unchanged.
