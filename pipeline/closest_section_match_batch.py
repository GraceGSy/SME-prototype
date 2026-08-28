#!/usr/bin/env python3
"""
closest_section_match_batch.py

Calls the Claude API to run the "closest-section-match-nested" skill in a loop
over every section AND subsection defined in paper1's nested JSON file,
finding each one's single closest-matching section or subsection in paper2.

This is a standalone re-implementation of that skill's workflow as an
automated script (rather than an agent reasoning through it manually):

  Step 1 (candidate construction) -- identical for both papers: every
  top-level entry contributes one "whole section" candidate (its own lead-in
  paragraphs plus every subsection's paragraphs, concatenated, using the
  entry's own question_this_text_answers) and, if it has subsections, one
  candidate per subsection (that subsection's own paragraphs alone, using its
  own question). Paper1's full candidate list is what this script loops over;
  paper2's full candidate list is the fixed pool every query is matched
  against.

  Step 2/3/4 (evidence + matching + single-match selection) -- for each
  paper1 candidate, the script sends the full paper2 candidate pool (names,
  numbers, questions, paragraph text) to Claude in one call, and asks it to
  pick the single closest match (or none) using the same role-based,
  joint-evidence discipline as the family of skills this is built on: judge
  by shared role in the paper's own arc, not shared vocabulary; weigh the
  question as primary evidence, paragraphs overriding only on a genuine
  conflict; never split into more than one match.

  The one deviation from an LLM call: candidates with empty paragraphs AND no
  question are resolved locally via the same exact-name fallback the skill
  describes, without spending an API call.

Usage:
    python3 closest_section_match_batch.py \
        --paper1 "/path/to/paper1-sections-with-subsections-and-paragraph-content-no-appendices.json" \
        --paper2 "/path/to/paper2-sections-with-subsections-and-paragraph-content-no-appendices.json" \
        [--output OUTPUT.json] [--model claude-sonnet-5] [--sleep 0.3]

Requires the anthropic Python package and an ANTHROPIC_API_KEY in the
environment (the Anthropic() client picks it up automatically).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

QUESTION_FIELD = "question_this_text_answers"

MATCH_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "match_index": {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "description": (
                "0-based index into the numbered candidate list of the single "
                "closest-matching paper2 candidate, judged by the role it plays "
                "in its paper -- or null if nothing in paper2 plays the same role."
            ),
        },
        "basis": {
            "type": "string",
            "description": (
                "Why the chosen candidate corresponds (or why nothing does), "
                "grounded in what the paragraphs and question_this_text_answers "
                "fields actually say. Never empty."
            ),
        },
    },
    "required": ["match_index", "basis"],
}

SYSTEM_PROMPT = """You are performing one step of the "closest-section-match-nested" skill: \
given ONE query section or subsection from paper1 (its paragraphs and its own \
question_this_text_answers), and the full set of candidate sections/subsections \
from paper2 (their paragraphs and their own questions_this_text_answers),\ 
find the SINGLE closest-matching paper2 candidate, or determine that none corresponds.

Judge correspondence by ROLE -- are the query and a candidate doing the same job \
in their respective documents, not whether they share vocabulary or topic.\ 
Read every paragraph on both sides in full before deciding.\
Weigh the question_this_text_answers field as reliable, primary \
evidence of role -- not a hint the paragraphs merely confirm -- and let the \
paragraphs override it only on a genuine conflict (watch for a question that names \
every sub-topic but still excludes some kind of content actually present in the \
paragraphs -- a "type-narrow" question).

A whole-section query matching a paper2 subsection, or a subsection query matching \
a paper2 whole section, is a completely normal and expected outcome -- do not \
prefer same-level matches over cross-level ones.

Report exactly ONE match. If the query's content genuinely touches more than one \
role in paper2, pick whichever candidate most centrally represents the query's \
content, and mention the secondary correspondence as a brief aside inside `basis` \
rather than picking a different candidate or refusing to choose.

If nothing in paper2 plays the same role as the query, the honest answer is no \
match (`match_index: null`) -- this is common and expected, especially for a \
narrow subsection query. Do not force the least-bad candidate.

Never leave `basis` empty, even when there is no match -- explain why nothing \
corresponds.

Respond only by calling the record_match tool."""


def load_paper(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def paragraph_texts(paragraphs: list[dict[str, Any]] | None) -> list[str]:
    if not paragraphs:
        return []
    return [p.get("text", "") for p in paragraphs]


def build_candidates(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the full whole-section + subsection candidate list for one paper,
    identical to Step 1 of directional-section-mapping-by-paragraphs-nested."""
    candidates: list[dict[str, Any]] = []
    for entry in entries:
        section_name = entry.get("section_name")
        section_number = entry.get("section_number")
        subsections = entry.get("subsections") or []

        whole_paragraphs = paragraph_texts(entry.get("paragraphs"))
        for sub in subsections:
            whole_paragraphs = whole_paragraphs + paragraph_texts(sub.get("paragraphs"))

        candidates.append(
            {
                "level": "whole",
                "section_name": section_name,
                "section_number": section_number,
                "subsection_name": None,
                "subsection_number": None,
                "paragraphs": whole_paragraphs,
                "question": entry.get(QUESTION_FIELD),
            }
        )

        for sub in subsections:
            candidates.append(
                {
                    "level": "subsection",
                    "section_name": section_name,
                    "section_number": section_number,
                    "subsection_name": sub.get("section_name"),
                    "subsection_number": sub.get("section_number"),
                    "paragraphs": paragraph_texts(sub.get("paragraphs")),
                    "question": sub.get(QUESTION_FIELD),
                }
            )
    return candidates


