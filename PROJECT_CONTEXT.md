# SMELTER project context and handoff

Last checked: November 18, 2026 (late evening), America/New_York.

This is a dated handoff for Claude or another contributor. It combines the current
checkout, saved experiment artifacts, relevant user decisions, and prior work.
It is not an instruction to start a paid experiment. Recheck Git state and the
specific run before acting. Follow the user's current request and applicable
`AGENTS.md` instructions if they differ from this historical account.

## 1. Current status

**November 18, late evening (start here; supersedes older notes where they differ).**

- **Published (question-atlas-runs.vercel.app, HCI source text included):**
  [runs/hci-three-paper-paragraphs-v3-20261118/](runs/hci-three-paper-paragraphs-v3-20261118/),
  the first paragraph-level run of the current pipeline (papers 1–3), and
  [runs/hci-five-paper-close-calls-v2-20261118/](runs/hci-five-paper-close-calls-v2-20261118/),
  the five-paper section run. Section-only runs open on the pattern board
  (Graphical Explorer) with the Paper Map as a second tab.
- **Paragraph results, papers 1–3** (`--section-fan-in --close-call-margin 0.10`,
  long context on): 287 paragraphs; 37 shared paragraph groups (20 span all three
  papers, 17 span two) holding 152 paragraphs; 135 paragraphs alone. 58 paragraph
  fan-in members. 50 close rankings: 41 re-asked, 27 settled by the re-ask, 23 held
  (7 still alone at the end). No yes/no question dropped paper text.
- **Timing (paid attempt that finished matching):** papers 1–2 replayed from cache
  in seconds; paper 3 (Examplore, 61 paragraphs) took 22.8 min for 2,184 new Jev
  calls (0.6 s/call) and 37 Claude group roles. Paper 2's paragraph phase, measured
  in the first attempt, took 3.6 min for 355 Jev calls. Paper 3 needed 2,184 calls
  against an upper bound of 2,249, so merging barely reduces the count; expect close
  to the bounds for papers 4 (4,456) and 5 (5,365): roughly 10,000 calls, about
  100 min plus Claude time.
- **Long context is on by default** (commit 9150280d): a yes/no question over 32k
  is resent with the 262k header; the member-sections-only fallback is removed, and a
  question too large even for long context stops the run. Most paragraph-level
  attempts used long context, which TypeSafe calls slower and less accurate.
- **Close calls** (commit f886aac8, opt-in `--close-call-margin`): a ranking whose
  top options are within the margin is re-asked among those options, then held.
  Five-paper section run: 3 close calls, all settled by the re-ask, 2 changed the
  pick, one section moved (Mesotext "Sensemaking Interfaces for Generative AI").
- **Paragraph-recursion bugs fixed tonight**, all from section fan-in meeting
  paragraph matching (each has a regression test that fails on the old code):
  1. Paragraphs were batched per section, not per section group; a group holding
     two sections of one paper was matched twice before either batch was applied,
     so a node merged away by the first was targeted by the second (KeyError, paper 2
     of `runs/hci-five-paper-paragraphs-20261118/`, 355 Jev calls). Fixed in 9a7fe20c;
     paragraph adjacency also now requires the same section (ordinals restart).
  2. A section merged in as fan-in left its paragraph nodes under the removed
     section node, so recursion failed ("Realignment requires the same exact parent
     scope", paper 3 of `runs/hci-three-paper-paragraphs-20261118/`, 155 Jev calls,
     18 Claude). Fixed in 0f433ab8, which also re-matches paragraphs of sections
     absorbed by reverse fan-in at insertion and batches recursion per (paper,
     section group).
  3. A full run with `--close-call-margin` failed at its last step: the close-call
     report created `reports/` before the singleton report, which requires a new
     folder (`runs/hci-three-paper-paragraphs-v2-20261118/`, matching complete,
     2,184 Jev calls). Fixed in 4caa93cd; v3 replayed v2's cache with zero new calls
     and identical groups.
- **Open decisions:** extend paragraph matching to papers 4–5 (about 10,000 Jev
  calls); legal corpus next (recommended: the five existing majority opinions,
  sections only; alternative: a circuit-split set). The user declined showing full
  papers in rankings (member sections stay). Unused failed runs above can serve as
  `--cache-from` sources.

**November 16 (supersedes the November 15 summary below where they differ).**

