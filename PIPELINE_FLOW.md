# Pipeline flow

The supported pipeline builds an ordered, question-role graph from canonical
documents. Extraction prepares a new source once; graph construction never
extracts it. Language models make bounded question and match judgments. Python
validates those judgments, applies graph rules, and writes inspectable outputs.
This is an SME-inspired comparison system, not the canonical symbolic SME.

## From source to viewer

![Source-to-viewer pipeline](docs/diagrams/pipeline-overview.png)

```mermaid
flowchart TD
    Raw["New PDF, TXT, or XHTML"]:::input
    Extract["Optional one-time extraction<br/>native Skill plus selected provider"]:::model
    Content["Canonical content JSON<br/>and extraction provenance"]:::artifact
    Prepared["Existing prepared JSON"]:::input
    Manifest["Ordered manifest<br/>start: 2+ documents; add: new documents"]:::input
    Validate["Validate source contract<br/>and derive positional IDs"]:::det
    Start["start / add<br/>freeze inputs and policy"]:::det
    Saved["Existing run with<br/>frozen inputs and policy"]:::input
    Retry["retry<br/>reuse saved inputs and policy"]:::det
    Judge["For each document in order:<br/>question and match judgments"]:::model
    Graph["Apply reciprocal, fan-in, and<br/>singleton rules in Python"]:::det
    Outputs["Immutable revision:<br/>events, reports, graph, viewer dataset"]:::artifact
    Viewer["Local viewer or static package<br/>Question Groups, Paper Map, Explorer"]:::det

    Raw --> Extract --> Content --> Manifest
    Prepared --> Manifest
    Manifest --> Validate --> Start --> Judge --> Graph
    Saved --> Retry --> Judge
    Graph -->|next document| Judge
    Graph -->|after last document| Outputs --> Viewer

    classDef input fill:#edf4f8,stroke:#30637d,color:#173747;
    classDef model fill:#fff0d8,stroke:#bc6c13,color:#603704;
    classDef det fill:#e7f4e8,stroke:#327144,color:#173e23;
    classDef artifact fill:#f1eafb,stroke:#7054a0,color:#382459;
```

`python -m pipeline.extraction` calls the extraction Skill for a new source,
validates the returned content, and refuses to overwrite an existing output.
`python -m pipeline.incremental_graph.cli validate` makes no model calls.
`start` creates a run from at least two documents; `add` appends only new
documents; `retry` takes no manifest and reuses saved inputs. Every execution
writes a new revision and replays the ordered sequence,
reusing completed judgments whose inputs and policy are unchanged. A failed
revision does not replace the last successful one. Viewer build, serving, and
packaging make no model calls.

## One document insertion

![Per-document graph stages](docs/diagrams/document-insertion.png)

```mermaid
flowchart TD
    Paper["Next prepared document<br/>in manifest order"]:::input
    Mode{"Granularity"}:::det
    Structural["Structural phase<br/>1. Reuse/generate section questions<br/>2. Match units and groups both ways<br/>3. Reconcile reciprocal choices<br/>4. Set group questions<br/>5. Revisit singletons and refresh questions"]:::model
    Older["Recompare paragraphs from older<br/>sections absorbed into shared groups"]:::model
    Root["Paragraph-only: one section per<br/>document joins a deterministic shared root"]:::det
    Paragraph["Paragraph phase, within each exact structural group<br/>1. Reuse/generate questions with adjacent context<br/>2. Match paragraphs and groups both ways<br/>3. Reconcile reciprocal cores and adjacent fan-in<br/>4. Set group questions<br/>5. Revisit singletons and refresh questions"]:::model
    Next{"More documents?"}:::det
    Export["Finalize journal; export graph,<br/>correspondences, replay, singleton report,<br/>and viewer dataset"]:::artifact

    Paper --> Mode
    Mode -->|section or subsection| Structural --> Older --> Paragraph
    Mode -->|paragraph-only| Root --> Paragraph
    Paragraph --> Next
    Next -->|yes| Paper
    Next -->|no| Export

    classDef input fill:#edf4f8,stroke:#30637d,color:#173747;
    classDef model fill:#fff0d8,stroke:#bc6c13,color:#603704;
    classDef det fill:#e7f4e8,stroke:#327144,color:#173e23;
    classDef artifact fill:#f1eafb,stroke:#7054a0,color:#382459;
```

Orange stages mix model judgments and deterministic Python reconciliation;
the model is called only when a question is missing or a judgment is not
already in the run cache. Each match request selects one eligible
candidate or null; it does not return a batch of matches. Python accepts
reciprocal selections, applies the limited paragraph adjacency rule, and keeps
unaccepted selections as provenance. Structural singleton recovery can absorb
an older section. The runner then compares that section's existing paragraphs
inside their new shared scope before processing the incoming document's
paragraphs. Paragraph-only mode skips structural model judgments but still
runs paragraph recovery.

See [architecture](docs/architecture.md) for the exact rules and
[data contracts](docs/data-contracts.md) for input and output schemas. The
[README](README.md) gives commands for a first run and a new corpus.
