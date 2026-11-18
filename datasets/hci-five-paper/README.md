# Five HCI papers

`raw/` holds the source PDFs. `content/` holds one content-only canonical JSON
file per paper. `content/manifest.yaml` lists all five in insertion order;
`content/first-two.manifest.yaml` selects AbstractExplorer and CorpusStudio for
a smaller first run. The graph generates missing role statements from these files.
Do not re-extract unchanged PDFs or reuse judgments from a different run.

The stored corpus has 52 top-level sections, 87 subsections, and 466
paragraphs. Source-marked subsections remain structural units; each paragraph
has one exact owner. Validate the full prepared corpus without API calls:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/hci-five-paper/content/manifest.yaml
```

Section numbers are the papers' printed numbers: Introduction is 1, and
unnumbered headings such as Abstract, Acknowledgments, and References have
`null`. Examplore (CHI 2018) prints no section numbers, so all of its numbers are
`null`. Pipeline IDs use document position, not these numbers.

November 16 cleanup of the first three papers (no re-extraction; paragraph counts
unchanged): printed section numbers; Examplore headings in the paper's own title
case instead of all capitals; four undecodable `(cid:N)` glyphs in Examplore's
Scenario section replaced by the circled figure markers the PDF shows (④–⑦);
AbstractExplorer's stray footnote markers removed from running text, spaces
before punctuation around its colored role labels removed, two line-break
hyphens inside words removed, and ten compounds restored that lost their hyphen
at a line break (for example `cross-document`). A shingle comparison against
the PDFs found no missing body text; uncovered PDF text is front matter, running
heads, footnotes, figures, tables, code listings, references, and appendices.
November 18 cleanup of Mesotext and Paralib (no re-extraction): printed section numbers (both had been numbered from Abstract). The same shingle audit found Paralib missing the last two paragraphs of 7.3 Qualitative Feedback (restored; Paralib now has 81 paragraphs, the corpus 466), a P19 quote merged with P17's across a figure (split as printed), and a Figure 6 caption fragment inside a 7.1 paragraph (removed). Mesotext's text matched its PDF. `last-two.manifest.yaml` selects these two papers. Sub-subsection headings (for example 5.2.1) remain folded into their subsection. The November 11 two-paper audit matched the retained headings
to the PDF outlines and checked paragraph order against the PDF text.
CorpusStudio has 123 paragraphs: the Participants passage below Table 1 on
PDF page 7 was restored, and three merged paragraph boundaries were split.
AbstractExplorer has 103. Bibliography entries and appendices are outside this
prepared corpus. Neither historic run inputs nor in-text citations were renumbered.

An older question-annotated variant was removed from the active checkout. It
remains in Git history and is not a gold standard. See the
[main README](../../README.md) to run the content-only example.

To generate Claude role statements for the first three papers without matching:

```powershell
py -3.11 -m pipeline.prepare_roles datasets/hci-five-paper/content/first-three.manifest.yaml output/prepared-runs/hci-three-paper-roles-20261116
```

The preparer sends the complete cleaned paper once per request as a cacheable
prefix, followed by one focus address and the role prompt. It never puts previous
annotations in that prefix. The output manifest references the two annotated
papers. The response log stores each prefix once plus per-unit responses and
provider-reported cache usage. Rerun the same command to reuse completed answers;
do not launch two writers for the same output directory.
