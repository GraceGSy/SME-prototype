# Legal corpus

`raw/` contains five majority-opinion PDFs and their five paired dissent PDFs,
already split to the authored document. `content/` contains direct PDF
extractions produced by the configured Claude extraction Skill.

Current extraction checkpoint: `banuelos_jimenez_opinion` and
`core_optical_opinion` are complete. The API balance was exhausted before
`lamb_opinion`; rerun the command below after replenishing it. Existing valid
files are skipped automatically.

```powershell
python -m pipeline.skill_pipeline.runner --dataset legal_opinions --stage extraction
python -m pipeline.skill_pipeline.runner --dataset legal_dissents --stage extraction
```

Legal extraction uses only printed Roman-numeral and capital-letter divisions.
It does not infer doctrinal or topical sections. A document with no printed
division remains one `Opinion` or `Dissent` section.

After all ten files exist, validate the two content corpora without API calls:

```powershell
python -m pipeline.incremental_graph.cli validate datasets/legal/opinions.manifest.yaml
python -m pipeline.incremental_graph.cli validate datasets/legal/dissents.manifest.yaml
```