- **Choice among yes answers.** From paper 3, Jev's yes/no answers are only a
  filter; a ranking question then chooses among every option that passed
  (focus paper complete, options shown by their own members and roles, because
  Jev's context fits about two complete papers). Oversized rankings are split
  in half. See [docs/jev.md](docs/jev.md#pairwise-matching-from-the-third-paper)
  and [the November 16 runs](#three-paper-runs-november-16).
- **Data cleaning** of the three HCI extractions: printed section numbers
  (Introduction = 1; Examplore unnumbered), Examplore title-case headings, four
  broken glyphs, AbstractExplorer footnote markers, hyphenation, and spacing.
  Details are in the [corpus README](datasets/hci-five-paper/README.md).
  `relabel_extraction` now keeps printed numbers; Jev IDs remain positional.
- **Role prompts** rewritten to describe function without naming the system,
  domain, features, or findings, in a single concise sentence. Role requests
  name units by printed heading (`section: 3 Formative Interview Study`).
- **Accepted-match explanations removed** at the user's request: Claude no longer
  explains Jev's accepted matches (see
  [Jev decides; Claude no longer explains](#jev-decides-claude-no-longer-explains)).
  Jev size rejections are now cached so replays do not resend them.
- **Incomplete:** the new-roles run's membership is final, but paper-3 group roles
  are missing because the Anthropic credit balance ran out. Code changes since the
  first attempt mean `retry` refuses it; finish with a new run:
  `python -m pipeline.incremental_graph.cli start output/prepared-runs/hci-three-paper-roles-20261116/manifest.yaml runs/<new-name> --jev --sections-only --cache-from runs/hci-three-paper-new-roles-v2-20261116`.
  All 215 Jev calls replay; only Claude group roles are new.

Previous status, November 15:

The latest experiment matched **top-level sections only** across three papers:
AbstractExplorer, CorpusStudio, and Examplore (CHI 2018). It used the new node
representation and, for paper 3, pairwise yes/no matching. The result is
**6 three-paper groups, 6 two-paper groups, and 2 unmatched sections**. Paragraph
matching has not run. See [the November 15 run](#three-paper-pairwise-section-run-november-15).

Code changes made on November 15 (uncommitted, on top of the earlier dirty state):

- **Subsection granularity removed.** `max_granularity` is `section` or
  `paragraph`. Subsections remain source structure inside their section; they get
  no role statements, structural units, or hierarchy edges. The manual matcher's
  own subsection mode was left in place (UI and saved-session schema).
- **Node representation.** A node with N members carries every member's passage
  and role, the complete paper of its latest member, and its group role. Earlier
  members' papers are dropped. Group roles are regenerated from the latest
  member's complete paper (`latest_paper`) plus every member's passage and role.
- **Pairwise matching from paper 3.** Each new unit asks Jev one yes/no question
  per node. Both directions read one score table; exact ties go to one ranking
  question over the tied nodes. Singleton recovery uses the same route.
- **Role preparation.** Only top-level sections and paragraphs get roles;
  `--policy-from` reuses an earlier preparation's exact request wording.
- Housekeeping: the stale viewer assertion, four Prettier failures, and test file
  reads without explicit UTF-8 were fixed.

Offline checks now pass: 229 Python tests, 19 viewer tests, 14 matcher tests,
13 comparison tests, Ruff, and Prettier. Both November 13 runs still fail a
saved-policy comparison with current code; do not `retry` them.

The design is documented in [docs/jev.md](docs/jev.md#node-representation).

### Read in this order

1. This document, especially [current results](#4-current-experiments-and-artifacts)
   and [known problems](#8-known-problems-and-unfinished-work).
2. [Prompt editing guide](prompts/README.md) for editable wording and its consumers.
3. [Architecture](docs/architecture.md) and [data contracts](docs/data-contracts.md)
   for graph invariants, with the stale-documentation warnings below.
4. [Jev guide](docs/jev.md) for transport, comparison, and recovery details.
5. The saved requests and events for the particular experiment under discussion.
   Today's prompt files cannot establish what a historical request contained.

## 2. Repository and working-copy boundaries

The application repository is the nested checkout:

```text
C:\HBS\Glassman Lab Research\hypothesis\SME-prototype-elena-clean
```

The parent `hypothesis` directory is a broader workspace with its own Git metadata,
older prototypes, browser-extension work, papers, and archives. Do not run Git
commands there when intending to change this application.

Snapshot taken before this documentation change:

| Item | Observed value |
|---|---|
| Branch | `ktantia/decisions-integration` |
| HEAD | `42086b10c99a941978eb1c891f2ec3ac32184c78` |
| Origin | `https://github.com/GraceGSy/SME-prototype.git` |
| Locally recorded upstream | `origin/ktantia/decisions-integration` |
| Upstream difference | Ahead 9; no remote fetch was performed during this audit |
| Existing dirty state | 22 modified tracked files, listed below |

The branch name does not mean the proposed OpenAI Decisions API integration is
implemented. The running classifier route is Jev/TypeSafe. The Decisions diagrams
and [offline demo](docs/demos/decisions-pipeline.html) remain design artifacts.

### Nine local commits beyond the recorded upstream

These are all dated November 12 in the local Git log, oldest first. Several
commits preserve work performed in earlier sessions; commit date is not run date.

| Commit | Work preserved |
|---|---|
| `b4b894bc` | Reviewed five-article Reuters technology corpus |
| `aa0e3ee6` | Hierarchical extraction labels and restored HCI paragraphs |
| `5cb4f528` | Focus-first Jev evidence; explanations only for accepted correspondences |
| `8105f421` | SDK request parameters and provider failures retained for inspection |
| `2b95fb79` | Public run catalog with approved Reuters source text |
| `27bd4b2c` | Local decision trace, provider inspection, and graph replay |
| `f6503063` | VS Code launch profile for live HCI matching |
| `69dabd37` | `Question statement to role statement` |
| `42086b10` | Whole-paper role preparation with verified Claude prompt caching |

Do not infer that these are on the current remote from this document. Verify the
remote before a handoff to another machine. The most recent work also requires
the uncommitted changes, not just HEAD.

### Pre-existing uncommitted work

The following files were already modified when this handoff began. Preserve them.

| Area | Modified files and purpose |
|---|---|
| Execution boundary | `pipeline/incremental_graph/cli.py`, `runner.py`, `runs.py`: `--sections-only`, structural checkpoints, top-level Jev projection, cache import from a saved sample |
| Jev evidence | `pipeline/incremental_graph/evidence.py`, `jev_outline.py`, `jev_selection.py`: full participating papers; Focus/Context/Candidates; simplified section records; stop rather than shrink full-text requests on a size error |
| Section-map export and server | `pipeline/incremental_graph/export.py`, `pipeline/viewer/server.py`, `pipeline/viewer/trace.py`: checkpoint discovery and local section-map payloads |
| Section-map browser view | `pipeline/viewer/src/app.ts`, `data.ts`, `local-runs.ts`, `model.ts`, `paper-map.ts`: load and display sections without fabricating paragraph results |
| Prompt wording and documentation | `docs/jev.md`, `prompts/README.md`, `prompts/graph/paragraph-role-statement/v1/system.md`, `prompts/graph/section-role-statement/v1/system.md`, `prompts/requests/jev.json` |
| Tests | `tests/test_graph_runs.py`, `tests/test_jev.py`, `tests/test_jev_pipeline.py` |

### What a Git clone does not contain

[`.gitignore`](.gitignore) excludes `runs/`, `output/`, `site/`, `_cache/`, `.env`,
virtual environments, dependencies, and generated viewer assets. The actual
November experiments, prepared role statements, provider receipts, and local
comparison pages therefore need a separate, deliberate transfer or backup.

Preserve whole run directories, not only their exported viewer datasets. The
inputs, policy, revisions, caches, rejected responses, and events are needed to
understand and sometimes reuse paid work. Do not put credentials in the transfer.

The local credential file previously located for this workspace is
`C:\HBS\Glassman Lab Research\hypothesis\.env`. The loader checks the environment
and then the repository and its ancestors. The audit did not read or print keys
or verify current balances. A fresh machine needs its own credential setup.

## 3. Purpose and decisions to preserve

SMELTER currently expands to **Structural Mapping Engine for Long TExtual
Reading** in the README. It compares documents by what their passages do in
context: explanation, evidence, motivation, evaluation, and other supported roles.
The intended research contribution includes both the computational mapping system
and the reader-facing interface. Do not reduce the project to only one of them.

The system is SME/structure-mapping-inspired. It does not implement the canonical
symbolic SME, a global relational alignment solver, or the paper's full theoretical
classification scheme. Stable IDs, reciprocal choices, and valid quotations are
engineering properties; they are not proof of a correct analogy.

### Explicit user decisions

- Prioritize DRY, YAGNI, separation of concerns, loose coupling, KISS, and concise
  documentation. The user has repeatedly asked for a codebase a human can navigate.
- Keep one authoritative source of each prompt and contract. Do not add a generic
  orchestration framework, compatibility layer, editor, or taxonomy speculatively.
- Reject malformed interfaces rather than silently repairing identities or source
  data. Keep narrowly documented historical-reading support where it already exists.
- Python owns eligibility, identity, ordering, graph updates, validation, and
  persistence. Models supply bounded semantic decisions and descriptions.
- Preserve full source passages in model evidence. Do not silently summarize or
  truncate them to fit a request. Deduplicate by physical source location, not by
  equal strings at different locations.
- Number extracted sections locally from the abstract as 1, retaining hierarchy:
  `1, 2, 3, 3.1, 3.2, 4`. Do not renumber citations embedded in prose.
- Generate **role statements**, not questions, for new work. The requested initial
  wording was: "What role does this section play in this paper? Answer with a
  single concise statement, focusing on role not content."
- For the latest preparation experiment, use cleaned extraction, exclude existing
  generated annotations, send one request per unit, and cache the full paper prefix.
- For current Jev section calls, use top-level sections only. Include descendant
  paragraph/subsection text inside the parent, but remove their headings, markers,
  boundaries, and lower-level role statements from the section presentation.
- Put **Focus**, **Context**, and **Candidates** in that order. Full participating
  paper text must remain available; only the candidate options are selectable.
- A representative one-focus sample should keep the real eligible candidate pool.
  Do not restrict candidates to matching headings and call it the full forward pass.
- Keep the manual matcher completely local: no model calls, backend annotation
  storage, fabricated model provenance, or tutorial writes into real annotations.
- The latest authorized execution stopped after section matching. Do not infer
  permission to resume paragraph matching from the existence of a retry command.
- Distinguish actual sent requests from offline reconstructions, cache hits from
  new calls, model explanations from decision mechanisms, and tests from accuracy.

The user wants literal, direct reporting, salient results first, active voice,
and explicit status. For reports, use the no-ai-slop guidance. For formatted prose
documents, the user's default is 12-point Times New Roman, standard margins, black
and white, and no margin manipulation to meet a page limit. This Markdown handoff
does not change manuscript formatting.

Related manuscript work lives outside this checkout under the parent workspace's
`SME_CHI_27` and `SME_CHI_27_current` directories. Earlier format-only work preserved
draft text, alternate abstracts, and TODOs. Do not treat those files as disposable
templates or change them as part of application maintenance. Their current
publication readiness was not audited here.

## 4. Current experiments and artifacts

All paths in this section are relative to this repository and usually Git-ignored.
Run names identify experiments, not interchangeable versions of one result.

### Three-paper runs: November 16

**Choice step, old roles:** [runs/hci-three-paper-choice-20261116/](runs/hci-three-paper-choice-20261116/),
from the November 15 manifest with `--cache-from` the November 15 run. All 143
paper-3 yes/no calls replayed from cache; 26 new Jev calls plus one size
rejection (the 9-option User Study ranking, then split in half). Result:
**8 three-paper groups, 1 two-paper group (CS + EX Conclusion), 6 unmatched**.
Fixed relative to November 15: EX User Study and EX Results now join the
three-paper user-study and results groups; EX Acknowledgments joins directly.
Changed: EX System Architecture (not Scenario) joins the system-description
group; EX Scenario, CS Data & Processing, CS Qualitative Results, and AE
Ablation Study are now unmatched. Every paper-3 forward choice picked the
expected node; losses come from reverse choices and reciprocity.

**New roles, cleaned inputs:** roles in
[output/prepared-runs/hci-three-paper-roles-20261116/](output/prepared-runs/hci-three-paper-roles-20261116/)
(319 responses: 32 sections, 287 paragraphs; 3 cache writes, 316 reads). They
no longer name systems or features, and AE Formative Interview Study is no
longer described as a literature review, but they average about 370
characters: the prompt's "how it relates to the sections before and after"
yields long single sentences that describe position more than function. That
clause has since been removed from both role prompts; these roles predate the
removal. **Nov 17 rerun:** roles regenerated without the clause in
[output/prepared-runs/hci-three-paper-roles-v2-20261117/](output/prepared-runs/hci-three-paper-roles-v2-20261117/)
($2.02; section median 336 chars). Papers 1–2 were run alone as a reusable
checkpoint,
[runs/hci-two-paper-checkpoint-v2-20261117/](runs/hci-two-paper-checkpoint-v2-20261117/)
(39 Jev calls); start later runs with `--cache-from` it to replay papers 1–2 at no
cost.
[runs/hci-three-paper-roles-v2-20261117/](runs/hci-three-paper-roles-v2-20261117/)
added Examplore (165 new Jev calls, 20 rankings, no size rejections) and gave
exactly the same groups as the old-role choice run: 8 three-paper groups
(Results reunited), CS + EX Conclusion, 7 unmatched non-reference sections.
**Nov 18 section fan-in experiment:**
[runs/hci-three-paper-fan-in-20261118/](runs/hci-three-paper-fan-in-20261118/)
repeats that run with `start --section-fan-in` (cache from the Nov 17 run; 44
new Jev calls). Five one-way sections joined beside a reciprocal core of their own
paper: CS Qualitative Results (Results), CS Conclusion and EX Conclusion
(Discussion), EX Scenario and CS Data & Processing (system; the latter through
the reverse direction at paper 3). Result: 8 groups, all three-paper, sizes
5/5/4/3/3/3/3/3; no baseline co-membership was lost (25 of 41 pairs shared);
unmatched non-reference sections fell from 7 to 3 (AE Formative, AE Ablation, EX
Synthetic Code Skeleton). The default remains no section fan-in.
**Nov 18 five-paper run:** Mesotext and Paralib were cleaned (see the dataset
README) and given roles with the same prompt
([output/prepared-runs/hci-last-two-roles-20261118/](output/prepared-runs/hci-last-two-roles-20261118/),
$1.24); [output/prepared-runs/hci-five-paper-roles-20261118/](output/prepared-runs/hci-five-paper-roles-20261118/)
combines them with the unchanged Nov 17 roles for papers 1–3. The first attempt,
[runs/hci-five-paper-fan-in-20261118/](runs/hci-five-paper-fan-in-20261118/),
stopped at paper 4 when a yes/no question (Mesotext complete plus a node's latest
paper complete) was too large for Jev. Yes/no questions now retry with the node's
member sections only (`pair_context_reduced`; 33 of 370 pairs).
[runs/hci-five-paper-fan-in-v2-20261118/](runs/hci-five-paper-fan-in-v2-20261118/)
(`--section-fan-in`, cache from the failed run; 266 new Jev calls, 49 rankings)
finished: 9 groups (sizes 9/8/7/6/6/5/4/4/2; six span all five papers), 11 fan-in
members, 51 of 52 non-reference sections matched (only AE Ablation unmatched).
Every papers-1–3 pair from the three-paper fan-in run survived. New: AE Formative
paired with Mesotext Formative Interviews; Mesotext's User Study (which contains
its results subsections) joined Results. Questionable fan-ins: Paralib Abstract
into Introduction, EX Synthetic Code Skeleton into Related Work, Mesotext Case
Studies into Discussion. The first matching run,
[runs/hci-three-paper-new-roles-20261116/](runs/hci-three-paper-new-roles-20261116/)
(204 Jev calls), stopped at a Claude explanation for lack of credit. After the
explanation step was removed,
[runs/hci-three-paper-new-roles-v2-20261116/](runs/hci-three-paper-new-roles-v2-20261116/)
replayed it from cache and ran singleton recovery (7 new Jev calls), then stopped
at the first paper-3 group role (no credit). Its membership is final:
**7 three-paper groups** (Abstract, Introduction, Related Work, system
description with EX Scenario added by recovery at 0.77, User Study, Discussion,
Acknowledgments); **4 two-paper** (AE Results + CS Qualitative Results;
CS Quantitative Results + EX Results; CS Data & Processing + EX System
Architecture; CS + EX Conclusion); **unmatched** AE Ablation Study,
AE Formative Interview Study, EX Synthetic Code Skeleton. Compared with the
old-roles choice run, the system-description group keeps three papers and fewer
sections are unmatched, but the results sections split into two pairs. Papers 1-2 changed under the new roles (AE Results now pairs with
CS Qualitative rather than Quantitative Results).

### Three-paper pairwise section run: November 15

Directory: [runs/hci-three-paper-section-nodes-20261115/](runs/hci-three-paper-section-nodes-20261115/).
Manifest: `output/prepared-runs/hci-examplore-roles-20261115/three-paper.manifest.yaml`.

Examplore roles were prepared into
[output/prepared-runs/hci-examplore-roles-20261115/](output/prepared-runs/hci-examplore-roles-20261115/)
with `--policy-from` the November 12 receipts, so all three papers share the
original concise role wording (not today's edited prompt files): 72 responses
(11 sections, 61 paragraphs), one cache write, 71 cache reads.

The run used `--cache-from runs/hci-full-text-section-matches-20261113`. An
offline check first confirmed that all 29 paper 1-2 matching attempts (21 votes,
8 explanations) hit that cache. Papers 1-2 therefore reproduce the November 13
section decisions; their 8 group roles were regenerated under the new context.

Paper 3: 11 sections x 13 nodes = 143 pairwise gate calls, plus 9 recovery pairs
(152 `pair_scored` events). No exact ties occurred. Jev made 146 new calls of 191
total. Claude wrote new group roles and 10 accepted-match explanations.

| Group | Members |
|---|---|
| 3 papers | Abstract; Introduction; Related Work; Discussion (EX: Discussion and Limitations); Acknowledgments; system description (AE: AbstractExplorer, CS: Corpus Studio, EX: Scenario) |
| 2 papers, from Nov 13 | AE Summative User Study + CS User Study; AE Results + CS Quantitative Results |
| 2 papers, new | CS Data & Processing + EX System Architecture and Implementation; CS Conclusion + EX Conclusion; AE Ablation Study + EX Results; CS Qualitative Results + EX User Study |
| Unmatched | EX Synthetic Code Skeleton; AE Formative Interview Study |

Observations, not adjudicated: EX Results scored the AE Ablation singleton 0.91
and the AE Results/CS Quantitative Results group 0.84; EX User Study scored the
CS Qualitative Results singleton 0.91 and the user-study group 0.89. Off-target
gate scores of 0.8-0.9 were common, so top-1 selection did most of the work.
EX Acknowledgments' best forward choice was CS Conclusion + EX Conclusion (0.86);
it joined the Acknowledgments group only through singleton recovery (0.78).
Regenerated group roles lean toward the latest member's paper, which is the only
complete paper in their context.

### Cleaned first-two-paper inputs

Canonical inputs are in [datasets/hci-five-paper/content/](datasets/hci-five-paper/content/).
The first-two manifest orders AbstractExplorer before CorpusStudio. The
[corpus README](datasets/hci-five-paper/README.md) records the November 11 repair:
CorpusStudio's Participants material below Table 1 on PDF page 7 was restored,
and three merged paragraph boundaries were split. AbstractExplorer remains at
103 paragraphs; CorpusStudio now has 123, for **226 total**.

Bibliography entries and appendices are outside this cleaned corpus. "Full paper"
in the recent prompts means the full retained extraction, not every PDF byte or
every appendix/table/figure. Historical frozen inputs were not overwritten.

| Paper | Top-level sections | Subsections | Paragraphs | Role-generation units |
|---|---:|---:|---:|---:|
| AbstractExplorer | 10 | 20 | 103 | 133 |
| CorpusStudio | 11 | 25 | 123 | 159 |
| Total | 21 | 45 | 226 | 292 |

The older **221-paragraph** two-paper count belongs to earlier inputs. It remains
in some operational docs and must not be used for the cleaned current pair.

### Whole-paper role preparation: November 12

Directory: [output/prepared-runs/hci-two-paper-roles-20261112/](output/prepared-runs/hci-two-paper-roles-20261112/).

- `manifest.yaml` references `abstractexplorer.json` and `corpusstudio.json`.
- `responses.jsonl` starts with shared parameters, prompts, and full-paper prefixes,
  then records sent requests and responses by paper/focus.
- The audit counted **292 responses, 2 cache writes, and 290 cache reads** from
  provider-reported usage. Offline manifest validation found zero missing roles.
- The preparer uses direct Anthropic messages, not the uploaded role-writing Skill.
- Earlier inspection reported a median role length of 43 words, range 21-69, and
  roughly 2 minutes 51 seconds for that run. Those are historical observations,
  not a latency promise or a newly repeated timing measurement.

**The prepared roles do not use today's edited prompts.** The receipt header
contains the original concise prompts. Today's section prompt additionally asks
about the relationship to the rest of the paper; today's paragraph prompt asks
about the role in its section and the relationship to the rest of that section.
Matching reuses present annotations. Editing Markdown does not regenerate them.

### First role-statement matching run: November 13

Directory: [runs/hci-two-paper-role-statements-20261113/](runs/hci-two-paper-role-statements-20261113/).

This run used the 292 prepared roles and **subsection granularity**, before the
later top-level-only/full-paper Jev change. It compared 36 CorpusStudio structural
units with 30 AbstractExplorer units in the forward direction and voted in reverse.
The run entered paragraph work before the user said "pause".

Saved run state still has `current_revision: null` and
`latest_revision: revision-0001`; do not call it a completed dataset. A prior
session suspended its process. On November 15, the process inventory showed no
matching/role-preparation process, only the local viewer. Do not try to resume a
historical PID or describe a now-absent process as currently suspended.

The saved abstract traces show:

| Direction | Gate | Highest-ranked candidate |
|---|---:|---|
| CorpusStudio abstract -> AbstractExplorer | 0.64 | Abstract, 0.96 |
| AbstractExplorer abstract -> CorpusStudio | 0.81 | Abstract, 0.93 |

Forward is `attempt-000001`; reverse is `attempt-000042`; the later Claude
explanation is `attempt-000067`. These results were read from the prior trace
inspection; they were not rerun in this audit. The two abstracts became reciprocal
matches. Claude's explanation followed the decision and cannot establish which
prompt change caused Jev's scores to differ from older runs.

### Full-paper/top-level abstract sample: November 13

Directory: [runs/hci-full-text-sections-abstract-sample-20261113/](runs/hci-full-text-sections-abstract-sample-20261113/).

The user first requested full text of both papers and then clarified top-level
sections only. This sample makes one forward decision: CorpusStudio's abstract
against all 10 AbstractExplorer top-level sections, with CorpusStudio's remaining
10 sections as context. The saved request layout is Focus/Context/Candidates,
with Section/Role/Content for each section.

The prior inspection verified all 226 retained paragraphs appeared once per
request, in source order within each section. The gate returned **0.94**; ranking
returned **A1 Abstract at 0.92**. The receipts reported 28,901 and 29,038 input
tokens respectively. This was two API calls for one directional decision, not a
reverse pass, explanation, or graph merge. The token counts are historical usage,
not a general request-size estimate.

### Latest section-only run: November 13

Directory: [runs/hci-full-text-section-matches-20261113/](runs/hci-full-text-section-matches-20261113/).

The full section pass reused the sample's exact forward abstract calls. Its
`cache-source.json` points to the sample; its first decision marks both Jev calls
as cache hits. Other cache records therefore must not automatically be counted
as newly purchased calls.

The audit read `revisions/revision-0001/section-checkpoint.json` and confirmed
13 section groups: **8 pairs and 5 singletons**, covering 21 sections. The journal
has 21 directional section votes, 8 accepted-match explanations, and 8 group-role
judgments. There are no paragraph-stage attempts in this checkpoint run.

| AbstractExplorer | CorpusStudio |
|---|---|
| Abstract | Abstract |
| Introduction | Introduction |
| Related Work | Background and Related Work |
| AbstractExplorer | Corpus Studio |
| Summative User Study | User Study |
| Results | Quantitative Results |
| Discussion | Discussion |
| Acknowledgments | Acknowledgments |

Unmatched sections, as recorded in the prior decision inspection:

- AbstractExplorer **Ablation Study**: Jev returned no match.
- CorpusStudio **Data & Processing** and **Conclusion**: Jev returned no match.
- AbstractExplorer **Formative Interview Study** selected Background and Related
  Work, but that section did not select it back.
- CorpusStudio **Qualitative Results** selected Results, but Results selected
  Quantitative Results instead.

"All sections processed" does not mean every section has a partner. Unmatched
sections are valid outputs, not automatically defects to eliminate.

The checkpoint intentionally does not write a completed paragraph dataset or set
`current_revision`. `latest_revision` is `revision-0001`. The new viewer exposes
it as a section map; the trace can still describe the overall run as unfinished.
Do not manufacture `summary.json`, a paragraph snapshot, or a success pointer.

### Earlier results worth retaining

| Artifact | What it establishes and what it does not |
|---|---|
| `runs/hci-first-three-jev-singletons-20261105-verified/revisions/revision-0001/` | Completed three-paper historical run: 612 attempts and 1,753 events. Uses old question-era policy/subsection inputs. The word `verified` in the directory name is not a semantic accuracy certification. |
| `runs/hci-first-three-jev-singletons-20261105/` | Two failed revisions preserve evidence errors: wrong quotation counts, then focus/target quotation attribution swaps. Do not mistake it for the completed `-verified` run. |
| `runs/hci-first-three-jev-probability-20261025-01/` | Failed when Anthropic reported insufficient credit. This is an old account failure, not evidence of current balance. |
| `runs/hci-first-two-jev-uncapped-20261025-01/revisions/revision-0001/` | Completed earlier two-paper Jev result used in comparison tooling. Different policy from November. |
| `runs/hci-section-medium-excerpts-20260917/revisions/revision-0013/` | Earlier five-paper HCI result; prior inspection reported 459 paragraphs. The current cleaned five-paper corpus is larger. |
| `runs/reuters-technology-jev-singletons-20261105/revisions/revision-0001/` | Completed five-article, paragraph-only run: 555 attempts and 870 events. Current audit re-read its summary. |
| `runs/hci-two-paper-forward-sample-20261111/` | One section and one paragraph decision after extraction repair. Its Participants section test restricted candidates to two Participants subsections. The 0.98 choice was not a full-pool result. |
| `output/jev-prompt-comparison/` | Saved payload illustrations, frozen-pool comparisons, and offline request reconstructions. Check each page's provenance before treating it as an actual call. |

The November 5 abstract mismatch was traced to the existence gate: 0.32 forward
and 0.50 reverse, neither strictly above 0.50. Ranking never ran in those cases.
Changing roles, source inputs, prompt layout, context, and granularity across later
experiments prevents a causal claim about which change improved that outcome.

## 5. What the current pipeline does

### Source preparation and identity

[pipeline/document.py](pipeline/document.py) owns the canonical nested document
shape, generated-label fields, positional IDs, and local hierarchical relabeling.
New annotations use `role_statement`. Some old inputs use
`question_this_text_answers`; historical viewer snapshots use
`overarching_question`. Explicit legacy-reading support does not make those the
preferred output fields for new work.

[pipeline/extraction.py](pipeline/extraction.py) extracts a new source separately
from graph construction. `_cache/source-extractions/` retains first responses and
approved copies keyed by source bytes. Uncertain previously sent extractions stop
rather than silently buying another request. Do not re-extract unchanged papers
just because a graph prompt changed.

[pipeline/source_review.py](pipeline/source_review.py) checks source coverage and
review receipts. PDF layouts still require visual review of boundaries, ownership,
footnotes, and exclusions. A valid JSON shape does not prove faithful extraction.
Generated annotations are outside the authored-content approval hash.

[input_data.py](pipeline/incremental_graph/input_data.py) projects canonical
documents to `section`, `subsection`, or `paragraph` granularity. In section mode,
descendant paragraphs fold into their top-level owner. Paragraph-only mode requires
one top-level section per paper and uses a deterministic shared root.

Subsection granularity was removed on November 15; the former Jev-only
`subsection`-to-`section` override is gone. Older manifests and frozen runs that
say `subsection` no longer load with current code.

### Whole-paper role preparation

[pipeline/prepare_roles.py](pipeline/prepare_roles.py) is a separate preparation
step. It strips prior annotations, builds the full cleaned paper prefix, and sends
one focus-specific request per nonempty section, subsection, or paragraph. A section
includes its descendants; the full paper is available when a subsection or paragraph
is the focus. It saves annotated derivatives for the graph, not edits to raw sources.

It warms each paper's prompt cache serially, verifies a hit, then permits parallel
requests. CLI default is three workers; the inspected historical run used four.
It rejects changed inputs/prompts in the same output directory and unresolved
sent requests. Replaying completed receipts is distinct from provider prompt-cache
reuse. Do not run two writers against one preparation directory.

Remaining request-design limitations are concrete: the system instruction is still
hard-coded in Python; subsection wording uses literal string replacement of
`this section`; focus addresses do not state an explicit end boundary. The previous
audit found the full descendant text present, so this is scope clarity and
maintainability work, not a confirmed omission of that text.

### Matching and graph acceptance

[runner.py](pipeline/incremental_graph/runner.py) orchestrates stages;
[match_rules.py](pipeline/incremental_graph/match_rules.py) implements pure
acceptance rules; [graph.py](pipeline/incremental_graph/graph.py) owns mutations
and replay. Documents enter in manifest order. Results can depend on that order.

For a normal complete run, each insertion performs structural matching and
reconciliation, group-role generation, structural singleton recovery, reparented
child processing, paragraph matching, and paragraph singleton recovery. A
section-only run stops before all paragraph work, including recursive child work.

Both levels use independent forward and reverse top-1 choices. Reciprocal choices
form the accepted core. Section matching does not admit paragraph-style fan-in
unless the experimental `section_fan_in` setting (`start --section-fan-in`) is on;
then the same adjacency rule applies to top-level sections, and a fan-in member is
the one allowed second section from a paper in a group.
At paragraph level, an eligible immediately adjacent one-way selection can join an
accepted reciprocal core. Fan-in does not recursively extend through other fan-in
members. Paragraph eligibility stays within the exact accepted structural scope;
showing full paper text does not make all paragraphs eligible candidates.

Singleton recovery revisits old singletons after insertions, uses frozen pools and
independent directions, and merges mutual choices. A structural merge reparents
its existing paragraph nodes. The algorithm does not split established groups,
repeat until convergence, or search a globally optimal relational alignment.

If matched structural units each contain exactly one paragraph, their paragraph
match can inherit the structural match without selection or explanation calls.
Multi-paragraph sections still follow the ordinary paragraph process.

### Jev decides; Claude no longer explains

[jev_selection.py](pipeline/incremental_graph/jev_selection.py) constructs the
body; [pipeline/providers/jev.py](pipeline/providers/jev.py) sends it. Configured
Jev model is `jev-1.14.0`; the generative configuration names `claude-sonnet-5`.
These are observed repository settings, not a claim about future API availability.

For each directional choice:

1. An empty eligible pool produces no call.
2. Jev receives one `has_match` Noul question. At a score of 0.50 or below, the
   result is null and there is no ranking call.
3. Above 0.50, one candidate wins directly. Multiple candidates require a separate
   `match` Choice request over the same evidence state.
4. Python maps visible labels back to real IDs and records the directional vote.
5. Python applies reciprocity/fan-in/recovery rules.

On November 16 the user removed the accepted-match explanation step: Claude no
longer explains accepted matches, the explain-match Skill and quotation-catalogue
repair were deleted, and `CachedJudgments.judge` refuses Jev match requests. Votes
remain in provenance with their Jev responses. Older runs still contain
`accepted_match_explained` events and explanation attempts; the trace viewer reads
them. Do not discard rejected responses or silently normalize them into success.

Choice decoding uses the largest returned probability, correcting an inconsistent
reported `choice` while retaining both raw and effective choices in provenance.
Ties keep the reported choice if it is tied for highest; otherwise selection uses
lexicographic order. Scores are not calibrated across different request pools.

### Evidence layout and request size

[evidence.py](pipeline/incremental_graph/evidence.py) snapshots source material and
accepted memberships; [jev_outline.py](pipeline/incremental_graph/jev_outline.py)
renders it. Current section records look like this:

```text
Focus
Section: B1 CorpusStudio / Abstract
Role: <saved role statement>
Content: <complete retained section text>

Context
<other participating sections, plus applicable accepted-match context>

Candidates
Section: A1 AbstractExplorer / Abstract
Role: <saved role statement>
Content: <complete retained section text>
<other eligible top-level sections>
```

Section content joins extraction line breaks with spaces but preserves words and
punctuation. Paragraph-mode outlines retain paragraph addresses/roles and full
participating-paper context. Accepted prior memberships are context; rejected
votes and future decisions are not accepted prior matches.

The current full-paper route raises a size error rather than retrying smaller
pools after a request-size rejection. Older/windowed routes retain hierarchical
splitting, and the >255-choice handling remains in the selector. Do not describe
the new complete-paper policy as universally covered by the old splitting prose.
Large corpora and the new paragraph full-context path remain a cost/context risk.

### Persistence and policy boundaries

[runs.py](pipeline/incremental_graph/runs.py) freezes inputs, saves per-revision
configuration, and maintains `latest_revision` versus `current_revision`.
`retry` performs cached replay into a new revision; it does not resume a suspended
Python stack. `add` also replays the ordered process with the new papers included.

Scientific identity includes relevant code, configuration, prompts, contexts,
Skills, and installed dependency versions. The code hash includes
`pipeline/incremental_graph/export.py` and hashes file bytes, so even changes that
look like output-only edits or line-ending changes can affect retry eligibility.
Do not overwrite saved policy hashes to force acceptance.

`--cache-from` copies a cache into a separate new run. Exact-request validation
still controls reuse; copying a cache does not make all old decisions valid under
new wording. New code accepts a sample with a cache and `sample.json` as a source
even if it lacks `run.json`. The historical sample remains unchanged.

## 6. Editing and inspecting prompts

The user wants to edit generic wording and immediately understand its effect,
without changing individual saved role statements or unrelated pipeline behavior.
The current practical entry point is the source files in VS Code and the prompt
guide. A general prompt-editing web app was discussed but not implemented.

| Desired change | Authoritative source | Important dependency |
|---|---|---|
| Section role wording | [section system.md](prompts/graph/section-role-statement/v1/system.md) | Whole-paper preparer derives subsection wording by string replacement |
| Paragraph role wording | [paragraph system.md](prompts/graph/paragraph-role-statement/v1/system.md) | Current wording asks about its section; old prepared roles used paper-level wording |
| Shared group role | [group system.md](prompts/graph/group-role-statement/v1/system.md), [role Skill](prompts/skills/generate-role-statement/SKILL.md) | Group roles describe accepted membership; they do not choose it |
| Section existence/ranking policy | [jev.json](prompts/requests/jev.json) | Top-level `has_match_question`, `ranking_question`, `policy`, `gate_example`, `rank_example` |
| Paragraph matching policy | [jev.json](prompts/requests/jev.json) | `paragraph_to_paragraph`, `paragraph_to_group`, `paragraph_to_mixed`, `group_to_paragraph` replace the generic wording |
| All Jev outline interpretation | `outline_rule` in [jev.json](prompts/requests/jev.json) | Appended across routes |
| Source selection, grouping, text placement | `evidence.py`, `jev_outline.py`, `input_data.py` | These are Python behavior, not Markdown substitutions |
| Graph template assembly | [configuration.py](pipeline/incremental_graph/configuration.py), [judgments.py](pipeline/incremental_graph/judgments.py) | Schemas, context, cache identity, and Skills participate |
| Provider/extraction/repair instructions | [prompts/requests/](prompts/requests/) | `providers.json`, `extraction.json`, `evidence.json`, `evidence-repair.json` |

Jev's `criteria` field is the allowed-answer map, not a scoring rubric or the source
passages. For ranking it currently repeats the visible option label as its value
because the passage is already in `state`. Read `instructions` for how to decide
and `criteria` for what answers are allowed.

Restart the Python process after editing prompt files. For changed role wording,
prepare from cleaned inputs into a new output directory. For changed matching
policy, start a new run. Reusing an already annotated manifest deliberately reuses
its roles; do not claim that a Markdown edit updated those saved statements.

### Where to inspect exactly what was sent

| Artifact | Inspect |
|---|---|
| `cache/jev/<fingerprint>.json` | Exact request body and validated response |
| `cache/jev/responses/*.json` | Individual raw HTTP receipts, including failures; `request.state`, `request.questions`, and raw response text |
| `cache/responses/*.json` | Generative messages, output schemas, usage, and newer SDK parameter records |
| `cache/rejected/*.json` | Rejected judgments and validation diagnostics |
| `revisions/<revision>/provenance/attempts.jsonl` | Stage, request key, candidates, result, cache status, prompt/Skill identity, and Jev call fingerprints |
| `revisions/<revision>/provenance/events.jsonl` and `events.json` | What decisions changed in the graph; includes references to vote and explanation attempts |
| `revisions/<revision>/stages/` | Saved stage-level state for diagnosis |
| Prepared-role `responses.jsonl` | Header plus focus-specific request/response reconstruction for the direct Claude preparation route |

Older Claude receipts lack some SDK parameters. Uploaded Skill contents are not
embedded in every receipt; use recorded version/source hashes and matching source
history. Do not invent a complete historical request from today's defaults.

Set breakpoints in `JevSelector._request_and_labels`, the nested `ask` function's
cache lookup, `self.client.choose(body)`, and the HTTP send in `JevClient`. Line
numbers drift. A cache hit skips the live send breakpoint. Inspect saved artifacts
before forcing a miss and buying another call.

## 7. Interfaces and earlier completed work

### Local run viewer and trace

The viewer is plain TypeScript, not React. Shared schemas validate Python exports
and browser loading. The full dataset offers Passage Groups, Paper Map, and
Graphical Explorer. The explorer is a deterministic reading-order layout, not an
additional matching algorithm.

The local trace provides Decisions, Graph replay, and API archive. It reads saved
records and makes no model calls. The archive can include inherited, failed,
rejected, or unreferenced receipts; only linked events establish graph effects.

At audit time an existing viewer process served port **8074**. The checkpoint
endpoint returned two papers, 21 sections, zero paragraph records, and 13 groups.
The prior session browser-verified this section Paper Map. This audit rechecked its
HTTP data and ran the regular viewer tests, but did not repeat that exact manual UI
inspection. Ports/processes are transient.

- [Latest section Paper Map](http://127.0.0.1:8074/?run=hci-full-text-section-matches-20261113&revision=revision-0001)
- [Latest section trace](http://127.0.0.1:8074/trace?run=hci-full-text-section-matches-20261113&revision=revision-0001)

The trace remains local. Do not publish caches or source-rich trace records by
deploying the repository root.

### Manual annotation tool

[pipeline/manual_matcher/](pipeline/manual_matcher/) supports two-document,
many-to-many annotation at section/subsection and paragraph levels, independent
granularity workspaces, outside-structural-group matches, optional roles, local
autosave, resumable JSON, and viewer ZIP export. It validates an exact partition:
no unknown, duplicated, or omitted units.

Its eight-step tutorial uses separate practice state and must never overwrite real
labels. New saved sessions use schema version 2 and role statements; version 1
question-label sessions remain explicitly readable. Exported labels do not become
ground truth merely because they are structurally valid or complete as a partition.
No adjudication study was established by building this tool.

### Saved run comparison and public packaging

[pipeline/incremental_graph/compare.py](pipeline/incremental_graph/compare.py)
and [pipeline/comparison_viewer/](pipeline/comparison_viewer/) compare source-linked
memberships rather than generated group IDs. They report shared/lost/added pairs,
coverage, pair agreement, group overlap, and label similarity. Shared-source mode
is explicit; changed text for a common ID is rejected. Word-similarity scores are
not semantic truth, and agreement between two model runs is not accuracy.

Historical configured/public locations are below. They were not remotely checked
or redeployed during this handoff, and local November changes may not be published.

- [Manual matcher](https://question-atlas-labels.vercel.app/)
- [Run comparison demo](https://smelter-run-comparison.vercel.app/)
- [Run catalog](https://question-atlas-runs.vercel.app/)

On November 16 the run catalog was redeployed from `site/run-library-20261116/`
with the three-paper section run added as a sections-only revision
(`package_catalog.py` now publishes section checkpoints as `section-map.json`,
with source text removed). The other 14 runs' data was byte-identical to the
November 5 package; only the viewer build changed. On November 17 it was
redeployed from `site/run-library-20261117/` with
`hci-three-paper-roles-v2-20261117` added (sections only, source text redacted);
the other 15 runs are byte-identical to the November 16 package. On November 18
it was redeployed from `site/run-library-20261118/` with
`hci-three-paper-fan-in-20261118` added (sections only, source text redacted; the
viewer does not mark fan-in members); the other 16 runs are byte-identical to the
November 17 package.

The tracked catalog documentation says only the Reuters runs include paragraph
source text in the public package; other run packages omit it. The comparison
demo is a separate artifact with its own source-text exposure. Review the specific
package rather than assuming all public outputs have the same privacy boundary.

### Earlier engineering and research work

- Provider bookkeeping, Skill registration, request schemas, and prompt ownership
  were consolidated to remove duplicate implementations. Runtime assets now live
  under `prompts/graph`, `prompts/contexts`, `prompts/skills`, and `prompts/requests`.
- Reciprocal singleton realignment was corrected to run per insertion at both
  levels, including paragraph-only mode and reparented child scopes. Offline tests
  cover an older singleton joining a group created by a third document.
- Strict candidate enums, source-quotation checks, paid-response retention, and
  bounded evidence repair replaced ad hoc runtime identity repair.
- [Sherlock assessment](docs/sherlock-experiment.md) documented neighbor attribution
  errors, inconsistent abstraction, insufficiently justified role matches,
  fragmented paragraphs, and the limits of local top-1 selection. Those are
  historical observed failures and continuing evaluation concerns, not proof that
  every example still fails under the latest prompts.
- [Legal extraction audit](docs/history/legal-extraction-audit-20260910.md) repaired
  merged dissent paragraphs and interleaved footnotes with stored source evidence.
  Those repairs demonstrated why schema validation alone is insufficient.
- [Legal few-shot experiment](docs/history/legal-fewshot-comparison-20260910.md)
  increased comparison coverage and one plausible match, but retained topical
  abstention and inaccurate rationales. A stochastic rerun did not isolate the
  prompt's causal effect.
- [HCI rescue](docs/history/hci-rescue-20260907.md) preserved an older mixed-policy
  diagnostic with explicitly limited evidence. It is not a clean benchmark or a
  model for allowing generic ID repair in the current runtime.

Use [docs/history/README.md](docs/history/README.md) to distinguish historical
reports from current procedures. Some dated helper scripts have been retired.

## 8. Known problems and unfinished work

### Confirmed in this checkout

| Issue | Evidence and consequence | Next action, not performed here |
|---|---|---|
| Existing November 13 runs cannot retry under current policy | Recomputed `_policy_hash` differs for both the role-statement run and the section-only run. No retry was attempted. | Reconstruct the exact original policy, or create a separately identified new run with exact-request cache reuse after user approval. Never replace the saved hash. |
| Latest work is not portable through Git alone | Nine local commits, 22 modified files, and ignored run/preparation artifacts. | Review/commit scoped changes and separately transfer selected data if requested. |
| Documentation contradicts implementation | See the specific list below. | Update or clearly date superseded prose/diagrams without rewriting historical results. |

The policy audit established a mismatch, not a complete attribution of its cause.
In particular, `export.py` changed for the section map and participates in the code
hash. Dependency and byte-level changes also matter. Do not assume restoring one
file will necessarily make a run resumable.

### Documentation discrepancies

- The root README and the real-corpus section of `docs/jev.md` still say 221
  paragraphs for the first pair; current prepared inputs contain 226.
- `PIPELINE_FLOW.md` and a later portion of `docs/jev.md` say every non-null
  directional Jev choice gets an explanation before reconciliation. Current
  `runner.py` explains accepted matches after reconciliation.
- Later Jev prose still describes focus-then-candidates, section paragraph rows,
  and size splitting without the newer full-paper/top-level limitations. The new
  introductory paragraphs and `prompts/README.md` describe the newer path.
- `docs/jev.md` suggests a plain retry after section-only execution. That is valid
  only if the saved policy still matches; the inspected checkpoint does not.
- `docs/architecture.md` says graph judgments use native Skills, which is true of
  that route, but should not be read as describing `pipeline.prepare_roles`.
- Old guides describe missing OpenAI credentials and particular historical costs.
  They do not establish today's credentials, billing, or API compatibility.

This document records those differences instead of silently rewriting all old
documentation during a handoff request.

### Not finished, not necessarily broken

- Paragraph matching under the latest full-paper/top-level-section experiment has
  not been authorized or completed. The prior subsection run's partial paragraph
  results are not results for the new policy.
- The section checkpoint has no full dataset, summary, or successful revision
  pointer by design. A status-label improvement may help, but do not mislabel it
  as completed paragraph processing.
- Dedicated section-map endpoint and browser-model regression coverage is thin.
  The Python suite tests stopping before paragraph stages, but the current viewer
  tests do not specifically exercise the new `buildSectionMap`/checkpoint route.
- The user still finds prompt construction difficult to navigate. A source-backed,
  offline exact-request preview with a saved-versus-current diff was suggested;
  no general preview/editor workflow was implemented. Existing frozen comparison
  helpers and generated HTML examples do not provide that complete workflow.
- Whole-paper role focus boundaries could be made explicit without duplicating
  source text. Subsection string substitution and hard-coded system wording remain.
- The direct role-preparation route is Anthropic-specific. A configurable graph
  provider does not automatically make that route OpenAI-compatible.
- The OpenAI native-Skill graph adapter has offline tests. No current live end-to-end
  OpenAI graph validation was established in the inspected evidence.
- Full-paper Jev context may be expensive or exceed context limits with more
  documents. The current two-paper section result does not validate that scale.

### Scientific limitations still requiring evaluation

We need adjudicated source-level matches and no-matches, not just higher shared
group counts. The manual labeling tool exists, but this audit found no basis to
claim a completed gold-set evaluation of the newest policy.

Evaluate center attribution, role correctness, false positives, abstention,
candidate-pool effects, insertion-order sensitivity, and spend separately. Hold
inputs, granularity, models, generation, and candidate pools fixed when comparing
one prompt change. Do not compare the old 221-paragraph/question-based run to the
new 226-paragraph/role-based/top-level run as if only Jev changed.

An early wrong shared group is not split by singleton recovery. Functional units
can span printed paragraph boundaries. Formal relation/argument consistency and
systematicity remain outside the present algorithm. Proposed functional-block or
explicit-relation experiments are hypotheses, not implemented requirements.

## 9. Validation performed for this handoff

These checks ran on November 15 against the existing working copy, not only HEAD.
They use local fixtures/mocks and browser test data, not paid models.

| Check | Result |
|---|---|
| `py -3.11 -m unittest discover -s tests -q` | PASS: 228 tests |
| `py -3.11 -m ruff check pipeline tests helpers` | PASS |
| `py -3.11 -m ruff format --check pipeline tests helpers` | PASS: 87 files already formatted |
| `npm run build:viewer` | PASS, including `tsc --noEmit` |
| `npm run test:viewer` | FAIL: 18 passed, 1 stale error-message assertion |
| `npm run test:matcher` | PASS: 14 tests |
| `node --test tests/comparison-viewer.test.mjs` | PASS: 13 tests |
| `npm run format:check` | FAIL: four files listed above |
| Prepared first-two role manifest validation | PASS: 292 roles, zero missing section/paragraph statements |
| Role response receipt count | 292 responses; 2 cache writes; 290 cache reads |
| Latest checkpoint inspection | 8 pairs + 5 singletons; only structural attempts |
| Existing local section-map HTTP endpoint | PASS: 2 papers, 21 sections, 0 paragraph records, 13 groups |
| Saved-policy comparison for both November 13 HCI runs | MISMATCH; no paid retry attempted |

The audit did not rerun extraction, call Claude/Jev/OpenAI, adjudicate semantic
correctness, recheck public deployments, build the manual matcher deployment,
compile the manuscript, or fetch/push Git remotes. Historical UI checks and timings
remain identified as historical above.

## 10. Safe operational starting points

Run these from the nested application root. Python 3.11 and Node.js 22 are the
documented environment. Use the pinned requirements and lockfile; changing
dependencies can also change policy identity.

### Read-only or offline

```powershell
Set-Location 'C:\HBS\Glassman Lab Research\hypothesis\SME-prototype-elena-clean'
git status --short --branch
git log -12 --oneline
py -3.11 -m pipeline.incremental_graph.cli validate output/prepared-runs/hci-two-paper-roles-20261112/manifest.yaml
```

To serve saved results, choose an unused port and leave any existing process alone:

```powershell
py -3.11 -m pipeline.viewer.server runs --port 8074
```

Serving, reading the trace, and replaying events make no model calls. If launching
a background helper on Windows, keep its window hidden. Do not kill a process just
because it owns a desired port; first identify it and its purpose.

### Paid commands: examples only, require an authorized experiment

New role generation, using an unused destination:

```powershell
py -3.11 -m pipeline.prepare_roles datasets/hci-five-paper/content/first-two.manifest.yaml output/prepared-runs/NEW-ROLE-EXPERIMENT
```

New section-only Jev experiment, using the specifically chosen prepared roles:

```powershell
py -3.11 -m pipeline.incremental_graph.cli start output/prepared-runs/hci-two-paper-roles-20261112/manifest.yaml runs/NEW-SECTION-EXPERIMENT --jev --sections-only
```

Removing `--sections-only` permits paragraph work. `retry RUN_DIR` also defaults
to full processing and is not a harmless status command. It must pass policy and
input checks, and uncached operations can incur charges. Stage-forced retries can
rebuy judgments. There is no default provider-enforced spending ceiling; optional
local call/token guards are not billing guarantees.

The VS Code profile in [.vscode/launch.json](.vscode/launch.json) is explicitly a
**paid** launch. It starts a fresh debug run from the historical three-paper HCI
frozen manifest, not the new two-paper checkpoint, and it does not include
`--sections-only`. Do not press F5 expecting read-only inspection.

### Recommended next work, subject to the user's request

1. Preserve the working copy and local experiment artifacts; inspect the diff
   before committing anything. Do not combine unrelated edits or rewrite history.
2. Repair the stale viewer assertion and add focused section-checkpoint/map tests.
   Keep formatting cleanup separate from scientific behavior changes.
3. Correct the contradictory operational documentation so the actual continuation
   boundary, effective granularity, and explanation timing are clear.
4. Decide whether to inspect the current section result further, regenerate roles
   under the edited wording, or authorize a new paragraph experiment. These are
   different experiments and need separate names and evidence.
5. If execution is authorized, resolve policy compatibility before attempting paid
   continuation. Keep the current checkpoint and all earlier inputs immutable.
6. Evaluate a small adjudicated set before expanding the corpus or claiming that
   the newest representation improves accuracy.

## 11. Evidence and maintenance notes

This handoff used the current source/diff, Git log, canonical data, role receipts,
run/checkpoint/journal files, local HTTP data, tests, and the recent project chat
**Find Jev abstract mismatch rationale** (`01a182c4-6bdf-7f00-a5df-718272ed3223`).
That chat records the November 11-13 source repair, role switch, prompt discussion,
pause request, full-text section restriction, and section-only result. Earlier
repo-maintenance and manuscript context came from project-specific saved summaries.

On this machine, additional historical context is under
`C:\Users\kanis\.codex\memories\MEMORY.md`, the corresponding
`rollout_summaries` directory, and `C:\Users\kanis\.codex\sessions`.
Those are local recovery aids, not repository dependencies. Search only the
relevant project entries; do not copy unrelated conversations or secrets into Git.

This document is a curated handoff, not a claim that every historical conversation
was exhaustively reviewed. If a precise old decision matters, follow its saved
artifact or chat rather than treating a summary as current execution evidence.

When updating this file, change the date, branch/commit snapshot, experiment status,
test results, and known problems together. Keep observations, proposals, historical
failures, and authorized next actions distinct. Never replace a failed result with
an undocumented success claim.
