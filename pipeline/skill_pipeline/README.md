# Canonical document pipeline

This is the single extraction, question-generation, and pairwise-matching
pipeline for both HCI papers and Sherlock Holmes stories. Claude Skills make
language judgments. Python fixes stage order, IDs, candidate construction,
coverage, validation, retry, checkpointing, and provenance.

## Contract

Every document is the same nested JSON array described in
[`DATA_CONTRACTS.md`](../../DATA_CONTRACTS.md). Content and question-annotated
files have identical structure; questions add only
`question_this_text_answers`.

Stable IDs are derived from position, never generated text:

- `s0001` is the first section.
- `s0001.ss0001` is its first subsection.
- `s0001.ss0001.p0001` is that subsection's first paragraph.

The two matching stages use the same candidate and match schemas. Their only
structural difference is the configured `view`: `sections` excludes subsection
candidates, while `sections_and_subsections` includes them.

## Configure

Edit [`pipeline.yaml`](pipeline.yaml) to change ordered stages, Skills, model,
documents, question subsets, matching pairs, candidate views, or output paths.
The runner contains no extraction, question, or matching judgment.

HCI inputs are already-extracted canonical JSON. Sherlock inputs are pinned
XHTML files and are sent to the configured extraction Skill; Python never
infers narrative scene boundaries.

## Run

From the repository root:

```powershell
$env:ANTHROPIC_API_KEY = "your-key"
python -m pipeline.skill_pipeline.runner --dataset sherlock --stage extraction
python -m pipeline.skill_pipeline.runner --dataset sherlock --stage questions
python -m pipeline.skill_pipeline.runner --dataset sherlock --stage section_matching
python -m pipeline.skill_pipeline.runner --dataset sherlock --stage section_and_subsection_matching
```

Replace `sherlock` with `hci`, or use `--dataset all --stage all`.

Generated files live under `runs/document-pipeline/results/<dataset>/`:

```text
<document>.content.json
<document>.questions.json
<document-a>--<document-b>.<matching-stage>.json
```

Each matching-stage file holds both directions in one envelope. It is updated
atomically after every valid source batch, so reruns resume from source IDs
already present. `--force` deliberately starts each selected artifact again.
Use `--force` after changing a source file, Skill, model, or candidate view;
ordinary reruns assume an existing validated artifact is the intended
checkpoint.
`runs.jsonl` records model, response, Skill version/hash, input/output hashes,
and batch provenance; `errors.jsonl` and rejected responses preserve failures.
