# Architecture And Maintenance

## What The System Does

The goal is to expose cross-document correspondences that ordinary topical
similarity may miss: two passages about different subjects can perform a similar
explanatory, evidential, causal, or discourse function. Questions summarize these
functions for inspection; they are not node identities or proof of equivalence.

The current implementation delegates local semantic judgments to an LLM and
keeps acceptance rules deterministic. This separation makes a mistaken judgment
auditable without hiding graph mutations inside a model response.

## Extraction

`pipeline.extraction.extract_document` validates a raw source request, registers
one extraction Skill, and makes one structured request. The requested domain
selects the source-specific extraction instructions. It validates the returned
nested content, rejects question metadata, and publishes provenance before the
content file. Neither file may already exist.

Text inputs also have a final-passage presence check. This catches some
truncation, not omissions or reordering elsewhere. PDF and XHTML fidelity still
requires review; no comprehensive source-alignment validator is claimed.

## Graph Construction

`runs.py` owns start/add/retry, frozen input snapshots, policy hashes, revisions,
and the successful/latest pointers. `input_data.py` projects already-valid
canonical content into the selected granularity.

The stage order is fixed. Complete this sequence for each document before
inserting the next, whether documents arrive in one manifest or separate adds:

1. Register each paper in manifest order.
2. Reuse or generate its structural questions.
3. Match each new structural unit against existing nodes in both directions.
4. Accept reciprocal selections; create nodes for unmatched units.
5. Generate display questions for the structural groups.
6. Revisit all structural singletons, including those from earlier documents.
   Each selects its best eligible established group or null; each established
   group independently selects its best eligible singleton or null. Merge only
   mutual top-1 choices, excluding groups that already contain the source paper.
7. Regenerate changed structural questions.
8. Reuse or generate the document's paragraph questions. Within each exact
   structural node, match paragraphs in both directions, reconcile, and generate
   group questions.
9. Apply the same singleton realignment algorithm to paragraph nodes, bounded
   to each exact structural node, and regenerate changed group questions.

Both levels use one shared realignment implementation. Each pass freezes the
candidate pools and obtains all forward/reverse judgments before any merge.
The reverse pool includes all eligible singletons, not just proposers. An
established group can absorb at most one singleton per pass; this is not an
unbounded repeat-until-convergence loop. A later insertion starts a fresh pass.

Paragraph-only mode requires one section per document, creates a deterministic
shared root, and skips only structural LLM judgments, not paragraph realignment.
Section mode combines a section's
descendant paragraphs. Subsection mode preserves both levels and gives each
paragraph one exact structural owner.

Paragraph reconciliation uses reciprocal top-1 cores and a bounded fan-in rule:
an immediately adjacent one-way selection can join a reciprocal core. It cannot
chain through an already-added fan-in member. Unaccepted projected selections
are provenance only. The ordinary graph edges are containment edges, not
invented causal or analogical relations.

A structural singleton may already own paragraph nodes from an earlier document.
Its merge reparents those nodes and updates their member ownership, preserving
IDs and source text. Replay records these scope changes explicitly. Every merge
records both judgment attempt IDs; unreciprocated choices remain provenance only.

A third paper can establish a group that an older singleton now joins at either
level. Realignment still does not split previously accepted shared groups or
search all possible global relational alignments. Those are different operations,
not implicit consequences of singleton matching.

## Module Boundaries

- `runner.py`: stage orchestration, judgment requests, application of decisions.
- `evidence.py`: exact unit/node evidence and identity-free paragraph windows.
- `match_rules.py`: pure reciprocity and adjacency predicates.
- `graph.py`: deterministic mutations, stable IDs, serialization, replay.
- `llm.py`: graph-specific fingerprints, cache records, response validation.
- `pipeline/llm/client.py`: shared Skills API calls, registration, temporary
  attachment cleanup, request bounds, observed usage accounting.
- `journal.py`: append-only attempts, events, and stage records.
- `export.py`, `correspondences.py`, `correspondence_table.py`: inspection outputs.
- `pipeline/files.py`: shared atomic JSON writes and filesystem hashes.

The viewer is plain TypeScript, not a framework rewrite. Its modules separate
wire contracts, loading, model indexing, groups, paper map, replay reduction,
replay rendering, tutorial, and application wiring. The TypeScript build exports
JSON Schema so Python packaging and browser loading validate the same shapes.
Only source-order reading views and replay remain; hidden skeleton, link,
iteration, trace/flow, and MILP experiments were removed.

The tutorial was reduced to eight steps about the retained views, without the
old experiment-specific action-gating machinery. Participant routing remains
available through `package_study`; it is not random assignment, telemetry, or
a completed user-study infrastructure.

## Prompt Caching

Graph judgments still use native Claude Skills and code execution. Skill files
are not copied into the system prompt. Matching context declares `cache_prefix:
[scope, candidates]`: the transport sends cached task instructions, then cached
scope/candidates, then the changing focus without a cache marker. This applies
to both directions at both levels, including singleton realignment. Complete
eligible pools and neighbor windows are preserved, not shortened or normalized.
Question prompts keep unique evidence uncached rather than paying to write a
large prefix that will not repeat.

