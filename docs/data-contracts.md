# Data Contracts

This branch has an intentional contract reset. Older run formats, pairwise
mapping outputs, epoch files, aliases, and malformed model output are rejected,
not normalized.

## Canonical Source

`pipeline/document.py` owns validation. A document is a nonempty nested array:

```json
[
  {
    "section_name": "Results",
    "section_number": "4",
    "paragraphs": [
      {"paragraph_number": 0, "text": "Lead-in text."}
    ],
    "subsections": [
      {
        "section_name": "Findings",
        "section_number": "4.1",
        "paragraphs": [
          {"paragraph_number": 0, "text": "Finding text."}
        ]
      }
    ]
  }
]
```

Only source-marked divisions belong here. Paragraph numbers are exact integers,
zero-based, contiguous, and restart inside each paragraph array. Text must be a
nonblank string; its whitespace is preserved. Unknown fields are errors.

`question_this_text_answers` is optional metadata on a section, subsection, or
paragraph. Extraction omits it; the graph reuses valid existing questions and
generates missing ones. It is not an alternate document format or an identity.

Stable IDs derive from array positions: `s0001`, `s0001.ss0001`,
`s0001.p0001`, `s0001.ss0001.p0001`. Changing questions or labels leaves
identity unchanged; reordering source structure changes it by design.

## Ordered Manifest

```yaml
schema_version: 1
max_granularity: subsection
papers:
  - paper_id: paper_a
    title: Paper A
    file: content/paper_a.json
  - paper_id: paper_b
    title: Paper B
    file: content/paper_b.json
```

Paths resolve relative to the manifest. Paper IDs use letters, digits, dashes,
or underscores and must be unique. Allowed granularity is `section`,
`subsection`, or `paragraph`; omitted granularity intentionally defaults to
`section`. Misspelling it is an error, not an invitation to use that default.

Paragraph mode requires one top-level section with no subsections. A flattened
whole-story file is an explicitly stored derivative, never an implicit runtime
conversion.

## Judgment

One request contains one focus and the complete eligible candidate pool.
The focus has no selectable identity. Candidate IDs are output handles.
Paragraph evidence uses `previous_paragraph`, `paragraph_under_consideration`,
and `next_paragraph` in reading order. Only the paragraph under consideration is
matched; neighbors are context, with null at a structural owner's boundary.
Neither focus nor member windows expose paragraph IDs, numbers, or labels.
Source text and generated metadata are not rewritten to remove numbers in prose.
The exact response is:

```json
{"target_id": null, "basis": "No supplied candidate performs the same role.", "evidence": {"focus": [], "target": []}}
```

For a match, `target_id` must exactly equal one supplied candidate ID. A missing
field, blank basis, extra field, wrong type, or invented ID is invalid.
For a non-null selection, `evidence.focus` and `evidence.target` each contain one
short verbatim quotation per center, in the supplied member order. A unit has
one center; a group has one per member. Each quote must be nonempty, at most 240
characters, and an exact substring of that center's `full_text`. Neighbor text,
another member's text, paraphrases, and whitespace repairs are not accepted.
Abstentions require both arrays empty. Quotes establish attribution, not semantic
correctness: the basis must still explain the shared role rather than word overlap.
The shared schema and caller instructions live in `prompts/shared/`; native
Skills are unchanged. Historical two-field responses are not accepted by this
contract and must not receive fabricated evidence during replay.

Question requests return exactly `question_this_text_answers` with a nonblank
string. There is no batched-result interface.

## Run Storage

```text
runs/<run>/
  run.json
  inputs/revision-0001/
    manifest.yaml
    paper-0001.json
    paper-0002.json
  cache/
  revisions/revision-0001/
    provenance/attempts.jsonl
    provenance/events.jsonl
    stages/
    events.json
    summary.json
    reports/singletons.json
    reports/singletons.md
    dataset/
```

`run.json` stores the current successful revision, latest attempted revision,
input hashes, resolved configuration, and policy fingerprint. Failed execution
does not replace the successful pointer. Retry uses frozen inputs and a new
revision directory, with content-addressed judgment reuse.

A failure record may be written under its revision. An interruption can leave a
partial revision; do not edit its inputs or treat it as a successful dataset.

Each insertion records `section_rerepresentation` and
`paragraph_rerepresentation` stages (the former is omitted in paragraph-only
mode). Realignment records both `singleton_to_group` and `group_to_singleton`
decisions. Both use exactly the same target-or-null response contract above.

The singleton report uses only recorded events. It gives each paragraph outside
a shared group one operational reason: `never_compared`,
`selected_without_acceptance`, `model_abstained`, or `candidate_only`. Exposure
means appearing as a focus or eligible candidate, not merely as neighbor context.
Non-null outgoing or incoming selection takes precedence over abstentions in
other calls. Attempt IDs link back to the unmodified judgment provenance.
Final-snapshot recovery eligibility is separate from these historical outcomes:
same-scope singleton peers are excluded by the current recovery policy, and an
established target must not already contain the singleton's paper. The report
does not claim that an eligible target was examined or that a selection was sound.

## Viewer Export

`manifest.json` and one JSON file per paper preserve source order.
`final_snapshot.json` partitions paragraphs into shared groups and singletons,
and includes structural groups. Every paragraph has exactly one membership.
A shared group represents at least two papers; a singleton exactly one.

`graph-replay.json` is optional, with an ordered event stream, paper order,
layouts, and final graph hash. Mutation events create/update/merge nodes and add
containment edges. Judgment/projection/fan-in annotations are not extra mutations.
Realignment `node_merged` events require `attempt_id` and `reverse_attempt_id`.
`node_reparented` records a paragraph node's old and new structural parent;
replay updates both node scope and member ownership without changing identity.
The former one-way realignment event contract is intentionally not accepted.

The exporter also writes `graph.json`, `correspondences.json`, and
`correspondences.md` for analysis. Packaging copies only viewer-required data.

`pipeline/viewer/src/contracts.ts` defines exact viewer wire shapes and exports
JSON Schema during the build. No empty `bidirectional_matches.json`,
`representative_members` duplicate, or blank predecessor/successor field remains.

Participant IDs are exactly two uppercase letters plus three digits, with a
configured prefix. The browser does not trim or uppercase a malformed ID.
