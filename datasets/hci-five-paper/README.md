# HCI five-paper dataset

`manifest.yaml` defines the canonical insertion order. Each JSON file contains
non-appendix top-level sections, optional subsections, paragraphs in reading
order, and precomputed `question_this_text_answers` metadata.

The incremental graph treats top-level sections as section units. Subsection
paragraphs are folded into their parent section in reading order, while each
paragraph remains an independent paragraph unit.

Run the non-network validation from the repository root:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/hci-five-paper/manifest.yaml
```
