# Structural cross-paper matching pipeline

Extracts a hierarchical structure (sections → paragraphs) from a set of academic
papers, tags each unit with a free-text question describing its role, cross-matches
those tags between papers, groups the resulting links, and visualizes everything in
an interactive HTML viewer.

Loosely inspired by Gentner's Structure-Mapping Engine (structural alignment between
papers), but implemented as a much simpler tag-matching pipeline rather than a full
entity/proposition graph aligner. (An earlier, more literal SME-style attempt lives in
`schema.py` / `extract_graph.py` / `align_graphs.py` / `align_trace.py` / `cli.py` and
`viz/index.html` / `viz/align_viewer.html` — **not used by the current pipeline**,
kept only for reference. Everything below is the active pipeline.)

## Setup

```bash
pip install -r requirements.txt
```

Requires an Anthropic API key with available credit:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

(The scripts read this from the environment directly via the `anthropic` SDK — there's
no `.env` loading in the code, so `export` it in your shell, or `source` a `.env` file
yourself before running.)

Optionally override the model used for extraction/summarization calls (defaults to
`claude-sonnet-5`):

```bash
export SME_EXTRACT_MODEL=claude-sonnet-5
```

## Input papers

The pipeline expects PDFs in `SME/papers/`. Three example papers are checked in
there already:

```
SME/papers/examplore_chi18.pdf
SME/papers/mesotext.pdf
SME/papers/paralib_uist22.pdf
```

To use your own papers, drop PDFs into `SME/papers/` and either edit each script's
`DEFAULT_PAPERS` list or pass paths explicitly, e.g. `python3 extract_sections.py
my_paper.pdf`. The paper's filename stem (minus `.pdf`) becomes its `paper_id`
throughout the pipeline and viewer.

## Running the pipeline

Run these **in order** from `SME/pipeline/`. Each step reads the previous step's
output from `output/sections/`, so later steps will silently do nothing useful (or
crash) if run out of order.

```bash
# 1. Extract each paper's high-level sections + a free-text role tag per section.
#    One Claude call per paper.
python3 extract_sections.py

# 2. Fill in each section's actual text by slicing the raw PDF text locally.
#    No API call. MUST run before step 3, and MUST be re-run any time step 1
#    is re-run (extract_sections.py resets section text to "").
python3 attach_section_text.py

# 3. Extract paragraphs within each section, each with its own free-text tag
#    plus prev/next discourse-relation tags, plus the id of the section it
#    came from (section_id -- local bookkeeping, not a model output). One
#    Claude call per section.
python3 extract_fine_grained.py

# 4. For every section/paragraph, find its top-3 most similar tags in each
#    OTHER paper (directional candidates). No API call -- pure lexical
#    similarity. -> tag_matches.json
python3 match_tags.py

# 5. Prune to only bidirectional (mutual top-3) matches. No API call.
#    -> bidirectional_matches.json
python3 prune_bidirectional.py

# 6. Group linked quotes into connected components (transitive), filtered to
#    a per-granularity similarity threshold before grouping. No API call.
#    -> quote_groups.json
python3 group_matches.py

# 7. For each paragraph group, ask Claude what overarching research question
#    unifies its members -- given each member's own question, its actual
#    paragraph text, AND its parent section's question (not the section's
#    content). One Claude call per group. Writes back onto quote_groups.json.
python3 summarize_groups.py

# 8. Match paragraph-group summary questions against each other (top-3 each),
#    then prune to bidirectional. No API calls. -> group_matches.json,
#    bidirectional_group_matches.json
python3 match_groups.py
python3 prune_group_bidirectional.py

# 9. Group the paragraph-groups themselves into super-groups (connected
#    components over the bidirectional group matches, threshold-filtered).
#    No API call. -> group_of_groups.json
python3 group_groups.py

# 10. Ask Claude what overarching question unifies each super-group's member
#     questions. One Claude call per super-group. Writes back onto
#     group_of_groups.json.
python3 summarize_super_groups.py
```

