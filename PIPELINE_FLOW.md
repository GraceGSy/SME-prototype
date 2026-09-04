# Pipeline flow

The active workflow uses one nested document contract and one Claude Skills
interface. Green steps are deterministic. Orange steps are model judgments.

## Document pipeline

```mermaid
flowchart TD
    Config["pipeline.yaml: ordered stages, Skills,<br/>datasets, files, views, model"]:::det
    Source{"Configured source"}:::det
    HCI["HCI paper PDFs"]:::artifact
    Story["Pinned Sherlock XHTML<br/>verified by SHA-256"]:::artifact
    Legal["Authored opinion or dissent text<br/>verified by SHA-256"]:::artifact
    Extract["Claude extraction Skill:<br/>source-marked sections, scenes, paragraphs"]:::llm
    Content["Extracted<br/>document.content.json"]:::artifact
    IDs["Validate schema and derive positional IDs<br/>s0001, s0001.ss0001, ..."]:::det
    Question["Claude question Skill once per<br/>non-empty section/subsection"]:::llm
    Questions["Same document shape plus one field:<br/>question_this_text_answers"]:::artifact
    View{"Configured candidate view"}:::det
    Sections["Include section candidates"]:::det
    Nested["Include section and subsection candidates"]:::det
    Forward["Claude matching Skill: A to B<br/>source_id, target_id, basis"]:::llm
    Reverse["Claude matching Skill: B to A<br/>same schema"]:::llm
    Matches["One checkpointed match envelope<br/>containing both directions"]:::artifact

    Config --> Source
    Source -->|pdf| HCI --> Extract
    Source -->|xhtml| Story --> Extract
    Source -->|text| Legal --> Extract
    Extract --> Content
    Content --> IDs --> Question --> Questions --> View
    View -->|sections| Sections --> Forward
    View -->|sections_and_subsections| Nested --> Forward
    Forward --> Reverse --> Matches
    classDef det fill:#e8f5e9,stroke:#2e7d32,color:#163c19;
    classDef llm fill:#fff1dc,stroke:#c46b08,color:#623704;
    classDef artifact fill:#e8eefb,stroke:#3f5f9f,color:#1f3154;
```

The harness also writes `runs.jsonl`, `errors.jsonl`, Skill/source/output
hashes, and stage checkpoints for audit and retry. These records do not alter
the pipeline flow. Extraction returns structured JSON to Python rather than
having Claude create and reread an output file. Every model call uses the
configured effort, thinking, prompt, attachment, input-token, and output-token
limits. Each judgment is one Messages API request; the adapter never sends the
response back as a follow-up turn.

Both matching stages use the same candidate and output contracts. They differ
only in candidate inclusion and the configured Skill. Candidate views exist in
memory, so no flat or nested duplicate input files are written.

## Incremental graph

```mermaid
flowchart TD
    Manifest["Ordered manifest, max_granularity,<br/>and canonical document JSON"]:::artifact
    Load["Shared validation and positional IDs"]:::det
    Mode{"max_granularity"}:::det
    Structural["For each paper: section/subsection<br/>questions and matching"]:::llm
    Reconcile["Reciprocal matches add members;<br/>otherwise create singleton nodes"]:::det
    Contains["Add source-backed contains edges"]:::det
    NodeQuestions["Generate questions for<br/>changed multi-member nodes"]:::llm
    Rerepresent["One singleton-to-established<br/>matching pass"]:::llm
    Merge["Apply eligible merges in stable order;<br/>retain rejected selections as provenance"]:::det
    SharedRoot["Assign each one-section document<br/>to one shared corpus root"]:::det
    ParagraphQuestions["Generate every paragraph question<br/>in one call per paper"]:::llm
    Paragraphs["Two directional batched calls per<br/>exact structural node"]:::llm
    ParagraphRules["Apply reciprocal and bounded<br/>adjacent fan-in rules"]:::det
    Export["Deterministically export final_snapshot,<br/>paper files, correspondences, replay"]:::det
    Package["Validate and package one<br/>viewer contract"]:::det
    UI["Question Groups | Paper Map<br/>Graph Replay only if replay exists"]:::artifact

    Manifest --> Load --> Mode
    Mode -->|section or subsection| Structural --> Reconcile --> Contains --> NodeQuestions
    NodeQuestions --> Rerepresent --> Merge --> ParagraphQuestions
    Mode -->|paragraph| SharedRoot --> ParagraphQuestions
    ParagraphQuestions --> Paragraphs --> ParagraphRules --> Export --> Package --> UI
    classDef det fill:#e8f5e9,stroke:#2e7d32,color:#163c19;
    classDef llm fill:#fff1dc,stroke:#c46b08,color:#623704;
    classDef artifact fill:#e8eefb,stroke:#3f5f9f,color:#1f3154;
```

The graph runner also appends match attempts and graph events and checkpoints
every stage for audit and retry. These records do not alter graph construction.

Every orange graph step uses a configured Claude Skill. Question judgments
return `question_this_text_answers`; match judgments return `target_id` and
`basis`. Python supplies complete evidence, constrains IDs, validates output,
and controls all graph mutation. Match selections that are not accepted by a
deterministic rule never become graph edges.

The pairwise match envelope is intentionally not fed into the incremental graph:
pairwise document matching permits multiple targets, while an insertion-round
graph judgment selects one existing node or none. They share document, ID,
question, candidate, and field conventions without pretending those two
different decisions are interchangeable.

`python -m pipeline.study --dataset <id>` automates the useful handoff. Section
and subsection modes run document questions before graphing. Paragraph mode
reuses extraction, flattens each document deterministically, and lets the graph
runner generate paragraph questions. Both paths write the ordered manifest,
invoke the graph, and package the viewer without manual file selection.

## Outbound calls

| Trigger | Endpoint purpose | Skipped when |
|---|---|---|
| Missing pinned Sherlock source | HTTPS download from the configured immutable URL | Verified source is cached |
| First use of a changed Skill | Anthropic Skills create/version | Skill hash is registered |
| Extraction | Anthropic Files plus beta Messages/Skill execution | Valid content artifact exists |
| Question or match judgment | Anthropic beta Messages/Skill execution | Valid checkpoint or content-addressed cache exists |

Viewer packaging and browser rendering make no model calls. The retained
`pipeline/graph_sme/` proposition graph is a separate legacy experiment with a
different semantic object, not an alternate document-pipeline format.
