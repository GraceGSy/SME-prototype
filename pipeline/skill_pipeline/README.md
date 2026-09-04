# Canonical document pipeline

This is the single extraction, question-generation, and pairwise-matching
pipeline for HCI papers, Sherlock Holmes stories, and judicial opinions. Claude Skills make
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
documents, question subsets, matching pairs, candidate views, execution limits,
or output paths. The runner contains no extraction, question, or matching
judgment.

HCI inputs are already-extracted canonical JSON. Sherlock inputs are pinned
XHTML files. Legal inputs are UTF-8 text files containing one authored opinion
or dissent. XHTML and legal text inputs are sent to the configured extraction
Skill; Python never infers narrative or legal boundaries. Each corpus keeps
tracked `raw/` and `content/` artifacts.

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

To continue from content through the incremental graph and packaged viewer with
no manual manifest handoff, run:

```powershell
python -m pipeline.study --dataset sherlock
```

Use `--dataset all` only after every configured corpus has been reviewed. It
also creates the participant-routed study package. Pairwise matching remains an
independent diagnostic stage because its many-to-many document comparison is
not a valid graph-insertion input.

Question and matching files live under `runs/document-pipeline/results/<dataset>/`.
Content files live in each dataset's configured tracked `content_dir`:

```text
<document>.questions.json
<document-a>--<document-b>.<matching-stage>.json
```

Each matching-stage file holds both directions in one envelope. It is updated
atomically after every valid source batch, so reruns resume from source IDs
already present. `--force` deliberately starts each selected artifact again.
The nested stage batches up to ten remaining source candidates, rather than
repeating the complete target pool for every individual source. The current
Sherlock pair therefore needs one request per direction.
Extraction returns schema-constrained JSON directly; the deterministic harness
validates and writes it. Claude is never asked to create and reread an output
file in its container.

Every call uses the YAML execution policy. The checked-in defaults use low
effort, disable adaptive thinking, set an advisory server-side task budget, cap
generated tokens and accepted input-token usage, clear stale tool results, reject
oversized prompts and attachments, and permit no automatic `pause_turn`
continuation. The SDK's own retries are also disabled. Usage is aggregated over
every explicitly permitted continuation and written beside the exact call
policy in `runs.jsonl`; a budget failure is written to `errors.jsonl` with the
usage observed before the harness stopped. A separate process-wide budget stops
the command before it can silently issue more than 100 responses or exceed the
configured cumulative input/output ceilings.

Anthropic's task budget is advisory. The hard local ceilings can prevent a
continuation or later request, but they cannot undo the cost of an in-flight
server-tool response already returned by Anthropic. Keep a workspace spend limit
in the Anthropic Console as the final account-level backstop.

Matching validation also makes one attempt per batch. Invalid structured output
is preserved for inspection and fails the command instead of triggering another
charged call with the same prompt.

A failed command can be rerun from the last validated checkpoint without
duplicating completed calls. Never raise a limit or use `--force` merely because
a call exhausted its budget; inspect the prompt, Skill behavior, and recorded
usage first.
Use `--force` after changing a source file, Skill, model, or candidate view;
ordinary reruns assume an existing validated artifact is the intended
checkpoint.
`runs.jsonl` records model, response, Skill version/hash, input/output hashes,
and batch provenance; `errors.jsonl` and rejected responses preserve failures.