Steps 1, 3, 7, and 10 are the only ones that call the Claude API. All of them cache
their responses to disk (per paper/section/group id, under
`output/sections/_cache/`) and check the cache before calling again — safe to re-run
a script after a crash or after running out of credit; already-completed items are
skipped. To force a full re-run of a step, delete its cache subdirectory first (and
remember step 2's note above about re-running `attach_section_text.py` after step 1).

Anthropic prompt caching (`cache_control: ephemeral` on the system prompt) is also
used within steps 1/3/7/10 so that repeated calls in one run only pay full price for
the first call.

### Optional: iterative paragraph-group refinement

After step 7, `refine_paragraph_groups.py` can be run to refine the paragraph
groups further, independently of steps 8-10 above:

```bash
python3 refine_paragraph_groups.py
```

This is a clustering-style refinement loop, repeated `N_ITERATIONS = 5` times:

1. **Reassign**: for EVERY paragraph in EVERY paper (not just ones already in a
   group), ask Claude to pick whichever *current* group's `overarching_question` it
   fits best -- a single Claude call per paragraph, returning one group_id directly
   (not a score per candidate; this keeps output small and cheap, and the candidate
   question list lives in the cached system prompt, so it's only paid for once per
   iteration, not once per paragraph). A paragraph that started out ungrouped can
   join a group here; a paragraph already in a group can be moved to a
   better-fitting one. The number of paragraphs that changed group is printed each
   iteration.
2. **Re-summarize**: recompute `overarching_question` for each surviving group from
   its new membership (reusing `summarize_group()` from step 7, same enriched
   prompt), discarding the old question. Groups that lost every member are dropped.

Every Claude call (both the per-paragraph assignment calls and the per-group
resummarization calls) is cached per iteration under `output/sections/_cache/`, and
each iteration's full result is saved to `output/sections/paragraph_groups_iter<N>.json`
before moving to the next — resuming after a crash or a fresh credit top-up skips
everything already done and continues from the last completed iteration; re-running
after full completion makes no Claude calls at all. The final result is written to
`output/sections/paragraph_groups_refined.json`.

This is one of the more expensive steps by call count (`paragraphs × N_ITERATIONS`
calls — e.g. ~236 paragraphs × 5 iterations ≈ 1,180 calls on the example papers),
though each call's output is tiny (a single group_id, ~36 output tokens). An earlier
design asked for a numeric fit score against every candidate group in one array
response; that made the model occasionally degenerate into a long run of malformed
entries (~10-15% of calls) and cost roughly 10x the output tokens per call, so it
was replaced with this direct single-choice version. `assign_paragraph()` still
retries up to `MAX_ASSIGN_ATTEMPTS = 2` times if a call comes back with no valid
group_id at all, and leaves the paragraph unassigned for that iteration (printed
clearly) if both attempts fail.

`quote_groups.json` itself is left untouched by this step — it stays the step 6/7
baseline. **Note:** the viewer's Groups tab currently reads `quote_groups.json`, not
`paragraph_groups_refined.json`, and the refined groups don't carry a `links` field
(the original bidirectional links no longer correspond to arbitrary post-refinement
membership) — visualizing the refined groups would need a follow-up viewer change.

### Output files

Everything lands in `output/sections/`:

| File | Produced by | Contents |
|---|---|---|
| `<paper_id>.json` | extract_sections.py, attach_section_text.py, extract_fine_grained.py | one paper's sections + paragraphs, each with `id`, `title`, `tag`, `text`, `prev_relation`, `next_relation`; paragraphs also have `section_id` (their parent section's id) |
| `manifest.json` | extract_sections.py | `[{paper_id, title, file}, ...]` for every paper in `output/sections/` |
| `tag_matches.json` | match_tags.py | directional top-3 tag candidates per unit, per granularity |
| `bidirectional_matches.json` | prune_bidirectional.py | mutual-match links only, per granularity |
| `quote_groups.json` | group_matches.py, summarize_groups.py | connected-component groups of linked quotes (sections + paragraphs); paragraph groups also get an `overarching_question` |
| `group_matches.json` | match_groups.py | directional top-3 similar groups per paragraph group |
| `bidirectional_group_matches.json` | prune_group_bidirectional.py | mutual-match links between paragraph groups |
| `group_of_groups.json` | group_groups.py, summarize_super_groups.py | super-groups of paragraph groups, each with an `overarching_question` |
| `paragraph_groups_iter<N>.json` | refine_paragraph_groups.py | snapshot of `{meta: {reassigned, total_assigned}, groups: [...]}` after refinement iteration N |
| `paragraph_groups_refined.json` | refine_paragraph_groups.py | final refined paragraph groups after all iterations (no `links` field — see note above) |

`output/sections/_cache/` holds the raw per-item Claude responses (safe to delete to
force a re-run; safe to commit or ignore, your call — it's just a speed/cost
optimization, not required output).

## Viewing the results

Serve `SME/pipeline/` over HTTP (the viewer fetches JSON via `fetch()`, which won't
work from a `file://` URL) and open the viewer:

```bash
python3 -m http.server 8743 --directory SME/pipeline
```

then open `http://localhost:8743/viz/tag_matches_viewer.html` (this is the current,
active viewer — `viz/sections_viewer.html` is an earlier iteration kept for
reference; `viz/index.html` and `viz/align_viewer.html` belong to the old
entity/proposition pipeline mentioned above, not this one).

The viewer has three tabs:
- **Section** / **Paragraph** — columns of quotes (one column per paper), with
  bidirectional matches drawn as curved links between them. Hover a quote to preview
  its links; click to pin it and re-align the other columns so linked quotes land on
  the same row; click a quote's "expand" hint to toggle its full text independently
  of pinning.
- **Groups** — a node-link tree: top-level nodes are super-groups (click to expand
  into their member paragraph-groups, shown with arced similarity links between
  siblings); click a group node to expand it into a 3-column quote view (same
  link-drawing/hover/expand behavior as the Section/Paragraph tabs), showing that
  group's actual member quotes and the links between them.

Both tabs share a **preview length** slider (how much quote text to show before
truncating) and a **min similarity** slider (filters out weaker links/arcs below the
chosen threshold).

If you edit the viewer HTML/JS and don't see changes reflected, hard-refresh or
append a cache-busting query string (`?t=2`) — browsers can cache the HTML file
itself, not just the JSON it fetches (which already requests `cache: "no-store"`).

## Tuning knobs

- `TOP_K = 3` in `match_tags.py` / `match_groups.py` — how many candidate matches to
  keep per unit/group before bidirectional pruning.
- `SIMILARITY_THRESHOLDS` in `group_matches.py` (`0.33` sections, `0.45` paragraphs)
  and `SIMILARITY_THRESHOLD = 0.33` in `group_groups.py` — links below this score are
  dropped *before* connected-components grouping, to keep groups from collapsing into
  one giant blob on a dense link graph. Raise these if groups still look too broad;
  lower them if you're getting too many tiny/singleton groups.
- Similarity itself (`text_similarity()` in `align_graphs.py`) is a 50/50 blend of
  Jaccard word-overlap and character-level sequence similarity — cheap and
  dependency-free, no embeddings or extra API calls involved.
