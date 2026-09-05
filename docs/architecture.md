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

The stage order is fixed because it encodes real data dependencies:

1. Register each paper in manifest order.
2. Reuse or generate its structural questions.
3. Match each new structural unit against existing nodes in both directions.
4. Accept reciprocal selections; create nodes for unmatched units.
5. Generate display questions for the structural groups.
6. After all papers, let structural singletons select established multi-paper
   nodes in one direction. Reject merges that duplicate a paper in a node.
7. Regenerate changed structural questions.
8. For each paper in order, reuse or generate paragraph questions, match against
   eligible paragraph nodes in both directions, reconcile, and generate questions.

Paragraph-only mode requires one section per document, creates a deterministic
shared root, and skips structural LLM judgments. Section mode combines a section's
descendant paragraphs. Subsection mode preserves both levels and gives each
paragraph one exact structural owner.

Paragraph reconciliation uses reciprocal top-1 cores and a bounded fan-in rule:
an immediately adjacent one-way selection can join a reciprocal core. It cannot
chain through an already-added fan-in member. Unaccepted projected selections
are provenance only. The ordinary graph edges are containment edges, not
invented causal or analogical relations.

A third paper is matched to the existing multi-paper nodes. It does not trigger
a general global reassessment of all earlier unmatched paragraph pairs.
The current rerepresentation pass runs once after the entire structural insertion
sequence, not after each paper in a multi-paper start/add command. It only moves
structural singletons into established groups; it cannot split or revise an
existing shared group. Paragraph-only mode skips it entirely. This is narrower
than the proposed per-addition global realignment and must not be described as
implementing that proposal.

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

## Strictness

Reject unsupported versions, wrong types, unknown fields, missing decisions,
unknown IDs, duplicate assignments, and malformed present files. Explicit null
means abstention; a missing field does not.

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
