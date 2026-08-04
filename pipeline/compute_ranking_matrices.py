"""Alternative step 8: instead of hard-assigning each paragraph to a single
best-fitting group (see refine_paragraph_groups.py, a separate track this
script does not touch), this computes two full RANKING matrices via Claude,
run for a single pass -- no iteration/reassignment loop.

Matrix 1 (paragraph -> ranked questions): for EVERY paragraph in EVERY
paper, one Claude call giving it ALL of step 7's paragraph-group
overarching_question candidates, asking it to rank ALL of them from best-
to worst-answered-by-this-paragraph. Saved to
output/sections/paragraph_question_ranking.json as
{"paper_id:unit_id": [group_id, group_id, ...]} (best first).

Matrix 2 (question, paper -> ranked paragraphs): for EVERY (overarching
question, paper) pair, one Claude call giving it ALL of that paper's
paragraphs, asking it to rank them from best-to-worst at answering that
question. Saved to output/sections/question_paragraph_ranking.json as
{group_id: {paper_id: [unit_id, unit_id, ...]}} (best first).

Caching, in both directions, follows the same principle used elsewhere in
this pipeline: whichever list is CONSTANT across a batch of calls goes in
the (Anthropic-)cached system prompt, and the one item that varies per call
goes in the user message, so the expensive/large part is only paid for once
per batch instead of once per call:
  - Matrix 1: the ~21-question list is constant across all ~236 paragraph
    calls -> lives in the cached system prompt, one call per paragraph.
  - Matrix 2: one paper's full paragraph list is constant across all ~21
    question calls for that paper -> lives in the cached system prompt,
    with papers as the outer loop and questions as the inner loop.

Every call is also cached to disk per item under output/sections/_cache/
(resume-safe / rerun-safe -- already-computed rankings are reused, no
re-calls, matching the rest of this pipeline's caching convention).

Usage:
    python3 compute_ranking_matrices.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from anthropic import Anthropic

from cache_utils import cached_system, log_cache_usage
from section_schema import Section, SectionedPaper

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"
CACHE_DIR = OUTPUT_DIR / "_cache"

MAX_ATTEMPTS = 3


def _build_ranking_tool(ids: list[str], id_field_description: str) -> dict:
    return {
        "name": "record_ranking",
        "description": "Record the full ranking, best to worst.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ranking": {
                    "type": "array",
                    "description": "every id listed exactly once, ordered best (first) to worst (last)",
                    "items": {"type": "string", "enum": ids, "description": id_field_description},
                },
            },
            "required": ["ranking"],
        },
    }


def _call_ranking_once(system_prompt: str, user_content: str, tool: dict, model: str) -> list[str]:
    client = Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=3000,
        system=cached_system(system_prompt),
        messages=[{"role": "user", "content": user_content}],
        tools=[tool],
        tool_choice={"type": "tool", "name": "record_ranking"},
    )
    log_cache_usage(model, response)
    for block in response.content:
        if block.type == "tool_use" and block.name == "record_ranking":
            data = block.input
            if set(data.keys()) - {"ranking"} and len(data) == 1:
                data = next(iter(data.values()))
            ranking = data.get("ranking", []) if isinstance(data, dict) else []
            return [r for r in ranking if isinstance(r, str)]
    return []


def _rank_with_retry(system_prompt: str, user_content: str, tool: dict, expected_ids: list[str], model: str, label: str) -> list[str]:
    expected_set = set(expected_ids)
    ranking: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ranking = _call_ranking_once(system_prompt, user_content, tool, model)
        # a valid ranking is a full permutation of expected_ids: same length, same set, no duplicates
        if len(ranking) == len(expected_ids) and len(ranking) == len(set(ranking)) and set(ranking) == expected_set:
            break
        problem = "duplicate ids" if len(ranking) != len(set(ranking)) else "missing/extra ids"
        print(f"    [{label}] attempt {attempt}/{MAX_ATTEMPTS}: got {len(ranking)}/{len(expected_ids)} ({problem})"
              + (" -- retrying" if attempt < MAX_ATTEMPTS else " -- keeping best-effort result"))
    return ranking


# ---------------------------------------------------------------------------
# Matrix 1: for each paragraph, rank all candidate questions best -> worst
# ---------------------------------------------------------------------------

M1_SYSTEM_TEMPLATE = """You are ranking a fixed set of candidate research questions by how well EACH is \
answered by one paragraph from an academic paper. Each candidate question summarizes a cluster of \
related paragraphs pulled from multiple different papers.

Candidate questions:
{listing}

You will be given a paragraph's own role-tag question and its actual text. Rank ALL of the candidate \
questions above from BEST answered by this paragraph to WORST, using their exact group_id. Every \
candidate must appear exactly once, in order."""

M1_USER_TEMPLATE = """Paragraph question: {tag}

Paragraph content:
\"\"\"
{text}
\"\"\"

Rank every candidate question from best to worst fit for this paragraph, using the record_ranking tool."""


