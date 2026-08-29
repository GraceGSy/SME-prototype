---
name: "extract-section-and-subsection-paragraphs"
description: "Extracts section, subsection, and paragraph content from either an academic PDF with an existing section manifest or source-marked narrative XHTML. In narrative mode, Claude extracts the text while using only explicit headings and horizontal-rule separators as scene boundaries. Produces the same strict nested JSON schema for both domains."
---

# Extract Section and Subsection Paragraphs

## What this is (and isn't)

This is the subsection-aware sibling of `extract-section-paragraphs`. That skill splits each top-level section's text into one flat `paragraphs` array. This skill does the same job, but when a top-level section has subsections (per its input's own `subsections` array), it splits that section's text into: the section's own **lead-in** paragraphs (whatever comes before the first subsection's heading) in the top-level entry's own `paragraphs` field, and each **subsection's own** paragraphs nested inside that subsection's own object. A top-level section with no subsections (`subsections: []`) is handled exactly like `extract-section-paragraphs` — its whole text becomes its own flat `paragraphs` array, no lead-in/subsection distinction to make.

It reuses `extract-section-paragraphs`'s own text-extraction and paragraph-splitting machinery wholesale — the `pdftotext -layout`/plain-mode extraction, the line-position and running-header/footer detection, the three paragraph-break signals (blank line, indent, vertical gap), the caption/chart-label exclusion rules, the list-stays-one-paragraph rule. **Consult that skill's SKILL.md directly for the exact mechanics of all of that** — this skill's own Steps 1, 2, and 4 below just point back to it rather than re-deriving it, same pattern `extract-top-and-second-level-section-names` uses relative to `extract-top-level-section-names`. The one genuinely new piece of work this skill adds is Step 3 (locating subsection boundaries within a section) and Step 5 (the order-integrity check).

**This does not judge subsection boundaries itself** — it takes the `subsections` array (names and numbers) as given input from `extract-top-and-second-level-section-names`, and only has to find *where in the body text* each already-identified subsection heading actually starts. If the user hasn't already run that skill (or its appendix-excluding sibling) on this PDF, run it first.

## Inputs

Choose exactly one mode:

1. **Academic mode:** the existing nested section manifest and source PDF described below.
2. **Narrative mode:** one XHTML source document whose real divisions are encoded as `h3` headings and/or `hr` separators.

## Narrative mode: explicit boundaries only

Use this mode for fiction or other narrative documents. Claude performs the extraction from the supplied XHTML, subject to these source-grounded boundary rules:

- An explicit `h3` division becomes a top-level section.
- If no `h3` divisions exist, the complete story becomes one top-level section named from its `h2` title.
- An `hr` inside a top-level section divides that section into source-backed scenes. `n` separators create `n + 1` scenes.
- Scene names are metadata assigned in document order: `Scene 1`, `Scene 2`, and so on. Numbering continues across titled divisions.
- If a section has at least one separator, all its prose belongs to its scene subsections and its top-level `paragraphs` array is empty.
- If a section has no separator, it has no synthetic subsections and retains its complete prose in `paragraphs`.
- Read and extract the narrative prose from the XHTML itself. Preserve wording and paragraph order; normalize only markup and whitespace needed to produce plain paragraph text.
- Exclude document chrome and non-narrative metadata such as navigation, the story heading itself, and colophon material.
- Never infer a boundary from changes in time, location, speaker, point of view, topic, or plot. Whitespace alone is not a scene separator.
- A leading, trailing, or consecutive separator is an input-integrity error. Do not fabricate an empty scene.
- If there is no explicit `hr` separator anywhere in the story, stop rather than inventing scenes.
- Save the extracted content directly in the strict JSON schema below. Report its section, scene, and paragraph counts.

## Academic-mode inputs

1. A `sections-with-subsections.json` (or `sections-with-subsections-excluding-appendices.json`) file: a JSON array of nested section objects (`section_name`, `section_number`, `subsections: [{section_name, section_number}]`), in the order sections appear in the paper — the output of `extract-top-and-second-level-section-names` or `extract-top-and-second-level-section-names-excluding-appendices`.
2. The PDF path those sections were extracted from.

## Workflow

### Step 1: Extract full text, line-position data, and running headers/footers

Identical to `extract-section-paragraphs`'s own Step 1 — run it exactly as documented there (the `pdftotext -layout` vs. plain fallback, the unconditional line-position extraction via `pdfplumber` or equivalent, the corpus-wide running-header/footer detection, the column-merge sanity check). Don't re-derive or approximate this from memory; read that skill's current SKILL.md if any detail is unclear.

### Step 2: Locate each top-level section's boundaries

Identical to `extract-section-paragraphs`'s own Step 2: for each top-level entry, in order, find where its header actually appears in the body text, and treat its content as running until the start of the *next top-level entry* — including all of its own subsections along the way. The last top-level entry's content runs to its natural extent.

### Step 3: Within each top-level section, locate subsection boundaries and split into spans

This is the new work this skill adds. For a top-level entry with `subsections: []`, skip this step entirely — its whole Step 2 span is treated as one undivided span, handled in Step 4 exactly as `extract-section-paragraphs` would.

For a top-level entry with a non-empty `subsections` array: within that section's own Step 2 span, locate where each subsection's header actually appears in the body text — not a citation to it, not a running header/footer, not a cross-reference — using the same anti-grep-alone discipline `extract-top-and-second-level-section-names` used to find it in the first place (a subsection header can be split across lines, have its number dropped, or merge with the following paragraph's first line — cross-check rather than trusting one pass). Do this for every subsection in the array, in order.

This partitions the top-level section's span into:

- **The lead-in span**: everything between the top-level section's own header and the *first* subsection's header. This can be empty (many sections launch straight into their first subsection with no lead-in prose at all) — that's normal, not an error.
- **Each subsection's own span**: everything between that subsection's header and the *next* subsection's header (or, for the *last* subsection in the array, everything up to the end of the top-level section's own Step 2 boundary).

**By construction, the last subsection's span always extends all the way to the top-level section's own end boundary.** This is deliberate — see Step 5 below for why this matters and what to do if the actual body text doesn't cooperate with that assumption (i.e. there's real content after what looks like the last subsection's natural end, but before the next top-level section starts).

### Step 4: Split each span into paragraphs

For the lead-in span (if any) and for each subsection's own span, apply `extract-section-paragraphs`'s own Step 3 exactly — the three paragraph-break signals (blank line, first-line indent, vertical gap) all checked unconditionally, line-wrap rejoining, running-header/footer stripping, caption/chart-label/footnote exclusion, the list-stays-one-paragraph rule. Treat each span as its own independent mini-section for this purpose — `paragraph_number` restarts at `0` within each span (the lead-in's own paragraphs, and each subsection's own paragraphs, all number from `0` independently — see Output schema).

A lead-in span with no real prose (a section that launches straight into its first subsection) produces an empty `paragraphs` array (`[]`), not a fabricated placeholder.

### Step 5: Order-integrity check — flag before finalizing, don't silently place

**This is the step that exists specifically because this skill's nested schema has exactly one place order can get silently misrepresented, and this skill must never let that happen invisibly.**

The schema (see Output below) puts a top-level section's own `paragraphs` field *before* its `subsections` array, and every consumer of this schema will reasonably read that field as "the section's lead-in, before its subsections" — which is exactly what Step 3 constructs it to be, *as long as* the last subsection's span really does reach all the way to the top-level section's own end boundary, with nothing real left over.

For every top-level entry with a non-empty `subsections` array, explicitly verify this: after determining the last subsection's own span in Step 3, confirm there is no real body content between the end of that span and the top-level section's own Step 2 end boundary (the start of the next top-level section, or the natural end of the document for the very last section overall).

- **If there is no such leftover content** (the normal, expected case): nothing to flag. The schema's implicit "lead-in first, subsections after, in order" reading is accurate for this entry.
- **If there IS real leftover content** — body prose that comes chronologically *after* every subsection's own content but isn't inside any of them — **do not append it to the top-level `paragraphs` field.** Doing so would silently misrepresent PDF reading order: a reader of the JSON would take that field to mean "before the subsections," when this content actually comes after all of them. There is no field in this skill's schema that can hold "trailing, post-subsections, section-level content" without either misrepresenting order (if forced into `paragraphs`) or misattributing it to a subsection it doesn't actually belong to (if force-appended to the last subsection's own `paragraphs`). **This is a genuine judgment call, not a mechanical one — stop and flag it explicitly to the user** (quote the leftover text, or its first ~15 words, and name the section) rather than silently picking one of those two imperfect placements. Report how many such cases were found, if any, prominently in your summary — don't bury it in the JSON or let it pass unmentioned.

**Also re-flag the existing column-scrambling risk from `extract-section-paragraphs`'s own Step 1, specifically where it touches a subsection boundary.** That skill already warns that `-layout` mode's automatic column merge can silently reorder text within a section on some two-column templates. Here, if that scrambling risk appears anywhere near a subsection boundary you identified in Step 3 (not just within a single paragraph), it's a more serious version of the same problem — it could misattribute whole paragraphs to the wrong subsection, not just merge two paragraphs' text together. If you had to fall back to per-column word-position extraction (as that skill already instructs) anywhere near a subsection boundary, say so explicitly in your summary as an order-integrity flag, not just as a routine extraction note.

If you're genuinely unsure whether something found in this step counts as real leftover content or is just an artifact of your own boundary-finding, treat it as real and flag it — the cost of a false-positive flag is a quick confirmation from the user; the cost of a false negative is a silent, undetectable order misrepresentation sitting in the output JSON.

### Step 6: Build the output

For each top-level entry, preserve `section_name` and `section_number` unchanged, and build:

- `paragraphs`: the lead-in span's paragraphs (Step 4) if `subsections` is non-empty, or the section's *entire* paragraph list if `subsections` is empty (same as `extract-section-paragraphs`'s own output in that case).
- `subsections`: for each subsection object, preserve `section_name`/`section_number` unchanged and add its own `paragraphs` array from Step 4.

## Output

Save as a JSON array, named `sections-with-subsections-and-paragraph-content.json` if the input was `sections-with-subsections.json`, or `sections-with-subsections-and-paragraph-content-excluding-appendices.json` if the input was `sections-with-subsections-excluding-appendices.json` — same directory as the input unless the user specifies otherwise. Don't overwrite either input file.

Briefly tell the user: how many top-level sections were processed, how many had subsections vs. none, total paragraph count (lead-in + all subsections + flat sections combined), and — prominently, not buried — the results of the Step 5 order-integrity check: how many sections (if any) had real leftover content after their last subsection that needed flagging rather than silent placement, and how many (if any) had a subsection-boundary column-scrambling risk. If zero such cases were found, say so explicitly too, so the user knows the check ran rather than was skipped.

### Output schema (strict)

ALWAYS use this exact shape for every top-level entry:

```json
{
  "section_name": "string, unchanged from the input",
  "section_number": "string or null, unchanged from the input",
  "paragraphs": [
    {"paragraph_number": 0, "text": "string"}
  ],
  "subsections": [
    {
      "section_name": "string, unchanged from the input",
      "section_number": "string or null, unchanged from the input",
      "paragraphs": [
        {"paragraph_number": 0, "text": "string"}
      ]
    }
  ]
}
```

**`paragraphs` on a top-level entry means two different things depending on whether `subsections` is empty — document this plainly to the user, don't let it be a silent gotcha:** if `subsections` is `[]`, `paragraphs` is the section's *entire* paragraph content (same meaning as `extract-section-paragraphs`'s output). If `subsections` is non-empty, `paragraphs` is *only* the lead-in content before the first subsection — `[]` if there is none. This dual meaning is exactly why Step 5's order-integrity check exists: it's only safe to read a non-empty-subsections entry's `paragraphs` field as "comes before everything in `subsections`" once Step 5 has confirmed there's no leftover content after the last subsection.

`paragraph_number` is always an integer, `0`-indexed, and resets to `0` independently within the lead-in `paragraphs` array and within *each* subsection's own `paragraphs` array — never a running count across the whole top-level section. `paragraphs` is `[]` (never `null`, never omitted) wherever there's genuinely no prose — an empty lead-in, a content-less subsection, or a References-type section with no real body text.

Full example:

```json
[
  {
    "section_name": "Abstract",
    "section_number": null,
    "paragraphs": [{"paragraph_number": 0, "text": "This paper presents..."}],
    "subsections": []
  },
  {
    "section_name": "General Methods",
    "section_number": "4",
    "paragraphs": [
      {"paragraph_number": 0, "text": "We conducted two studies to investigate..."}
    ],
    "subsections": [
      {
        "section_name": "Stimuli",
        "section_number": null,
        "paragraphs": [{"paragraph_number": 0, "text": "Stimuli were drawn from..."}]
      },
      {
        "section_name": "Procedure",
        "section_number": null,
        "paragraphs": [
          {"paragraph_number": 0, "text": "Participants first completed..."},
          {"paragraph_number": 1, "text": "After the main task, participants..."}
        ]
      }
    ]
  }
]
```

Don't add extra fields anywhere in this structure — no `page_number`, no `word_count`, no `is_lead_in` flag, no order-integrity-warning field embedded in the JSON itself (that belongs in your response text to the user, per Step 5, not in the data).

## Common mistakes to avoid

- **Appending trailing, post-last-subsection content to the top-level `paragraphs` field.** This is the single most important mistake this skill exists to prevent — it silently misrepresents PDF reading order, since that field is read as "comes before the subsections." Flag it per Step 5 instead of placing it anywhere.
- **Silently appending trailing content to the last subsection's own `paragraphs` instead** as a "safer" default. It's not safer — that content may not actually belong to that subsection's own role either. This is a genuine judgment call; ask, don't guess.
- **Treating a section's lead-in-before-first-subsection assumption as automatically true without running Step 5's check.** The schema's ordering convention is only accurate once verified per section, not by default.
- **Skipping Step 5 entirely because "it usually doesn't happen."** It's a mandatory check on every section with subsections, the same "unconditional, every time" discipline `extract-section-paragraphs`'s own three paragraph-break signals and `extract-top-and-second-level-section-names`'s own 3a/3b subsection checks already use — not a conditional fallback for when something looks suspicious.
- **Re-deriving the paragraph-splitting mechanics (the three signals, caption exclusion, list handling) from memory instead of running `extract-section-paragraphs`'s own current Step 3.** Read that skill's SKILL.md directly if any detail is unclear.
- **Treating a section with `subsections: []` as needing lead-in/subsection splitting logic at all.** It doesn't — handle it exactly like `extract-section-paragraphs` would, its whole content in one flat `paragraphs` array.
- **Restarting `paragraph_number` from a running count across the whole top-level section, instead of resetting to `0` independently for the lead-in and for each subsection.**
- **Judging subsection boundaries from scratch instead of taking the `subsections` array as given input.** This skill locates *where in the body text* an already-identified subsection starts — it doesn't decide *whether* something is a subsection at all; that's `extract-top-and-second-level-section-names`'s job.
- **Missing a subsection-boundary column-scrambling risk because it "only" affects paragraph attribution and doesn't look like a within-paragraph merge issue.** Flag it as an order-integrity concern per Step 5, not just as a routine Step 1 extraction note.
- **Overwriting the input `sections-with-subsections(...).json` file, or using the same filename for both the with-appendices and without-appendices variants of this skill's own output.**
- **Adding extra fields to the strict schema**, including any kind of embedded warning/flag field — order-integrity findings belong in your response text, not the JSON.