Existing cache markers also enable Anthropic's automatic caching of code
execution results within a Skill request's server-side iterations, as documented
in [server-tool caching](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching).
This does not guarantee that a Skill's on-demand instruction-file read will be
reused across separate judgments. Container state is independent of prompt
caching; containers and tool histories are not carried between judgments.

Both pipelines store native Skill registration records in
`_cache/skill-registry.json` under the repository root (the graph configuration's
Skill-root parent). New runs reuse the registered ID/version for identical Skill
files; source changes create a new version, and credentials have isolated
records. This is registration reuse, not cached model output or a guarantee of
prompt-cache hits. Old per-run registries are not migrated. Local judgment
results remain run-scoped, so independent experiments do not silently share
decisions. Archiving `runs/` no longer discards the shared Skill registry.

The existing system breakpoint and the two user-prefix breakpoints use the
five-minute TTL. This leaves one of the four explicit breakpoint slots free.
According to [Anthropic's caching documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching),
cache reuse requires an identical preceding prefix and the model's minimum
token length. Changing scope, candidates, instructions, or model settings can
prevent reuse; merely changing the focus no longer invalidates the pool prefix.
Realignment pools can differ because eligibility depends on paper membership.
Five minutes is measured from request start, so long-running Skill calls can
still outlast the cache. No longer TTL or extra warm-up request is enabled.

`rendered_user` in provenance joins the candidate-prefix and dynamic-focus text
blocks with two newlines. `rendered_system` retains the task instructions sent
in the first user block. Full context still participates in local result-cache
identity, and prompt identity includes the configured prefix partition. Cached
evidence still counts toward prompt-size and observed-token guards.

Offline tests verify request layout, evidence preservation, and invalidation,
not Anthropic cache hits or matching quality. For a live run, measure
`cache_read_input_tokens / (input_tokens + cache_creation_input_tokens +
cache_read_input_tokens)` on actual API responses. Exclude local result-cache
hits: their raw usage is historical provenance, not a new bill. Server-tool
iterations can contribute usage too, so this is not purely cross-request reuse.

## Strictness

Reject unsupported versions, wrong types, unknown fields, missing decisions,
unknown IDs, duplicate assignments, and malformed present files. Explicit null
means abstention; a missing field does not.

Graph-level rejected judgments are saved separately in `cache/rejected/`, with
the full response, request, and validation error. They are never accepted cache
entries or repaired by the runtime. Each rejection gets its own record so a
later failed retry cannot overwrite the paid evidence.

Normal wire decoding (JSON/YAML and a manifest path string into a Path) is not
repair. Source text is retained verbatim. One-time content stripping/flattening
belongs in `helpers/`, with the derivative then stored and reused.

The internal field named `normalized` in judgment provenance is historical
terminology for the schema-validated response object. It does not invoke a
normalizer. Legacy source aliases, batch ID repair, output repair, and registry
migration have been removed.

## Applying The Coding Practices

- **SoC / Law of Demeter:** source interpretation, language judgment, graph
  mutation, persistence, and presentation have separate owners. Evidence readers
  get graph snapshots rather than reaching into NetworkX for mutation.
- **DYC:** this document explains execution and invariants; contracts document
  accepted interfaces; research claims and limitations live in the assessment.
- **DRY:** one canonical source validator, one JSON writer, one Claude transport,
  and shared viewer schemas. Do not introduce an abstraction for coincidental
  similarity between genuinely different scientific operations.
- **KISS:** two explicit pipelines, a fixed stage order, a static viewer, and
  inspectable JSON. No plugin framework, service layer, database, or background job.
- **TDD:** reproduce a bug with a failing test, implement the smallest fix, then
  run focused and full suites. Keep scripted judgments separate from live-model
  and human evaluation. Existing tests do not imply the original code was TDD.
- **YAGNI:** delete retired paths instead of carrying compatibility. Do not add
  a global alignment solver, learned thresholds, automatic chunking, provider
  abstraction, or additional UI modes before a concrete experiment requires them.

## Remaining Work, In Order

1. Run the small, annotated, cross-domain experiment in the Sherlock assessment.
   Do not fund another whole-corpus run before establishing what counts as a match.
2. Add regression fixtures for adjudicated failures. Evaluate prompt-only
   grounding changes separately from representation/algorithm changes.
3. If local decisions still conflict, test minimal explicit relations and role
   bindings before building a general alignment engine.
4. Add extraction-fidelity checks only for observed failure types, preserving
   raw sources and refusing automatic semantic repair.
5. Conduct real user sessions after technical acceptance criteria are met.

The runner is still the largest Python module and judgments still use flexible
evidence dictionaries. Split further only at a real scientific or testing
boundary; replacing them with a generic workflow framework would not improve
this codebase.
