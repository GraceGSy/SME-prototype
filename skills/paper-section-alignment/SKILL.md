---
name: paper-section-alignment
description: Compares the section/outline structure of two academic papers (PDFs) by independently mapping each paper's top-level sections onto their closest counterpart in the other, then checking which mappings hold up when reasoned about from both directions. Produces a confirmed "common section structure," "alignable diffs" (sections in both papers with no confirmed match), and "non-alignable diffs" (sections with no counterpart at all). Use whenever the user wants to compare the structure/outline of two papers or PDFs, align sections between two documents, find common structure between two papers, ask how two papers' organization differs, or wants to know which sections of one paper correspond to which of another — even if they don't say "section mapping" or name this skill. Also trigger for "does paper A have anything like paper B's related-work section" or "map these two papers' sections onto each other."
---

# Paper Section Alignment

## Why bidirectional reasoning matters here

A single pass of "for each section in Paper A, what's the closest match in Paper B?" is easy to fool. Section titles can coincidentally look similar ("Results" in one paper vs. "Results" in another) while covering different content, and a plausible-sounding match in one direction can hide the fact that Paper B's side of that pairing actually belongs somewhere else. The fix used here is to reason about the mapping **twice, independently** — once starting from Paper A's sections, once starting from Paper B's — and then only trust the pairings that both passes agree on. Where they disagree, that disagreement is itself useful information: it usually means the two papers organize that content in a genuinely different way, not that the mapping is wrong.

## Inputs

Two PDF paths. Call them `paper1` and `paper2` in the order the user gives them (or ask if it's ambiguous which is which). Keep this assignment fixed for the whole workflow — every output field uses `paper1_` / `paper2_` prefixes tied to these specific files, not to "whichever paper is more relevant in this direction."

## Workflow

### Step 1: Extract each paper's top-level section titles

Use `pdftotext` on each PDF (try `-layout` first; if the paper uses a two-column layout and headers come out garbled or interleaved with running headers/footers, fall back to plain `pdftotext`, which usually preserves reading order better for column text even though it loses spatial layout). Look for the numbered top-level headers (e.g., "1 Introduction", "2 Related Work") — these are usually a lone digit followed by a capitalized title, sometimes split across two lines by the PDF's rendering. Don't just grep once and assume you found everything — cross-check against the paper's actual page count and skim for missed sections (subsections numbered "2.1" etc. don't count as top-level).

### Step 2: Read each section's actual content

Titles alone are not reliable enough to map on — "Results," "Discussion," and "Evaluation" mean different things paper to paper, and a paper's single "Results" section might really correspond to two separate sections in the other paper (or vice versa). Pull the paragraph text under each top-level section before judging correspondence.

**What you're reading for is the section's role in the paper's argument, not its topic or methodology.** Ask "what job is this section doing in the overall narrative — what question is it there to answer, and where does it sit in the arc from problem to contribution to evidence to reflection?" That's the basis for correspondence. Whether two sections use the same *kind* of evidence to do that job (interviews vs. a stated rationale; a controlled experiment vs. self-reported survey ratings) is a separate question, and a difference there is not, by itself, a reason to reject the match — it's often exactly the kind of substantive difference between the two papers that's worth surfacing in `basis`. A weak match because the sections play the same role but fill it differently is a real, informative match. A rejected match because the sections happen to cover different subject matter or different flavors of evidence, despite doing the same job in their respective papers, is a mistake — see "Common mistakes to avoid" below.

### Step 3: Map paper1 → paper2

For each section in `paper1`, identify its single closest corresponding section in `paper2`, based on both title and content.

