# Sherlock corpus

`raw/` contains the five pinned Standard Ebooks XHTML sources. `content/`
contains the corresponding canonical Claude Skill extractions. Every story has
real `<hr>` scene separators; the extraction names the resulting spans `Scene
1`, `Scene 2`, and so on without inferring narrative boundaries.

`whole-story/` is a deterministic derivative for graphing. Each file contains
the same paragraphs in the same order, but places them directly in one
top-level section and has no subsections. Its manifest sets
`max_granularity: paragraph`, which creates one shared corpus root and skips
section questions, section matching, and structural rerepresentation.

The manifest is ordered by first publication: `speckled_band`,
`wisteria_lodge`, `bruce_partington_plans`, `lady_frances_carfax`, then
`illustrious_client`. The graph consumes exactly the entries in the supplied
manifest, in that order; it does not silently limit a run to two stories.

For the first two complete stories only, use
`whole-story/first-two.manifest.yaml`. This explicitly selects The Speckled Band
then Wisteria Lodge (503 paragraphs total), not the old last-15-paragraph slice:

```powershell
python -m pipeline.incremental_graph.cli start datasets/sherlock/whole-story/first-two.manifest.yaml runs/sherlock-first-two
```

Review an extraction by opening its `*.content.json` beside the matching XHTML.
The required checks are paragraph fidelity and order, exclusion of book chrome,
and scene changes occurring only at `<hr>` elements. Validate all five without
an API call:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/sherlock/manifest.yaml
python -m pipeline.incremental_graph.cli validate datasets/sherlock/whole-story/manifest.yaml
```

Whole-story preparation was performed once. Its helper remains in
`helpers/prepare_content_corpus.py` for explicit future use, never runtime
normalization. Read [the experiment assessment](../../docs/sherlock-experiment.md)
before using graph outputs as evidence of method quality.
