# Manual Matcher

[Open the deployed matcher](https://question-atlas-labels.vercel.app/).

A browser-only annotation tool using the existing Question Atlas viewer components
and palette. It makes no model calls, uploads no documents, and needs no API key or
backend. Vercel serves only static assets and five prepared HCI example inputs.

## Use

Choose **Tutorial** in the header for an eight-step walkthrough with highlighted
controls and short practice papers. Next and Back show section grouping, optional
questions, paragraph matching, the outside-group picker, and saving/exporting.
Finish, Exit, and Escape discard the practice example and return to the selection
page. The tutorial never writes its examples to autosave or overwrites real labels.

1. Choose two prepared HCI papers, or upload two canonical extracted JSON files.
2. Choose Sections or Sections + subsections. Start matching.
3. Select any number of structural units from either paper and choose Group selected.
   A shared question is optional. Select a group to edit or separate its members.
4. Choose Match paragraphs on a group, or continue to the Paragraphs step and select
   a structural group. Group its paragraphs the same way.
5. On a paragraph, choose Match outside this group to search the other paper and
   select a paragraph outside the current structural group. This joins the existing
   paragraph groups and records the selected source/target pair. Selecting that group
   also reveals its out-of-scope paragraphs for inspection.
6. Save labels downloads a self-contained JSON file with both granularities and
   the original inputs. Open labels restores it. Browser autosave survives reloads,
   but it is local to that browser and origin, not shared cloud storage.
7. View in viewer opens a snapshot using the existing Question Groups, Paper Map,
   and Graphical Explorer components. Export viewer downloads a complete static
   viewer ZIP, including the pipeline-compatible data directory and resumable labels.

Granularity modes have independent annotations. Section mode folds subsection text
into its top-level section; subsection mode preserves exact paragraph owners, matching
`pipeline/incremental_graph/input_data.py`. Switching modes does not convert or erase
either mode's labels. Each structural unit and paragraph belongs to exactly one group
within its mode. Regrouping moves the selected members without duplicating them.

## Build And Test

From the repository root:

```powershell
npm run test:matcher
npm run build:matcher
python -m http.server 8767 --bind 127.0.0.1 --directory output/manual-matcher/public
```

The build packages only the matcher, current viewer assets, and five prepared HCI
JSON files under `output/manual-matcher/`. It never packages raw PDFs, run caches,
environment files, or the repository. Deploy that directory, not the repo root.

`npm run test:matcher` includes exact Python/browser loading parity on the first two
HCI papers, contract validation, grouping invariants, both granularities, optional
questions, and cross-group matches. It uses the repository's Python dependencies.

## Files And Contracts

- `model.ts`: canonical input validation, deterministic source IDs, grouping, labels,
  and viewer export; no UI or storage dependencies.
- `app.ts`, `index.html`, `styles.css`: manual matching interface.
- `storage.ts`: browser persistence and downloads.
- `preview.ts`, `viewer.html`: existing viewer components on a manual snapshot.
- `build.ts`: allowlisted static deployment package.

The label JSON identifies itself as `kind: manual_matching`, `schema_version: 1`.
It stores both original sources, the active mode, each mode's complete partition,
optional unit/group questions, and explicit outside-group selections. Import rejects
unknown units, duplicate memberships, omitted units, and inconsistent flags.

The viewer ZIP uses the same `manifest.json`, per-paper JSON, `final_snapshot.json`,
and `dataset.json` contracts as pipeline exports. It includes no fabricated model
judgments, event history, or replay. Groups spanning structural groups use a null
`parent_group_id`; the shared explorer displays them at the document level. Source
paragraph IDs, text, order, and section ownership remain unchanged.

Blank group questions get neutral display labels, not generated questions. Untouched
units remain separate, but export does not claim that they were reviewed or that the
label set is complete. Evaluation/adjudication workflows are outside this version.
