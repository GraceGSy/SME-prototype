# Third-party data in this repository

The repository's license covers its code, prompts, and documentation. It does not
cover the source texts below, which keep their own terms. Each dataset's README
says how the text was extracted and checked.

| Folder | What it is | Terms |
|---|---|---|
| `datasets/hci-five-paper/` | Five published HCI research papers (AbstractExplorer, CorpusStudio, Examplore CHI 2018, Mesotext, Paralib UIST 2022): the PDFs in `raw/` and text extracted from them in `content/` | Copyright stays with the papers' authors and publishers. Included for research use; ask them before reusing the papers elsewhere. |
| `datasets/legal/` | Five US federal appellate decisions, each split into opinion and dissent (sources linked in its README) | US federal court opinions are public domain. |
| `datasets/sherlock/` | Five Sherlock Holmes stories by Arthur Conan Doyle, from Standard Ebooks | Public domain in the US; Standard Ebooks releases its editions under CC0. |
| `runs/hci-five-paper-clean-20261119/` | A saved pipeline run over the HCI papers, including excerpts of their text | Same as `datasets/hci-five-paper/`. |

Model outputs saved in runs (role statements, match decisions) were produced with
Anthropic's Claude and TypeSafe's Jev; their use is subject to those providers' terms.