- **If one section legitimately corresponds to multiple sections in the other paper** (e.g., paper1's single "Results" section covers what paper2 splits into "Qualitative Results" and "Quantitative Results"), create a **separate entry for each** correspondence — do not combine them into one entry with a combined name like "Qualitative Results + Quantitative Results". This matters mechanically: Step 5's bidirectional check is an exact match, and a combined label will never match the other direction's separate entries even when they're saying the same thing.
- **If the match is weak, check whether it's weak on *role* or weak on *topic/method* — only the former disqualifies it.** Two sections match if they occupy the same position in each paper's argument and answer the same underlying question, even if they go about answering it completely differently. For example: paper1's "Formative Interview Study" (a section reporting empirical interviews that shaped the design) and paper2's "3.1 Design Goals" subsection (a paragraph asserting design rationale, no interviews involved) are a *real match* — both are "the section that explains what motivated this design," both sit in the same place in the paper (right before the system is introduced), even though one is backed by fieldwork and the other isn't. That difference in *how* each paper fills the same role is worth a sentence in `basis` — it's informative, not disqualifying. Don't reject a match just because the content, methodology, or rigor differs; reject it only if the sections are doing genuinely different jobs in their respective papers.
- **The analog is allowed to be a subsection, not just a top-level section.** If paper2 has no top-level section playing paper1's role, but a subsection buried inside a larger section does, name that subsection (e.g. `"CorpusStudio (§3.1 Design Goals)"` with `paper2_section_number: "3"`) rather than defaulting to null.
- **If there is truly no counterpart at all** — nothing, at any level, plays that role in the other paper — set `paper2_section_name` and `paper2_section_number` to `null` rather than forcing a bad match. `null` means "this job isn't done anywhere in the other paper," not "this job is done differently or less rigorously in the other paper." If you can point to *any* passage that's clearly trying to answer the same underlying question, name it — even a single paragraph — rather than defaulting to null.

Each entry needs these fields:

| Field | Description |
|---|---|
| `paper1_section_name` | Section name/title from paper1 |
| `paper1_section_number` | Section number from paper1 (as a string, e.g. `"3"`) |
| `paper2_section_name` | Closest corresponding section name in paper2, or `null` |
| `paper2_section_number` | Corresponding section number in paper2, or `null` |
| `basis` | Why these sections correspond — cite specific content overlap, not just title similarity. If weak or null, say why. |
| `question_the_sections_both_answer` | One question that both sections are fundamentally trying to answer — about their *role* in the paper (e.g. "what motivated this design?", "how was the system evaluated?"), not about shared subject matter or method. This is a good forcing function: if you can't articulate a shared role-level question, the match is probably wrong — but if you can, the match holds even when the two sections answer that question in very different ways. |

Save as `p1-p2-section-mapping.json` (a JSON array of these objects).

### Step 4: Map paper2 → paper1, independently

Repeat Step 3 in the other direction. **Reason through this from scratch — don't just invert Step 3's results.** The two passes are allowed to diverge, and often should: paper2's best match for one of its sections might be a paper1 section that, from paper1's side, was better matched to something else. That asymmetry is expected, not a bug — it's exactly what Step 5 uses to tell confirmed matches apart from one-sided guesses.

Save as `p2-p1-section-mapping.json`, using the same field names and the same `paper1`/`paper2` assignment as Step 3.

### Step 5: Find the bidirectional matches

Run the bundled script rather than eyeballing this — it's a mechanical exact-match comparison on section numbers, and a script won't miss an entry or misremember a number the way re-deriving it by hand can:

```bash
python3 scripts/find_common_and_diffs.py p1-p2-section-mapping.json p2-p1-section-mapping.json
```

This reads both mapping files and writes three output files into the same directory:

- **`common-section-structure.json`** — pairings where both directions independently agree (matched on `paper1_section_number` + `paper2_section_number`). These are the confident, load-bearing structural correspondences.
- **`alignable-section-diffs.json`** — pairings found in only one direction, where both papers still name an actual section. Worth a second look; often a genuine but weaker correspondence, or a case where the "closest" section is ambiguous.
- **`non-alignable-section-diffs.json`** — pairings where one side is `null`. These are real structural differences between the papers (a section that flatly doesn't exist in the other paper), not a disagreement between the two mapping passes.

The script also prints a summary count to the terminal — read it before moving on, since a common-structure count that seems too low or too high (e.g., 0 out of 8, or 8 out of 8 with no diffs at all) is a signal to go back and check Steps 3–4 rather than assuming the script is wrong.

### Step 6: Summarize for the user

Report the counts and, more importantly, what's substantively interesting:

- Which sections have **no counterpart at all** (the `non-alignable-section-diffs.json` entries) — these are real organizational differences between the papers, worth calling out by name.
- Which pairings **almost matched but didn't** (`alignable-section-diffs.json`) — these are often a labeling/scope quibble rather than a real difference, and worth a sentence of interpretation rather than just listing them.
- Don't just dump the JSON at the user — lead with the finding (e.g., "5 of 8 sections have a confirmed structural counterpart; the main differences are that Paper A runs a separate ablation study that Paper B has no equivalent of, and Paper B breaks results into qualitative/quantitative sections that Paper A keeps combined").

## Common mistakes to avoid

- **Combining multi-section correspondences into one label instead of splitting them (Step 3).** This is the single most common way to accidentally suppress a real bidirectional match — the script does exact matching on section numbers, so a combined entry like paper2 = "6 + 7" will never match separate entries for paper2 = "6" and paper2 = "7" in the other direction, even though they're the same underlying claim.
- **Inverting Step 3 to produce Step 4 instead of reasoning independently.** This defeats the entire point of the bidirectional check — every pairing would trivially "match itself," and you'd learn nothing about which correspondences are actually solid.
- **Matching on section name instead of number in the comparison script.** Names can pick up small annotation differences between independent reasoning passes (e.g., one pass appends a subsection reference like "(§3.1 Design Goals)" and the other doesn't) even when both passes are pointing at the same section. The bundled script matches on number, not name, for exactly this reason — don't "fix" this to string-match on names.
- **Defaulting to `null` whenever no top-level section is a good match, without checking subsections first.** This is an easy trap because Step 1 tells you to extract *top-level* section titles, which can make it feel like only top-level sections are valid answers. They're not — a subsection can be exactly the right "closest analog" for a weak match, and using one there is very different from a genuine `null` (no counterpart of any kind, at any level). Over-using `null` quietly turns real (if imperfect) structural correspondences into "these papers have nothing in common here" — check subsections before you give up.
- **Rejecting a match because the content or methodology differs, when the role is actually the same.** This is subtler than it sounds and easy to talk yourself into, because it feels rigorous: "paper1's section reports real interview data and paper2's doesn't, so they're not really the same thing." But the question is never "do these sections contain the same kind of evidence" — it's "do these sections do the same job in their paper's argument." A section that formally derives its design goals from stated rationale, and a section that derives the same design goals from interviews, are both "the section that justifies the design" — that's the correspondence. If you find yourself rejecting a candidate match because it "doesn't clear the bar" of methodological rigor or topical overlap rather than because it plays a different role in the paper, that's a sign you're using the wrong criterion — go back and check whether the role actually lines up before writing `null`.
