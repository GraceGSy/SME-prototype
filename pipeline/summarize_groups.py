"""Enrichment step: for each paragraph group in quote_groups.json, ask Claude
what overarching research question / purpose unifies the group's members, and
save that back onto the group as "overarching_question".

For each member paragraph, Claude is given: 1) the paragraph's own tag
question, 2) the paragraph's actual text content, and 3) the tag/question of
the paragraph's PARENT SECTION for context -- but NOT that section's own
content, to keep the prompt focused on the paragraphs themselves.

Only paragraph groups are processed (not section groups), per the current
ask. Uses the same prompt-caching (cache_utils.py) and per-item response
caching (resume-safe if interrupted) pattern as extract_fine_grained.py.

This module's helpers (build_paragraph_lookup, build_section_tag_lookup,
summarize_group) are reused by refine_paragraph_groups.py, which re-runs this
same summarization on iteratively-reassigned group membership.

Usage:
    python3 summarize_groups.py
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
# "iter0" -- the very first summarization pass, before any reassignment
# (see refine_paragraph_groups.py for iter1..N). Also intentionally distinct
# from this script's old flat cache path, since the enriched prompt below
# means any previously-cached response is no longer valid for it.
CACHE_DIR = OUTPUT_DIR / "_cache" / "group_summaries" / "iter0"

SYSTEM_PROMPT = """You will be given several paragraphs, each from a DIFFERENT academic paper, that \
were grouped together because they play a similar role (their own questions are similar to each \
other).

For each paragraph you'll see: the question it answers, its actual text, and -- for context only -- \
the question answered by the SECTION it came from (not that section's full content).

Identify the overarching research question these paragraphs collectively answer, or the overall \
purpose they play across these papers -- something like "What overarching research question do \
these questions answer?" or "What overall purpose do these questions play within the research paper?"

Answer with a single short question or phrase (same style as the paragraph questions -- not a fixed \
category, under ~12 words) that captures this shared theme. Give just the one overarching tag, not a \
list or an explanation."""

USER_PROMPT_TEMPLATE = """Paragraphs in this group:
{paragraphs}

Identify the overarching question/purpose using the record_overarching_question tool."""


def _build_tool() -> dict:
    return {
        "name": "record_overarching_question",
        "description": "Record the overarching research question or purpose that unifies a group of paragraphs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "overarching_question": {
                    "type": "string",
                    "description": "a short question or phrase (same style as the input tags) capturing the shared theme -- not a list, not an explanation",
                },
            },
            "required": ["overarching_question"],
        },
    }


def build_paragraph_lookup(papers: dict[str, SectionedPaper]) -> dict[tuple[str, str], Section]:
    """(paper_id, unit_id) -> the full paragraph Section, for its own text and section_id."""
    lookup: dict[tuple[str, str], Section] = {}
    for paper_id, paper in papers.items():
        for p in paper.paragraphs:
            lookup[(paper_id, p.id)] = p
    return lookup


def build_section_tag_lookup(papers: dict[str, SectionedPaper]) -> dict[tuple[str, str], str]:
    """(paper_id, section_id) -> that section's own tag question."""
    lookup: dict[tuple[str, str], str] = {}
    for paper_id, paper in papers.items():
        for s in paper.sections:
            lookup[(paper_id, s.id)] = s.tag
    return lookup


def _format_member(member: dict, paragraph_lookup: dict, section_tag_lookup: dict, index: int) -> str:
    paragraph = paragraph_lookup.get((member["paper"], member["unit_id"]))
    text = (paragraph.text if paragraph else "").replace("\n", " ").strip()
    section_tag = section_tag_lookup.get((member["paper"], paragraph.section_id), "") if paragraph else ""
    section_line = f'\n   Parent section question: "{section_tag}"' if section_tag else ""
    return f'{index}. Paragraph question: "{member["tag"]}"{section_line}\n   Paragraph content: "{text}"'


def _cache_path(cache_dir: Path, group_id: str) -> Path:
    return cache_dir / f"{group_id}.json"


def summarize_group(
    group_id: str,
    members: list[dict],
    paragraph_lookup: dict,
    section_tag_lookup: dict,
    cache_dir: Path = CACHE_DIR,
    model: str = DEFAULT_MODEL,
) -> str:
    cache_path = _cache_path(cache_dir, group_id)
    if cache_path.exists():
        print(f"    {group_id}: using cached response")
        return json.loads(cache_path.read_text())["overarching_question"]

    formatted = "\n".join(
        _format_member(m, paragraph_lookup, section_tag_lookup, i) for i, m in enumerate(members, start=1)
    )
    client = Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=200,
        system=cached_system(SYSTEM_PROMPT),
        messages=[{"role": "user", "content": USER_PROMPT_TEMPLATE.format(paragraphs=formatted)}],
        tools=[_build_tool()],
        tool_choice={"type": "tool", "name": "record_overarching_question"},
    )
    log_cache_usage(group_id, response)

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_overarching_question":
            data = block.input
            if set(data.keys()) - {"overarching_question"} and len(data) == 1:
                data = next(iter(data.values()))
            result = data.get("overarching_question", "")
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"overarching_question": result}, indent=2))
            return result

    raise RuntimeError(f"Model did not call record_overarching_question for group {group_id!r}")


def _load_papers(manifest: list[dict]) -> dict[str, SectionedPaper]:
    return {
        m["paper_id"]: SectionedPaper.model_validate(json.loads((OUTPUT_DIR / m["file"]).read_text()))
        for m in manifest
    }


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    papers = _load_papers(manifest)
    paragraph_lookup = build_paragraph_lookup(papers)
    section_tag_lookup = build_section_tag_lookup(papers)

    path = OUTPUT_DIR / "quote_groups.json"
    data = json.loads(path.read_text())

    groups = data.get("paragraphs", [])
    print(f"Summarizing {len(groups)} paragraph groups ...")
    for group in groups:
        overarching = summarize_group(group["group_id"], group["members"], paragraph_lookup, section_tag_lookup)
        group["overarching_question"] = overarching
        print(f"  {group['group_id']} ({len(group['members'])} members): {overarching!r}")

    path.write_text(json.dumps(data, indent=2))
    print(f"\nupdated {path}")


if __name__ == "__main__":
    main()
