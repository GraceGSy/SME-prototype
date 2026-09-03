# Claude Skills comparison harness

This package is the deterministic harness for testing document extraction,
question generation, and two interchangeable matching Skills. Claude makes the
language judgments; Python fixes the call order, candidate coverage, schemas,
validation, caching, retry behavior, and provenance.

It does not build or mutate the incremental graph. Validated matching output is
kept separate so graph rules can be changed without rerunning Claude.

## Configure

Edit `pipeline.yaml` to select:

- ordered stages and their Skill keys;
- input documents and matching pairs;
- section-only or section-and-subsection candidate views;
- model, batch size, validation attempts, cache directory, and output directory.

The configured corpora are five source-separated Sherlock Holmes stories and
the Examplore/CorpusStudio HCI pair. HCI starts from checked-in JSON. Sherlock
starts from pinned XHTML and uses the extraction Skill; Python never infers
narrative scene boundaries.

The graph pipeline and this comparison harness deliberately use different
nested matching Skills:

- `directional-section-mapping-by-paragraphs-nested` selects one best candidate
  or none for an incremental graph call.
- `directional-document-mapping-by-paragraphs-nested` compares two complete
  documents and preserves multiple legitimate correspondences.

## Run

From the repository root:

```powershell
$env:ANTHROPIC_API_KEY = "your-key"
python -m pipeline.skill_pipeline.runner --dataset sherlock --stage extraction
python -m pipeline.skill_pipeline.runner --dataset sherlock --stage questions
python -m pipeline.skill_pipeline.runner --dataset sherlock --stage section_matching
python -m pipeline.skill_pipeline.runner --dataset sherlock --stage section_and_subsection_matching
```

Replace `sherlock` with `hci`, or use `--dataset all --stage all`. Existing
validated files and candidate batches are reused. Use `--force` only when every
completed call should be repeated. After changing a Skill, source, or candidate
view, use `--force` or a fresh `output_dir`; file existence controls reuse.

Generated files live under `runs/skill-pipeline/results/` and are intentionally
ignored by Git. `runs.jsonl` records model, response, Skill version/hash, input
and output hashes, and normalization details. `errors.jsonl`, rejected outputs,
and raw responses retain failed or normalized attempts for inspection.
