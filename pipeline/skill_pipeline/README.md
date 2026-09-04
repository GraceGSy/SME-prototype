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
file in its container. The Skill has one short entrypoint and bundled domain
guides, so it reads only the selected narrative, legal, or academic rules and
never searches for a sibling Skill absent from its container.

Every call uses the YAML execution policy. One judgment makes exactly one
Messages API request containing the pinned Skill and complete input. The adapter
never appends Claude's response to a client-managed conversation: `pause_turn`
fails with recorded usage instead of causing a follow-up request. The defaults
use low effort, disable adaptive thinking, cap generated tokens and accepted
input-token usage, clear old server-tool results after 50,000 input tokens while
retaining the two newest tool uses, and reject oversized prompts and attachments.
The SDK's retries are also disabled.

The fixed system prefix has an explicit five-minute cache breakpoint. When the
prefix meets the model's cache-size threshold, this caches the stable tool/Skill
prefix across nearby calls. It also enables Anthropic's automatic caching of
code-execution results inside its server-side loop. Per-document content remains
after that breakpoint. Matching uses one
stable output schema; deterministic validation, rather than per-call schema
enums, enforces candidate IDs. Identical complete judgments are additionally
served from the harness's durable content-addressed cache without an API call.

Usage and the exact call policy are written to `runs.jsonl`; a limit failure is
written to `errors.jsonl` with the usage observed before the harness stopped. A
separate process-wide budget stops the command before it can silently issue more
than 100 responses or exceed the configured cumulative input/output ceilings.
These local ceilings cannot undo the cost of the one in-flight request. Keep a
workspace spend limit in the Anthropic Console as the account-level backstop.

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
