# Sherlock corpus

`raw/` contains the five pinned Standard Ebooks XHTML sources. `content/`
contains the corresponding canonical Claude Skill extractions. Every story has
real `<hr>` scene separators; the extraction names the resulting spans `Scene
1`, `Scene 2`, and so on without inferring narrative boundaries.

Review an extraction by opening its `*.content.json` beside the matching XHTML.
The required checks are paragraph fidelity and order, exclusion of book chrome,
and scene changes occurring only at `<hr>` elements. Validate all five without
an API call:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/sherlock/manifest.yaml
```
