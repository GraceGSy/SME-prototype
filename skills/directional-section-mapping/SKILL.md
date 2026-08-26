---
name: directional-section-mapping
description: Given two paper PDFs, maps every top-level section of "paper1" onto its closest section in "paper2" — a single-direction pass, not a bidirectional comparison. Outputs JSON with paper1/paper2 section names/numbers, the basis for each correspondence, and a shared question each pairing answers. Use for a one-way section correspondence between two papers, "what in paper B corresponds to each section of paper A," or an explicit directional mapping request. Trigger for "map each section of paper A onto its closest match in paper B," "for every section here, find the equivalent in that other paper," or when the user names one paper first and wants correspondence anchored from its point of view. For matches confirmed from both directions, or sections with no counterpart anywhere, use "paper-section-alignment" instead — this is the single-direction building block, meant to be invoked twice (once per direction) for that.
---

# Directional Section Mapping

## What this is (and isn't)

This is a **single-direction** pass: for every top-level section in `paper1`, find its closest corresponding section in `paper2`. It does not check whether `paper2`'s side of that pairing agrees when reasoned about independently — that's a separate, bidirectional skill (`paper-section-alignment`). This skill is the deliberate building block for someone who wants to run each direction as its own step, look at the result, and decide what to do next (including whether to run this skill again in the reverse direction) rather than getting an automatic all-in-one bidirectional report.

If the user wants both directions, run this skill twice: once with the papers as given, once with `paper1`/`paper2` swapped. Use different output filenames for each pass (see "Output" below) so the second run doesn't overwrite the first.

## Inputs

Two PDF paths. The order matters: whichever the user gives first (or explicitly designates) is `paper1`; the correspondence is found *from* paper1's sections *to* paper2's sections, not the other way around. If it's ambiguous which paper should anchor the mapping, ask.

## Workflow

### Step 1: Extract paper1's top-level section titles

Use `pdftotext` (try `-layout` first; fall back to plain `pdftotext` if the paper's two-column layout garbles headers or interleaves them with running headers/footers — plain mode usually preserves reading order better for column text even though it loses spatial layout). Look for numbered top-level headers (e.g., "1 Introduction," or IEEE-style "I. Introduction" — don't assume Arabic numerals, some fields use Roman numerals or lettered sections). Cross-check against the paper's page count and skim for anything the grep missed; subsections (e.g., "2.1") don't count as top-level.

### Step 2: Read both papers' content, not just paper1's

You need paper2's full content too, obviously — but also re-read paper1's section content, not just its titles, before judging correspondence. Titles alone are unreliable ("Results," "Discussion," and "Evaluation" mean different things paper to paper).

**What you're reading for is each section's role in its paper's argument, not its topic or methodology.** Ask "what job is this section doing — what question is it there to answer, and where does it sit in the arc from problem to contribution to evidence to reflection?" Two sections correspond if they play the same role, even if they fill that role with completely different kinds of content or evidence. For example, a section reporting empirical interviews that shaped a design, and another paper's subsection merely asserting design rationale with no fieldwork behind it, are a real correspondence — both are "the section that justifies the design," occupying the same position in the paper's arc. That difference in *how* each paper fills the role belongs in `basis` as an observation, not as a reason to reject the match. Don't reject a candidate match because the content, rigor, or evidence type differs — only reject it because the two sections are doing genuinely different jobs.

### Step 3: Map each paper1 section to its closest paper2 counterpart

For each top-level section in `paper1`:

- **If it legitimately corresponds to multiple sections in paper2** (e.g., paper1's single "Results" section covers what paper2 splits into "Qualitative Results" and "Quantitative Results"), create a **separate entry for each** correspondence. Do not combine them into one entry with a joined label like "Qualitative Results + Quantitative Results" — if this output is ever compared against a mapping from the other direction (e.g., by the `paper-section-alignment` skill), a combined label will silently fail to match separate entries that are actually saying the same thing.
- **The closest match is allowed to be a subsection, not just a top-level section.** If nothing in paper2's top-level sections plays paper1's role, check paper2's subsections before giving up — a subsection can be exactly the right analog. Name it with its subsection reference (e.g., `"CorpusStudio (§3.1 Design Goals)"` with `paper2_section_number: "3"`).
- **Use `null` only when nothing — not even a subsection — plays that role anywhere in paper2.** `null` means "this job isn't done anywhere in the other paper," not "this job is done differently, with less rigor, or with different evidence in the other paper." If you can point to any passage clearly trying to answer the same underlying question, name it rather than defaulting to null.

Each entry needs these fields:

| Field | Description |
|---|---|
| `paper1_section_name` | Section name/title from paper1 |
| `paper1_section_number` | Section number from paper1 (as a string, e.g. `"3"`) |
| `paper2_section_name` | Closest corresponding section name in paper2, or `null` |
| `paper2_section_number` | Corresponding section number in paper2, or `null` |
| `basis` | Why these sections correspond — cite the shared role and, where relevant, how each paper fills it differently. If weak or null, say why. |
| `question_the_sections_both_answer` | One question both sections are fundamentally trying to answer, framed around role (e.g. "what motivated this design?"), not shared subject matter. If you can't articulate one, the match is probably wrong. |

### Output

Save as a JSON array of these objects. Default filename: `p1-p2-section-mapping-with-questions.json`. If the user is running this a second time in the reverse direction (paper2 as the new paper1), use a distinct name like `p2-p1-section-mapping-with-questions.json` so it doesn't overwrite the first pass — ask if unclear which pass this is.

Don't just hand back the raw JSON with no comment — briefly tell the user how many sections got a confirmed match, a weak/subsection match, or `null`, and flag anything that stands out (e.g., "three of paper1's eight sections have no counterpart at all in paper2, all clustered around the evaluation methodology").

## Common mistakes to avoid

- **Combining multi-section correspondences into one label instead of splitting them.** The single most common way to silently break downstream bidirectional comparisons — always split, per Step 3.
- **Rejecting a match because the content or methodology differs, when the role is the same.** Easy to talk yourself into because it feels rigorous ("this section has real data and that one doesn't, so they're not the same"). The test is whether the two sections do the same job in their paper's argument, not whether they use the same kind of evidence to do it.
- **Defaulting to `null` without checking subsections first.** Step 1 has you extract top-level titles, which can make it feel like only top-level sections are valid answers — they're not. Check subsections before writing `null`.
- **Treating this skill as if it already does the bidirectional check.** It doesn't, on purpose. If the user actually wants confirmed/bidirectional matches or wants to know what has *no* counterpart at all (as opposed to an unconfirmed one-directional guess), point them to the `paper-section-alignment` skill, or run this skill twice (both directions) and let them compare the two files themselves.
