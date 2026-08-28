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
  by shared role, not shared vocabulary; weigh the question as primary
  evidence, paragraphs overriding only on a genuine conflict; never split
  into more than one match.

  The one deviation from an LLM call: candidates with empty paragraphs AND no
  question are resolved locally via the same exact-name fallback the skill
  describes, without spending an API call.

Prompt caching: paper2's full candidate pool is identical across every one of
paper1's queries in a run, so it is sent as a single cache-marked content
block (Anthropic's ephemeral prompt cache).

Concurrency: the per-query calls are independent of each other's results --
nothing about query N's match depends on query N-1's answer -- so after the
cache is warmed, they are dispatched in parallel via a thread pool rather
than one at a time.

The one thing that *does* require sequencing is the cache write itself: a
cache entry only becomes available for reads after the first response that
wrote it begins. Firing every query at once from a cold start would mean
several requests race to be "first," each missing the not-yet-written cache
and each paying the full cache-write price for the same paper2 block --
exactly the cost this whole scheme exists to avoid. So this script explicitly
pre-warms the cache with one dedicated max_tokens=0 request (see
"Pre-warming the cache" in Anthropic's prompt caching docs) before opening
the thread pool, confirms the write actually landed
(cache_creation_input_tokens > 0), and only then fans the real per-query
calls out concurrently. Every one of those concurrent calls should then read
the already-warm cache (cache_read_input_tokens > 0) instead of writing it
again.

Because pre-warming removes the "first call is slow and pays full price"
problem, and every remaining call now runs against an already-warm cache
concurrently rather than strung out one after another with a sleep in
between, the default 5-minute ephemeral cache TTL comfortably covers even
a large run -- there is no longer a slow serial ramp that could threaten to
outlast it.

Usage:
    python3 closest_section_match_batch.py \
        --paper1 "/path/to/paper1-sections-with-subsections-and-paragraph-content-no-appendices.json" \
        --paper2 "/path/to/paper2-sections-with-subsections-and-paragraph-content-no-appendices.json" \
        [--output OUTPUT.json] [--model claude-sonnet-5] [--max-workers 5]

Requires the anthropic Python package (a reasonably recent version -- prompt
caching via the `cache_control` field and max_tokens=0 pre-warming are both
generally-available features, no beta header needed) and an
ANTHROPIC_API_KEY in the environment (the Anthropic() client picks it up
automatically). The Anthropic client is safe to share across threads -- it's
backed by httpx, which supports concurrent requests on one client instance.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

TOOLS = [
    {
        "name": "record_match",
        "description": "Record the single closest match (or null) for this query.",
        "input_schema": MATCH_TOOL_SCHEMA,
    }
]

SYSTEM_PROMPT = """You are performing one step of the "closest-section-match-nested" skill: \
given ONE query section or subsection from paper1 (its paragraphs and its own \
question_this_text_answers), and the full set of candidate sections/subsections \
from paper2 (their paragraphs and their own question_this_text_answers), \
find the SINGLE closest-matching paper2 candidate, or determine that none corresponds.

Judge correspondence by ROLE -- are the query and a candidate doing the same job \
in their respective documents, not whether they share vocabulary or topic. \
Read every paragraph on both sides in full before deciding. \
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


def build_paper2_cache_block(paper2_context: str) -> dict[str, Any]:
    """The cacheable content block: paper2's full candidate pool, identical
    across every call in a run. `cache_control` marks this as the end of the
    cacheable prefix -- everything up through this block (tools, system, and
    this block itself) gets cached after the pre-warm call writes it."""
    return {
        "type": "text",
        "text": (
            "PAPER2 CANDIDATES (numbered, 0-based) -- this is the fixed candidate "
            "pool for every query in this run:\n\n" + paper2_context
        ),
        "cache_control": {"type": "ephemeral"},
    }


def prewarm_cache(client: Any, model: str, paper2_cache_block: dict[str, Any], usage_totals: UsageTotals) -> bool:
    """Sends one max_tokens=0 request so the paper2 cache block is written
    BEFORE any real query is sent. Necessary because a cache entry only
    becomes available for reads after the first response that writes it
    begins -- firing many queries at once from a cold cache would otherwise
    make several of them race to be "first" and all pay the full write price.

    Deliberately omits tool_choice (max_tokens=0 requests reject a forced
    tool_choice) but keeps the same `tools` array as the real calls, so the
    tools+system+paper2-block prefix is byte-for-byte identical to what the
    real calls will send.

    Returns True if the cache write is confirmed (cache_creation_input_tokens
    > 0), False otherwise (e.g. paper2's context fell under the model's
    minimum cacheable token count -- see Anthropic's cache limitations docs).
    """
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
            "  WARNING: no cache write recorded on pre-warm. If paper2's context is very "
            "small, it may be under the model's minimum cacheable token count -- every "
            "subsequent call will then run uncached (still correct, just not discounted)."
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
            "Which single paper2 candidate (by index) is the closest match to the "
            "query, judged by role? If none corresponds, use match_index: null."
        ),
    }
    # The cached block comes first so it forms a stable prefix across every
    # call; the query-specific block, which varies call to call, comes after
    # it and is never itself cached.
    messages = [{"role": "user", "content": [paper2_cache_block, query_block]}]

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                # No `temperature` param: this model generation has dropped support
                # for it (400 invalid_request_error if set), unlike earlier Claude
                # models where temperature=0 was used here for determinism.
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


def build_row(query: dict[str, Any], match_index: int | None, basis: str, paper2_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if match_index is not None and 0 <= match_index < len(paper2_candidates):
        match = paper2_candidates[match_index]
        return {
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
    return {
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper1", required=True, help="Path to paper1's nested sections JSON (queries loop over this file)")
    parser.add_argument("--paper2", required=True, help="Path to paper2's nested sections JSON (candidate pool searched)")
    parser.add_argument("--output", default=None, help="Output JSON path (default: alongside paper1, auto-named)")
    parser.add_argument("--model", default="claude-sonnet-5", help="Anthropic model string (default: claude-sonnet-5)")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=5,
        help=(
            "Number of query calls to run concurrently once the cache is warm "
            "(default: 5). Keep this within your account's requests-per-minute "
            "rate limit -- all workers share one Anthropic client."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Stop after this many real API calls in THIS run (default: no limit, "
            "run to completion). Locally-resolved fallback matches don't count "
            "against the limit -- they're free and instant. Use this for a smoke "
            "test: e.g. --limit 5 to send 5 real calls, inspect the partial output "
            "file, then rerun with --resume to pick up where you left off."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "If the output file already exists, skip any query already resolved "
            "in it (matched by section/subsection identity) and only process "
            "what's still missing. Combine with --limit to work through a large "
            "run in inspectable batches without ever re-paying for a query "
            "that's already been answered."
        ),
    )
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

    client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment; safe to share across threads
    paper2_context = format_paper2_context(paper2_candidates)
    paper2_cache_block = build_paper2_cache_block(paper2_context)
    print(f"paper2 cache block built once, ~{len(paper2_context)} chars "
          f"(~{len(paper2_context) // 4} tokens) -- reused as a cached prefix on every API call below.")

    # Pre-index paper2 candidates that are content-empty, for the exact-name fallback
    empty_paper2_by_name = {
        exact_name_key(c): i for i, c in enumerate(paper2_candidates) if is_content_empty(c)
    }

    usage_totals = UsageTotals()
    rows_by_index: dict[int, dict[str, Any]] = {}
    n_fallback = 0
    n_matched = 0
    n_null = 0

    def query_key(q: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
        return (q["section_name"], q["section_number"], q["subsection_name"], q["subsection_number"])

    def row_key(row: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
        return (
            row["paper1_section_name"],
            row["paper1_section_number"],
            row["paper1_subsection_name"],
            row["paper1_subsection_number"],
        )

    # --resume: load any rows an earlier (possibly --limit-ed) run already
    # wrote to this output path, keyed by section/subsection identity, so
    # this run never re-resolves -- and never re-pays for -- a query that
    # already has a real answer sitting on disk.
    resumed_rows: dict[tuple[Any, Any, Any, Any], dict[str, Any]] = {}
    if args.resume and output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            existing_rows = json.load(f)
        for row in existing_rows:
            resumed_rows[row_key(row)] = row
        print(f"\n--resume: found {len(resumed_rows)} already-resolved rows in {output_path}")

    n_resumed = 0

    # Resolve content-empty queries locally first -- no API call needed, no
    # reason to route them through the thread pool at all.
    api_indices: list[int] = []
    for i, query in enumerate(paper1_queries):
        key = query_key(query)
        if key in resumed_rows:
            rows_by_index[i] = resumed_rows[key]
            n_resumed += 1
        elif is_content_empty(query):
            match_key = exact_name_key(query)
            if match_key in empty_paper2_by_name:
                match_index = empty_paper2_by_name[match_key]
                basis = (
                    "Both are empty placeholder entries with no body paragraphs and no "
                    "question -- matched via the exact-name fallback for content-empty candidates."
                )
            else:
                match_index = None
                basis = "No paragraphs and no question, and no equally-empty paper2 candidate has an exactly matching name."
            n_fallback += 1
            rows_by_index[i] = build_row(query, match_index, basis, paper2_candidates)
        else:
            api_indices.append(i)

    n_available_api = len(api_indices)
    skipped_indices: list[int] = []
    if args.limit is not None and len(api_indices) > args.limit:
        skipped_indices = api_indices[args.limit:]
        api_indices = api_indices[: args.limit]

    if n_resumed:
        print(f"Carried forward {n_resumed} already-resolved rows from the previous run.")
    print(f"Resolved {n_fallback} content-empty queries locally (no API call).")
    print(f"{n_available_api} queries still need an API call this run.")
    if args.limit is not None:
        print(
            f"--limit {args.limit}: sending {len(api_indices)} of those {n_available_api} calls now, "
            f"leaving {len(skipped_indices)} for a follow-up --resume run."
        )

    if api_indices:
        # Prime the cache with one blocking call BEFORE opening the thread
        # pool -- see prewarm_cache()'s docstring for why this has to happen
        # first rather than just letting the first concurrent call do it.
        print("\nPre-warming prompt cache with paper2's candidate pool...")
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
                        f"[{completed}/{len(api_indices)}] {candidate_label(query)} "
                        f"-> {candidate_label(paper2_candidates[match_index])}"
                    )
                else:
                    safe_print(f"[{completed}/{len(api_indices)}] {candidate_label(query)} -> no match")
                rows_by_index[i] = build_row(query, match_index, basis, paper2_candidates)

    resolved_indices = sorted(rows_by_index.keys())
    for i in resolved_indices:
        row = rows_by_index[i]
        if row["paper2_section_name"] is not None or row["paper2_subsection_name"] is not None:
            n_matched += 1
        else:
            n_null += 1

    rows = [rows_by_index[i] for i in resolved_indices]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = len(paper1_queries)
    remaining = total - len(resolved_indices)
    print(f"\nDone. {len(rows)}/{total} rows written to {output_path}")
    print(f"  Carried forward from a prior run: {n_resumed}")
    print(f"  API calls made this run: {len(api_indices)}")
    print(f"  Resolved via exact-name fallback this run (no API call): {n_fallback}")
    print(f"  Real matches: {n_matched}")
    print(f"  No match: {n_null}")
    if remaining:
        print(
            f"\n{remaining} queries still unresolved (left out by --limit). To continue:\n"
            f"  python3 closest_section_match_batch.py --paper1 {paper1_path} --paper2 {paper2_path} "
            f"--output {output_path} --resume"
            + (f" --limit {args.limit}" if args.limit is not None else "")
        )

    if api_indices:
        print("\nToken usage (from response.usage, summed across all API calls including pre-warm):")
        print(f"  input_tokens (uncached, billed at full price):        {usage_totals.input_tokens}")
        print(f"  cache_creation_input_tokens (full price, first write): {usage_totals.cache_creation_input_tokens}")
        print(f"  cache_read_input_tokens (discounted, ~10% of full price): {usage_totals.cache_read_input_tokens}")
        print(f"  output_tokens:                                         {usage_totals.output_tokens}")
        print(
            "  Expect cache_creation_input_tokens to be roughly the size of paper2's context "
            "and concentrated in the pre-warm call, with cache_read_input_tokens carrying that "
            "same cost on every real query call after -- confirming every concurrent call read "
            "the already-warm cache instead of re-writing it."
        )


if __name__ == "__main__":
    main()