def check_questions_present(entries: list[dict[str, Any]], label: str) -> bool:
    """Step 0 precondition check: does this file show real signs of having
    been through question annotation? Samples top-level and subsection
    entries with real paragraph content."""
    checked = 0
    with_question = 0
    for entry in entries:
        if entry.get("paragraphs"):
            checked += 1
            if entry.get(QUESTION_FIELD):
                with_question += 1
        for sub in entry.get("subsections") or []:
            if sub.get("paragraphs"):
                checked += 1
                if sub.get(QUESTION_FIELD):
                    with_question += 1
    if checked == 0:
        print(f"[{label}] No entries with real paragraph content found -- cannot verify questions.")
        return False
    ratio = with_question / checked
    print(f"[{label}] {with_question}/{checked} content-bearing entries have {QUESTION_FIELD} (ratio {ratio:.2f}).")
    if ratio == 0:
        print(f"[{label}] REFUSING TO RUN: no sign of question annotation on this file.")
        return False
    return True


def candidate_label(c: dict[str, Any]) -> str:
    if c["level"] == "whole":
        return c["section_name"] or "(unnamed section)"
    return f'{c["section_name"]} > {c["subsection_name"]}'


def is_content_empty(c: dict[str, Any]) -> bool:
    return not c["paragraphs"] and not c["question"]


def exact_name_key(c: dict[str, Any]) -> str:
    name = c["subsection_name"] if c["level"] == "subsection" else c["section_name"]
    return (name or "").strip().lower()


def format_paper2_context(paper2_candidates: list[dict[str, Any]]) -> str:
    blocks = []
    for i, c in enumerate(paper2_candidates):
        para_text = "\n".join(f"    - {t}" for t in c["paragraphs"]) if c["paragraphs"] else "    (no paragraphs)"
        blocks.append(
            f"[{i}] level={c['level']} section_name={c['section_name']!r} "
            f"section_number={c['section_number']!r} subsection_name={c['subsection_name']!r} "
            f"subsection_number={c['subsection_number']!r}\n"
            f"  question_this_text_answers: {c['question']!r}\n"
            f"  paragraphs:\n{para_text}"
        )
    return "\n\n".join(blocks)


def format_query(q: dict[str, Any]) -> str:
    para_text = "\n".join(f"  - {t}" for t in q["paragraphs"]) if q["paragraphs"] else "  (no paragraphs)"
    return (
        f"QUERY (paper1) level={q['level']} section_name={q['section_name']!r} "
        f"section_number={q['section_number']!r} subsection_name={q['subsection_name']!r} "
        f"subsection_number={q['subsection_number']!r}\n"
        f"question_this_text_answers: {q['question']!r}\n"
        f"paragraphs:\n{para_text}"
    )