def _m1_cache_path(paper_id: str, unit_id: str) -> Path:
    return CACHE_DIR / "paragraph_question_ranking" / f"{paper_id}__{unit_id}.json"


def rank_questions_for_paragraph(paper_id: str, unit_id: str, tag: str, text: str, candidates: list[dict], model: str = DEFAULT_MODEL) -> list[str]:
    cache_path = _m1_cache_path(paper_id, unit_id)
    if cache_path.exists():
        return json.loads(cache_path.read_text())["ranking"]

    group_ids = [c["group_id"] for c in candidates]
    listing = "\n".join(f'- {c["group_id"]}: "{c["overarching_question"]}"' for c in candidates)
    system_prompt = M1_SYSTEM_TEMPLATE.format(listing=listing)
    tool = _build_ranking_tool(group_ids, "a candidate question's group_id")

    ranking = _rank_with_retry(
        system_prompt, M1_USER_TEMPLATE.format(tag=tag, text=text), tool, group_ids, model, f"{paper_id}:{unit_id}"
    )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"ranking": ranking}, indent=2))
    return ranking


# ---------------------------------------------------------------------------
# Matrix 2: for each (question, paper), rank that paper's paragraphs best -> worst
# ---------------------------------------------------------------------------

M2_SYSTEM_TEMPLATE = """You are ranking a fixed set of paragraphs from ONE academic paper by how well \
EACH answers a given research question.

Paragraphs (unit_id: question -- content):
{listing}

You will be given the research question. Rank ALL of the paragraphs above from BEST answering this \
question to WORST, using their exact unit_id. Every paragraph must appear exactly once, in order."""

M2_USER_TEMPLATE = """Research question: {question}

Rank every paragraph from best to worst fit for this question, using the record_ranking tool."""


def _m2_cache_path(group_id: str, paper_id: str) -> Path:
    return CACHE_DIR / "question_paragraph_ranking" / f"{group_id}__{paper_id}.json"


def rank_paragraphs_for_question(group_id: str, question: str, paper_id: str, paragraphs: list[Section], model: str = DEFAULT_MODEL) -> list[str]:
    cache_path = _m2_cache_path(group_id, paper_id)
    if cache_path.exists():
        return json.loads(cache_path.read_text())["ranking"]

    unit_ids = [p.id for p in paragraphs]
    listing = "\n".join(
        f'- {p.id}: "{p.tag}" -- "{(p.text or "").replace(chr(10), " ").strip()}"' for p in paragraphs
    )
    system_prompt = M2_SYSTEM_TEMPLATE.format(listing=listing)
    tool = _build_ranking_tool(unit_ids, "a paragraph's unit_id")

    ranking = _rank_with_retry(
        system_prompt, M2_USER_TEMPLATE.format(question=question), tool, unit_ids, model, f"{group_id}:{paper_id}"
    )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"ranking": ranking}, indent=2))
    return ranking


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    papers = {
        m["paper_id"]: SectionedPaper.model_validate(json.loads((OUTPUT_DIR / m["file"]).read_text()))
        for m in manifest
    }

    quote_groups = json.loads((OUTPUT_DIR / "quote_groups.json").read_text())
    groups = quote_groups.get("paragraphs", [])
    if not groups or not all(g.get("overarching_question") for g in groups):
        raise RuntimeError("quote_groups.json has no paragraph groups with an overarching_question -- run summarize_groups.py first")
    candidates = [{"group_id": g["group_id"], "overarching_question": g["overarching_question"]} for g in groups]

    all_paragraphs = []
    for paper_id, paper in papers.items():
        for p in paper.paragraphs:
            all_paragraphs.append({"paper": paper_id, "unit_id": p.id, "tag": p.tag, "text": p.text})

    print(f"=== Matrix 1: ranking {len(candidates)} questions for {len(all_paragraphs)} paragraphs ===")
    matrix1: dict[str, list[str]] = {}
    for p in all_paragraphs:
        key = f'{p["paper"]}:{p["unit_id"]}'
        matrix1[key] = rank_questions_for_paragraph(p["paper"], p["unit_id"], p["tag"], p["text"], candidates)
    m1_path = OUTPUT_DIR / "paragraph_question_ranking.json"
    m1_path.write_text(json.dumps(matrix1, indent=2))
    print(f"wrote {m1_path}\n")

    print(f"=== Matrix 2: ranking paragraphs for {len(candidates)} questions across {len(papers)} papers ===")
    matrix2: dict[str, dict[str, list[str]]] = {}
    for paper_id, paper in papers.items():
        for c in candidates:
            group_id = c["group_id"]
            ranking = rank_paragraphs_for_question(group_id, c["overarching_question"], paper_id, paper.paragraphs)
            matrix2.setdefault(group_id, {})[paper_id] = ranking
        print(f"  [{paper_id}] ranked its {len(paper.paragraphs)} paragraphs for all {len(candidates)} questions")
    m2_path = OUTPUT_DIR / "question_paragraph_ranking.json"
    m2_path.write_text(json.dumps(matrix2, indent=2))
    print(f"wrote {m2_path}")


if __name__ == "__main__":
    main()
