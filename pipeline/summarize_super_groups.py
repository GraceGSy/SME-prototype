"""Enrichment step: for each super-group in group_of_groups.json (a group of
groups -- see group_groups.py), ask Claude what overarching research question
or purpose unifies the group's member overarching_questions, and save that
back onto the super-group as "overarching_question".

Same prompt-caching (cache_utils.py) and per-item response caching (resume-
safe if interrupted) pattern as summarize_groups.py, just applied one level
up: the input is each super-group's member overarching_question strings
instead of raw paragraph tags.

Usage:
    python3 summarize_super_groups.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from anthropic import Anthropic

from cache_utils import cached_system, log_cache_usage

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"
CACHE_DIR = OUTPUT_DIR / "_cache" / "super_group_summaries"

SYSTEM_PROMPT = """You will be given a list of short questions/phrases, each capturing the overarching \
research question or purpose that unifies a group of related paragraphs across DIFFERENT academic papers. \
These groups were themselves grouped together because their overarching questions are similar to each \
other.

Identify the overarching research question these questions collectively answer, or the overall purpose \
they play across these papers -- something like "What overarching research question do these questions \
answer?" or "What overall purpose do these questions play within the research paper?"

Answer with a single short question or phrase (same style as the input -- not a fixed category, \
under ~12 words) that captures this shared theme. Give just the one overarching tag, not a list or \
an explanation."""

USER_PROMPT_TEMPLATE = """Questions from this group-of-groups:
{questions}

Identify the overarching question/purpose using the record_overarching_question tool."""


def _build_tool() -> dict:
    return {
        "name": "record_overarching_question",
        "description": "Record the overarching research question or purpose that unifies a group of group-level questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "overarching_question": {
                    "type": "string",
                    "description": "a short question or phrase (same style as the input questions) capturing the shared theme -- not a list, not an explanation",
                },
            },
            "required": ["overarching_question"],
        },
    }


def _cache_path(super_group_id: str) -> Path:
    return CACHE_DIR / f"{super_group_id}.json"


def summarize_super_group(super_group_id: str, questions: list[str], model: str = DEFAULT_MODEL) -> str:
    cache_path = _cache_path(super_group_id)
    if cache_path.exists():
        print(f"    {super_group_id}: using cached response")
        return json.loads(cache_path.read_text())["overarching_question"]

    joined = "\n".join(f"- {q}" for q in questions)
    client = Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=200,
        system=cached_system(SYSTEM_PROMPT),
        messages=[{"role": "user", "content": USER_PROMPT_TEMPLATE.format(questions=joined)}],
        tools=[_build_tool()],
        tool_choice={"type": "tool", "name": "record_overarching_question"},
    )
    log_cache_usage(super_group_id, response)

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_overarching_question":
            data = block.input
            if set(data.keys()) - {"overarching_question"} and len(data) == 1:
                data = next(iter(data.values()))
            result = data.get("overarching_question", "")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"overarching_question": result}, indent=2))
            return result

    raise RuntimeError(f"Model did not call record_overarching_question for super-group {super_group_id!r}")


def main() -> None:
    path = OUTPUT_DIR / "group_of_groups.json"
    groups = json.loads(path.read_text())

    print(f"Summarizing {len(groups)} super-groups ...")
    for group in groups:
        questions = [m["overarching_question"] for m in group["members"]]
        overarching = summarize_super_group(group["super_group_id"], questions)
        group["overarching_question"] = overarching
        print(f"  {group['super_group_id']} ({len(questions)} members): {overarching!r}")

    path.write_text(json.dumps(groups, indent=2))
    print(f"\nupdated {path}")


if __name__ == "__main__":
    main()