def call_claude_for_match(
    client: Any,
    model: str,
    query: dict[str, Any],
    paper2_context: str,
    max_retries: int = 3,
) -> tuple[int | None, str]:
    user_message = (
        f"{format_query(query)}\n\n"
        f"PAPER2 CANDIDATES (numbered, 0-based):\n\n{paper2_context}\n\n"
        "Which single paper2 candidate (by index) is the closest match to the query, "
        "judged by role? If none corresponds, use match_index: null."
    )

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                tools=[
                    {
                        "name": "record_match",
                        "description": "Record the single closest match (or null) for this query.",
                        "input_schema": MATCH_TOOL_SCHEMA,
                    }
                ],
                tool_choice={"type": "tool", "name": "record_match"},
            )
            tool_blocks = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
            if len(tool_blocks) != 1:
                raise RuntimeError(f"Expected exactly one tool_use block, got {len(tool_blocks)}")
            result = dict(tool_blocks[0].input)
            match_index = result.get("match_index")
            basis = result.get("basis") or ""
            if not basis.strip():
                raise RuntimeError("Model returned an empty basis")
            return match_index, basis
        except Exception as exc:  # noqa: BLE001 -- deliberately broad, retried below
            last_error = exc
            wait = 2**attempt
            print(f"    API call failed (attempt {attempt}/{max_retries}): {exc}. Retrying in {wait}s...")
            time.sleep(wait)

    return None, f"API call failed after {max_retries} attempts: {last_error}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper1", required=True, help="Path to paper1's nested sections JSON (queries loop over this file)")
    parser.add_argument("--paper2", required=True, help="Path to paper2's nested sections JSON (candidate pool searched)")
    parser.add_argument("--output", default=None, help="Output JSON path (default: alongside paper1, auto-named)")
    parser.add_argument("--model", default="claude-sonnet-5", help="Anthropic model string (default: claude-sonnet-5)")
    parser.add_argument("--sleep", type=float, default=0.3, help="Seconds to sleep between API calls")
    args = parser.parse_args()

    paper1_path = Path(args.paper1)
    paper2_path = Path(args.paper2)
    paper1_name = paper1_path.name.split("-sections-with-subsections")[0]
    paper2_name = paper2_path.name.split("-sections-with-subsections")[0]

    output_path = Path(args.output) if args.output else paper1_path.parent / f"{paper1_name}-{paper2_name}-closest-section-match-batch.json"

    print(f"Loading paper1: {paper1_path}")
    paper1_entries = load_paper(str(paper1_path))
    print(f"Loading paper2: {paper2_path}")
    paper2_entries = load_paper(str(paper2_path))

    # Step 0: precondition check on both files
    ok1 = check_questions_present(paper1_entries, paper1_name)
    ok2 = check_questions_present(paper2_entries, paper2_name)
    if not (ok1 and ok2):
        print("\nStopping: one or both files do not show signs of question annotation. "
              "Add question_this_text_answers before running this script.")
        sys.exit(1)

    # Step 1: build candidate lists
    paper1_queries = build_candidates(paper1_entries)
    paper2_candidates = build_candidates(paper2_entries)
    print(f"\nBuilt {len(paper1_queries)} paper1 query candidates "
          f"({sum(1 for c in paper1_queries if c['level'] == 'whole')} whole, "
          f"{sum(1 for c in paper1_queries if c['level'] == 'subsection')} subsection).")
    print(f"Built {len(paper2_candidates)} paper2 candidates "
          f"({sum(1 for c in paper2_candidates if c['level'] == 'whole')} whole, "
          f"{sum(1 for c in paper2_candidates if c['level'] == 'subsection')} subsection).")

    try:
        from anthropic import Anthropic
    except ImportError:
        print("\nThe 'anthropic' package is not installed. Run: pip install anthropic")
        sys.exit(1)

    client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    paper2_context = format_paper2_context(paper2_candidates)

    # Pre-index paper2 candidates that are content-empty, for the exact-name fallback
    empty_paper2_by_name = {
        exact_name_key(c): i for i, c in enumerate(paper2_candidates) if is_content_empty(c)
    }

    rows = []
    n_api_calls = 0
    n_fallback = 0
    n_matched = 0
    n_null = 0

    for i, query in enumerate(paper1_queries, 1):
        label = candidate_label(query)
        print(f"[{i}/{len(paper1_queries)}] {label} ...", end=" ", flush=True)

        match_index: int | None
        basis: str

        if is_content_empty(query):
            key = exact_name_key(query)
            if key in empty_paper2_by_name:
                match_index = empty_paper2_by_name[key]
                basis = (
                    "Both are empty placeholder entries with no body paragraphs and no "
                    "question -- matched via the exact-name fallback for content-empty candidates."
                )
                n_fallback += 1
                print(f"exact-name fallback -> {candidate_label(paper2_candidates[match_index])}")
            else:
                match_index = None
                basis = "No paragraphs and no question, and no equally-empty paper2 candidate has an exactly matching name."
                n_fallback += 1
                print("exact-name fallback -> no match")
        else:
            match_index, basis = call_claude_for_match(client, args.model, query, paper2_context)
            n_api_calls += 1
            if match_index is not None and 0 <= match_index < len(paper2_candidates):
                print(f"-> {candidate_label(paper2_candidates[match_index])}")
            else:
                print("-> no match")
            time.sleep(args.sleep)

        if match_index is not None and 0 <= match_index < len(paper2_candidates):
            match = paper2_candidates[match_index]
            n_matched += 1
            row = {
                "paper1_section_name": query["section_name"],
                "paper1_section_number": query["section_number"],
                "paper1_subsection_name": query["subsection_name"],
                "paper1_subsection_number": query["subsection_number"],
                "paper2_section_name": match["section_name"],
                "paper2_section_number": match["section_number"],
                "paper2_subsection_name": match["subsection_name"],
                "paper2_subsection_number": match["subsection_number"],
                "basis": basis,
            }
        else:
            n_null += 1
            row = {
                "paper1_section_name": query["section_name"],
                "paper1_section_number": query["section_number"],
                "paper1_subsection_name": query["subsection_name"],
                "paper1_subsection_number": query["subsection_number"],
                "paper2_section_name": None,
                "paper2_section_number": None,
                "paper2_subsection_name": None,
                "paper2_subsection_number": None,
                "basis": basis,
            }
        rows.append(row)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\nDone. {len(rows)} rows written to {output_path}")
    print(f"  API calls made: {n_api_calls}")
    print(f"  Resolved via exact-name fallback (no API call): {n_fallback}")
    print(f"  Real matches: {n_matched}")
    print(f"  No match: {n_null}")


if __name__ == "__main__":
    main()
