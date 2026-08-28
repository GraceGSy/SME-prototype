#!/usr/bin/env python3
"""
closest_paragraph_match_within_section.py

The paragraph-level, single-section-pair analog of closest_section_match_batch.py.

closest_section_match_batch.py loops over EVERY section/subsection candidate in
paper1, searching the FULL candidate pool of paper2's sections/subsections, to
find each one's single closest match anywhere in paper2. This script narrows
both sides down first: given one already-identified section (or subsection) of
paper1 and one already-identified section (or subsection) of paper2, it loops
over every PARAGRAPH in paper1's chosen section, searching only the paragraphs
belonging to paper2's chosen section, to find each paragraph's single closest
match within that specific candidate pool.

It is the drill-down step for a section pairing that already looks right at
the section level (confirmed, or a promising alignable-diff) where you want to
know which specific paragraphs on each side actually correspond to each other
-- e.g. after `closest_section_match_batch.py` or the paper-section-alignment
skill family has told you "corpusstudio's 'Implementation Details' (3.4) is
the closest match to examplore_chi18's whole SYSTEM ARCHITECTURE AND
IMPLEMENTATION section," this script answers the finer question of which of
3.4's paragraphs land on which of SYSTEM ARCHITECTURE AND IMPLEMENTATION's
paragraphs.

The API call itself is THE SAME MAPPING QUERY as closest_section_match_batch.py
-- same tool-calling shape (a single `record_match` call returning a
0-based `match_index` or `null`, plus a non-empty `basis`), same prompt-caching
+ pre-warm + concurrent-thread-pool dispatch pattern, same role-based ("what
is this paragraph doing," not "does it share vocabulary") judging standard,
same "null is a common and expected answer, don't force the least-bad
candidate" discipline, and -- corrected from an earlier draft of this script,
which wrongly assumed paragraphs carry no question field of their own --
the SAME joint, co-equal question+text evidence standard used throughout this
skill family. Individual paragraphs in this corpus's nested JSON files DO
carry their own `question_this_text_answers` field (composed per-paragraph,
not just per-section/subsection), so each query and each candidate paragraph
is compared using both its own question field AND its own text together, with
the question weighed as reliable, primary evidence of what the paragraph is
doing and the text overriding it only on a genuine conflict -- not text alone.
The only things that actually change relative to the parent script are the
granularity of what's being compared (paragraphs, not sections/subsections)
and the fact that paper2's candidate pool is pre-scoped to one section/
subsection instead of the whole paper.

Both paragraph pools are expected to come from sections/subsections that
already correspond (or are suspected to) at the section level -- this script
does no section-level judgment of its own, and a paper1/paper2 section pair
you pass in is trusted as given, not re-verified.

"A section" vs "a subsection": if only --paper1-section is given (no
--paper1-subsection), the paragraph pool is that section's OWN paragraphs
PLUS every one of its subsections' paragraphs, concatenated -- the same
"whole section" definition closest_section_match_batch.py's build_candidates()
uses for its whole-level candidates. If --paper1-subsection is also given,
the pool narrows to just that one subsection's own paragraphs. Same rule
applies to --paper2-section/--paper2-subsection independently -- the two
sides don't have to be scoped at the same level (a paper1 whole-section pool
can be matched against a paper2 single-subsection pool, or vice versa).

Usage:
    python3 closest_paragraph_match_within_section.py \
        --paper1 "/path/to/paper1-sections-with-subsections-and-paragraph-content-no-appendices.json" \
        --paper2 "/path/to/paper2-sections-with-subsections-and-paragraph-content-no-appendices.json" \
        --paper1-section "Corpus Studio" --paper1-subsection "Implementation Details" \
        --paper2-section "SYSTEM ARCHITECTURE AND IMPLEMENTATION" \
        [--paper1-section-number 3] [--paper1-subsection-number 3.4] \
        [--paper2-section-number None] [--paper2-subsection "..."] [--paper2-subsection-number "..."] \
        [--output OUTPUT.json] [--model claude-sonnet-5] [--max-workers 5] [--limit N] [--resume]

Requires the anthropic Python package and an ANTHROPIC_API_KEY in the
environment, same as closest_section_match_batch.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

MATCH_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "match_index": {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "description": (
                "0-based index into the numbered candidate paragraph list of the single "
                "closest-matching paper2 paragraph, judged from its question_this_text_answers "
                "and its text together -- or null if nothing in the candidate pool corresponds."
            ),
        },
        "basis": {
            "type": "string",
            "description": (
                "Why the chosen paragraph corresponds (or why nothing does), grounded in "
                "the actual paragraph text AND question_this_text_answers field on both sides. "
                "Never empty."
            ),
        },
    },
    "required": ["match_index", "basis"],
}

TOOLS = [
    {
        "name": "record_match",
        "description": "Record the single closest matching paragraph (or null) for this query.",
        "input_schema": MATCH_TOOL_SCHEMA,
    }
]

SYSTEM_PROMPT = """You are performing a PARAGRAPH-level version of the "closest-section-match" \
family of comparisons: given ONE query paragraph from a specific, already-identified section \
or subsection of paper1, and the full set of candidate paragraphs from a specific, already-\
identified section or subsection of paper2, find the SINGLE closest-matching paper2 paragraph, \
or determine that none corresponds.

Both paragraph pools are already scoped down to sections (or subsections) that have already \
been judged to correspond, or are suspected to, at the SECTION level -- this is not a whole-\
paper search. A null result here does not mean "nothing like this paragraph exists anywhere \
in paper2," only "nothing in THIS specific candidate pool plays the same role at the paragraph \
level."

Each paragraph -- query and candidate alike -- carries its own question_this_text_answers \
field in addition to its text. Read both together as one joint body of evidence, the same \
discipline used throughout this skill family: weigh the question field as reliable, primary \
evidence of what the paragraph is doing, and let the paragraph text override it only on a \
genuine conflict (watch for a question that undersells or narrows what the paragraph's text \
actually covers). Never judge from text alone when a question field is present, and never \
let the question pre-filter which candidates get their text read -- read every candidate \
paragraph's text in full before deciding.

Report exactly ONE match. If the query paragraph's content genuinely touches more than one \
candidate paragraph, pick whichever candidate most centrally corresponds, and mention the \
secondary overlap as a brief aside inside `basis` rather than refusing to choose.

A null result (match_index: null) is common and expected -- a section-level pairing can hold \
even when individual paragraphs on one side have no direct counterpart on the other (e.g. one \
paper elaborates with an extra example, edge case, caveat, or implementation detail the other \
simply omits). Do not force the least-bad candidate just because the pools were pre-scoped to \
a matching section pair.

Never leave `basis` empty, even when there is no match -- explain why nothing corresponds.

Respond only by calling the record_match tool."""


class UsageTotals:
    """Thread-safe accumulator for response.usage across concurrent calls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0

    def add(self, usage: Any) -> None:
        if usage is None:
            return
        with self._lock:
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0
            self.cache_creation_input_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
            self.cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0


PRINT_LOCK = threading.Lock()


def safe_print(*args: Any, **kwargs: Any) -> None:
    with PRINT_LOCK:
        print(*args, **kwargs)


def load_paper(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def norm_name(name: Any) -> str:
    return (name or "").strip().lower()


def find_section_entry(
    entries: list[dict[str, Any]], section_name: str, section_number: str | None, label: str
) -> dict[str, Any]:
    matches = [e for e in entries if norm_name(e.get("section_name")) == norm_name(section_name)]
    if section_number is not None:
        matches = [e for e in matches if str(e.get("section_number")) == str(section_number)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise SystemExit(
            f"[{label}] Ambiguous: {len(matches)} top-level sections named {section_name!r} "
            f"-- pass the matching section-number argument too. Candidates: "
            + ", ".join(f"{e.get('section_name')!r} (number={e.get('section_number')!r})" for e in matches)
        )
    available = ", ".join(f"{e.get('section_name')!r}" for e in entries)
    raise SystemExit(f"[{label}] No top-level section named {section_name!r} found. Available: {available}")


def find_subsection_entry(
    section_entry: dict[str, Any], subsection_name: str, subsection_number: str | None, label: str
) -> dict[str, Any]:
    subs = section_entry.get("subsections") or []
    matches = [s for s in subs if norm_name(s.get("section_name")) == norm_name(subsection_name)]
    if subsection_number is not None:
        matches = [s for s in matches if str(s.get("section_number")) == str(subsection_number)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise SystemExit(
            f"[{label}] Ambiguous: {len(matches)} subsections named {subsection_name!r} under "
            f"{section_entry.get('section_name')!r} -- pass the matching subsection-number argument too."
        )
    available = ", ".join(f"{s.get('section_name')!r}" for s in subs)
    raise SystemExit(
        f"[{label}] No subsection named {subsection_name!r} found under "
        f"{section_entry.get('section_name')!r}. Available subsections: {available or '(none)'}"
    )


def collect_paragraph_pool(
    entries: list[dict[str, Any]],
    section_name: str,
    section_number: str | None,
    subsection_name: str | None,
    subsection_number: str | None,
    label: str,
) -> list[dict[str, Any]]:
    """Resolves --paperN-section[/-subsection] against entries and returns the
    flat list of paragraph dicts to use as that side's pool, each tagged with
    its own section/subsection identity (section identity is the resolved
    top-level section throughout; subsection identity is None for a section's
    own lead-in paragraphs, or that specific subsection's identity).

    If subsection_name is given, the pool is JUST that subsection's own
    paragraphs. Otherwise it's the section's own paragraphs plus every one of
    its subsections' paragraphs concatenated -- the same "whole section"
    definition closest_section_match_batch.py's build_candidates() uses.
    """
    section_entry = find_section_entry(entries, section_name, section_number, label)
    resolved_section_name = section_entry.get("section_name")
    resolved_section_number = section_entry.get("section_number")

    pool: list[dict[str, Any]] = []

    def add_paragraphs(paragraphs: list[dict[str, Any]] | None, sub_name: str | None, sub_number: str | None) -> None:
        for p in paragraphs or []:
            pool.append(
                {
                    "section_name": resolved_section_name,
                    "section_number": resolved_section_number,
                    "subsection_name": sub_name,
                    "subsection_number": sub_number,
                    "paragraph_number": p.get("paragraph_number"),
                    "text": p.get("text", ""),
                    "question": p.get("question_this_text_answers"),
                }
            )

    if subsection_name is not None:
        sub_entry = find_subsection_entry(section_entry, subsection_name, subsection_number, label)
        add_paragraphs(sub_entry.get("paragraphs"), sub_entry.get("section_name"), sub_entry.get("section_number"))
    else:
        add_paragraphs(section_entry.get("paragraphs"), None, None)
        for sub in section_entry.get("subsections") or []:
            add_paragraphs(sub.get("paragraphs"), sub.get("section_name"), sub.get("section_number"))

    return pool


def paragraph_label(p: dict[str, Any]) -> str:
    loc = p["section_name"]
    if p["subsection_name"]:
        loc += f" > {p['subsection_name']}"
    return f"{loc} ¶{p['paragraph_number']}"


def format_paper2_context(paper2_paragraphs: list[dict[str, Any]]) -> str:
    blocks = []
    for i, p in enumerate(paper2_paragraphs):
        blocks.append(
            f"[{i}] section_name={p['section_name']!r} section_number={p['section_number']!r} "
            f"subsection_name={p['subsection_name']!r} subsection_number={p['subsection_number']!r} "
            f"paragraph_number={p['paragraph_number']!r}\n"
            f"  question_this_text_answers: {p['question']!r}\n"
            f"  text: {p['text']}"
        )
    return "\n\n".join(blocks)


def format_query(q: dict[str, Any]) -> str:
    return (
        f"QUERY (paper1) section_name={q['section_name']!r} section_number={q['section_number']!r} "
        f"subsection_name={q['subsection_name']!r} subsection_number={q['subsection_number']!r} "
        f"paragraph_number={q['paragraph_number']!r}\n"
        f"question_this_text_answers: {q['question']!r}\n"
        f"text: {q['text']}"
    )


def check_questions_present(pool: list[dict[str, Any]], label: str) -> bool:
    """Precondition check, same discipline as closest_section_match_batch.py's
    own check_questions_present(): does this paragraph pool show real signs of
    having been through per-paragraph question annotation?"""
    if not pool:
        return True  # emptiness is handled separately by the caller
    with_question = sum(1 for p in pool if p.get("question"))
    ratio = with_question / len(pool)
    print(f"[{label}] {with_question}/{len(pool)} paragraphs have question_this_text_answers (ratio {ratio:.2f}).")
    if ratio == 0:
        print(
            f"[{label}] WARNING: no paragraph in this pool has a question_this_text_answers field. "
            "Matching will effectively fall back to text-only judgment -- if this pool's paragraphs "
            "were supposed to carry per-paragraph questions, check the input file before trusting results."
        )
    return True


def build_paper2_cache_block(paper2_context: str) -> dict[str, Any]:
    """The cacheable content block: paper2's full (pre-scoped) paragraph pool,
    identical across every call in this run."""
    return {
        "type": "text",
        "text": (
            "PAPER2 CANDIDATE PARAGRAPHS (numbered, 0-based) -- already scoped to the "
            "section/subsection you identified; this is the fixed candidate pool for "
            "every query paragraph in this run:\n\n" + paper2_context
        ),
        "cache_control": {"type": "ephemeral"},
    }


def prewarm_cache(client: Any, model: str, paper2_cache_block: dict[str, Any], usage_totals: UsageTotals) -> bool:
    """Same rationale as closest_section_match_batch.py's prewarm_cache(): write
    paper2's candidate-pool cache block once, confirmed, before opening the
    thread pool -- see that script's docstring for the full explanation."""
    placeholder = {"type": "text", "text": "warmup"}
    response = client.messages.create(
        model=model,
        max_tokens=0,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [paper2_cache_block, placeholder]}],
        tools=TOOLS,
    )
    usage_totals.add(getattr(response, "usage", None))
    usage = getattr(response, "usage", None)
    created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    print(f"Cache pre-warm complete: cache_creation_input_tokens={created}")
    if created == 0:
        print(
            "  WARNING: no cache write recorded on pre-warm. If paper2's candidate pool is very "
            "small (a short subsection), it may be under the model's minimum cacheable token "
            "count -- every subsequent call will then run uncached (still correct, just not discounted)."
        )
        return False
    return True


def call_claude_for_match(
    client: Any,
    model: str,
    query: dict[str, Any],
    paper2_cache_block: dict[str, Any],
    usage_totals: UsageTotals,
    max_retries: int = 3,
) -> tuple[int | None, str]:
    query_block = {
        "type": "text",
        "text": (
            f"{format_query(query)}\n\n"
            "Which single paper2 candidate paragraph (by index) is the closest match to the "
            "query paragraph? If none corresponds, use match_index: null."
        ),
    }
    messages = [{"role": "user", "content": [paper2_cache_block, query_block]}]

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOLS,
                tool_choice={"type": "tool", "name": "record_match"},
            )
            usage_totals.add(getattr(response, "usage", None))
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
            safe_print(f"    API call failed (attempt {attempt}/{max_retries}): {exc}. Retrying in {wait}s...")
            time.sleep(wait)

    return None, f"API call failed after {max_retries} attempts: {last_error}"


def build_row(query: dict[str, Any], match_index: int | None, basis: str, paper2_paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    row = {
        "paper1_section_name": query["section_name"],
        "paper1_section_number": query["section_number"],
        "paper1_subsection_name": query["subsection_name"],
        "paper1_subsection_number": query["subsection_number"],
        "paper1_paragraph_number": query["paragraph_number"],
        "paper1_text": query["text"],
        "paper2_section_name": None,
        "paper2_section_number": None,
        "paper2_subsection_name": None,
        "paper2_subsection_number": None,
        "paper2_paragraph_number": None,
        "paper2_text": None,
        "basis": basis,
    }
    if match_index is not None and 0 <= match_index < len(paper2_paragraphs):
        match = paper2_paragraphs[match_index]
        row["paper2_section_name"] = match["section_name"]
        row["paper2_section_number"] = match["section_number"]
        row["paper2_subsection_name"] = match["subsection_name"]
        row["paper2_subsection_number"] = match["subsection_number"]
        row["paper2_paragraph_number"] = match["paragraph_number"]
        row["paper2_text"] = match["text"]
    return row


def slug(*parts: str | None) -> str:
    joined = "-".join(p for p in parts if p)
    return re.sub(r"[^a-z0-9]+", "-", joined.lower()).strip("-") or "section"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--paper1", required=True, help="Path to paper1's nested sections JSON")
    parser.add_argument("--paper2", required=True, help="Path to paper2's nested sections JSON")
    parser.add_argument("--paper1-section", required=True, help="Top-level section name in paper1 to scope queries to")
    parser.add_argument("--paper1-section-number", default=None, help="Disambiguates --paper1-section if the name isn't unique")
    parser.add_argument("--paper1-subsection", default=None, help="If given, narrows paper1's pool to just this subsection (of --paper1-section)")
    parser.add_argument("--paper1-subsection-number", default=None, help="Disambiguates --paper1-subsection if the name isn't unique")
    parser.add_argument("--paper2-section", required=True, help="Top-level section name in paper2 to scope the candidate pool to")
    parser.add_argument("--paper2-section-number", default=None, help="Disambiguates --paper2-section if the name isn't unique")
    parser.add_argument("--paper2-subsection", default=None, help="If given, narrows paper2's pool to just this subsection (of --paper2-section)")
    parser.add_argument("--paper2-subsection-number", default=None, help="Disambiguates --paper2-subsection if the name isn't unique")
    parser.add_argument("--output", default=None, help="Output JSON path (default: alongside paper1, auto-named)")
    parser.add_argument("--model", default="claude-sonnet-5", help="Anthropic model string (default: claude-sonnet-5)")
    parser.add_argument("--max-workers", type=int, default=5, help="Concurrent query calls once the cache is warm (default: 5)")
    parser.add_argument("--limit", type=int, default=None, help="Stop after this many real API calls this run (see closest_section_match_batch.py for the --resume workflow this pairs with)")
    parser.add_argument("--resume", action="store_true", help="Skip paragraphs already resolved in an existing --output file, keyed by paper1 paragraph identity")
    args = parser.parse_args()

    paper1_path = Path(args.paper1)
    paper2_path = Path(args.paper2)
    paper1_name = paper1_path.name.split("-sections-with-subsections")[0]
    paper2_name = paper2_path.name.split("-sections-with-subsections")[0]

    print(f"Loading paper1: {paper1_path}")
    paper1_entries = load_paper(str(paper1_path))
    print(f"Loading paper2: {paper2_path}")
    paper2_entries = load_paper(str(paper2_path))

    paper1_queries = collect_paragraph_pool(
        paper1_entries, args.paper1_section, args.paper1_section_number,
        args.paper1_subsection, args.paper1_subsection_number, "paper1",
    )
    paper2_candidates = collect_paragraph_pool(
        paper2_entries, args.paper2_section, args.paper2_section_number,
        args.paper2_subsection, args.paper2_subsection_number, "paper2",
    )

    p1_scope = args.paper1_subsection or args.paper1_section
    p2_scope = args.paper2_subsection or args.paper2_section
    print(f"\npaper1 pool: {len(paper1_queries)} paragraph(s) from {args.paper1_section}"
          f"{' > ' + args.paper1_subsection if args.paper1_subsection else ' (whole section)'}")
    print(f"paper2 pool: {len(paper2_candidates)} paragraph(s) from {args.paper2_section}"
          f"{' > ' + args.paper2_subsection if args.paper2_subsection else ' (whole section)'}")

    if not paper1_queries:
        print("\npaper1's identified section/subsection has zero paragraphs -- nothing to query. Exiting.")
        sys.exit(1)

    check_questions_present(paper1_queries, "paper1")
    check_questions_present(paper2_candidates, "paper2")

    output_path = (
        Path(args.output)
        if args.output
        else paper1_path.parent / f"{paper1_name}-{slug(p1_scope)}-{paper2_name}-{slug(p2_scope)}-closest-paragraph-match.json"
    )

    def query_key(q: dict[str, Any]) -> tuple[Any, Any, Any]:
        return (q["subsection_name"], q["subsection_number"], q["paragraph_number"])

    def row_key(row: dict[str, Any]) -> tuple[Any, Any, Any]:
        return (row["paper1_subsection_name"], row["paper1_subsection_number"], row["paper1_paragraph_number"])

    resumed_rows: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    if args.resume and output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            existing_rows = json.load(f)
        for row in existing_rows:
            resumed_rows[row_key(row)] = row
        print(f"\n--resume: found {len(resumed_rows)} already-resolved rows in {output_path}")

    rows_by_index: dict[int, dict[str, Any]] = {}
    api_indices: list[int] = []
    n_resumed = 0
    for i, query in enumerate(paper1_queries):
        key = query_key(query)
        if key in resumed_rows:
            rows_by_index[i] = resumed_rows[key]
            n_resumed += 1
        else:
            api_indices.append(i)

    if not paper2_candidates:
        print("\npaper2's identified section/subsection has zero paragraphs -- every paper1 "
              "paragraph is resolved locally as no-match (no API call).")
        for i in api_indices:
            rows_by_index[i] = build_row(
                paper1_queries[i], None,
                "paper2's identified section/subsection has no paragraphs -- nothing to compare against.",
                paper2_candidates,
            )
        api_indices = []

    n_available_api = len(api_indices)
    skipped_indices: list[int] = []
    if args.limit is not None and len(api_indices) > args.limit:
        skipped_indices = api_indices[args.limit:]
        api_indices = api_indices[: args.limit]

    if n_resumed:
        print(f"Carried forward {n_resumed} already-resolved rows from a previous run.")
    if n_available_api:
        print(f"{n_available_api} paragraph queries still need an API call this run.")
    if args.limit is not None and skipped_indices:
        print(f"--limit {args.limit}: sending {len(api_indices)} of those {n_available_api} calls now, "
              f"leaving {len(skipped_indices)} for a follow-up --resume run.")

    usage_totals = UsageTotals()

    if api_indices:
        try:
            from anthropic import Anthropic
        except ImportError:
            print("\nThe 'anthropic' package is not installed. Run: pip install anthropic")
            sys.exit(1)

        client = Anthropic()
        paper2_context = format_paper2_context(paper2_candidates)
        paper2_cache_block = build_paper2_cache_block(paper2_context)
        print(f"\npaper2 cache block built once, ~{len(paper2_context)} chars "
              f"(~{len(paper2_context) // 4} tokens) -- reused as a cached prefix on every API call below.")

        print("\nPre-warming prompt cache with paper2's candidate paragraph pool...")
        prewarm_cache(client, args.model, paper2_cache_block, usage_totals)

        print(f"\nDispatching {len(api_indices)} queries across {args.max_workers} concurrent workers...")
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            future_to_index = {
                executor.submit(
                    call_claude_for_match, client, args.model, paper1_queries[i], paper2_cache_block, usage_totals
                ): i
                for i in api_indices
            }
            completed = 0
            for future in as_completed(future_to_index):
                i = future_to_index[future]
                query = paper1_queries[i]
                match_index, basis = future.result()
                completed += 1
                if match_index is not None and 0 <= match_index < len(paper2_candidates):
                    safe_print(
                        f"[{completed}/{len(api_indices)}] {paragraph_label(query)} "
                        f"-> {paragraph_label(paper2_candidates[match_index])}"
                    )
                else:
                    safe_print(f"[{completed}/{len(api_indices)}] {paragraph_label(query)} -> no match")
                rows_by_index[i] = build_row(query, match_index, basis, paper2_candidates)

    resolved_indices = sorted(rows_by_index.keys())
    n_matched = sum(1 for i in resolved_indices if rows_by_index[i]["paper2_paragraph_number"] is not None)
    n_null = len(resolved_indices) - n_matched
    rows = [rows_by_index[i] for i in resolved_indices]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = len(paper1_queries)
    remaining = total - len(resolved_indices)
    print(f"\nDone. {len(rows)}/{total} rows written to {output_path}")
    print(f"  Carried forward from a prior run: {n_resumed}")
    print(f"  API calls made this run: {len(api_indices)}")
    print(f"  Real matches: {n_matched}")
    print(f"  No match: {n_null}")
    if remaining:
        print(
            f"\n{remaining} queries still unresolved (left out by --limit). To continue:\n"
            f"  python3 closest_paragraph_match_within_section.py --paper1 {paper1_path} --paper2 {paper2_path} "
            f"--paper1-section {args.paper1_section!r}"
            + (f" --paper1-subsection {args.paper1_subsection!r}" if args.paper1_subsection else "")
            + f" --paper2-section {args.paper2_section!r}"
            + (f" --paper2-subsection {args.paper2_subsection!r}" if args.paper2_subsection else "")
            + f" --output {output_path} --resume"
            + (f" --limit {args.limit}" if args.limit is not None else "")
        )

    if api_indices:
        print("\nToken usage (from response.usage, summed across all API calls including pre-warm):")
        print(f"  input_tokens (uncached, billed at full price):        {usage_totals.input_tokens}")
        print(f"  cache_creation_input_tokens (full price, first write): {usage_totals.cache_creation_input_tokens}")
        print(f"  cache_read_input_tokens (discounted, ~10% of full price): {usage_totals.cache_read_input_tokens}")
        print(f"  output_tokens:                                         {usage_totals.output_tokens}")


if __name__ == "__main__":
    main()
