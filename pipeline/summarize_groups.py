"""Enrichment step: for each paragraph group in quote_groups.json, ask Claude
what overarching research question / purpose unifies the group's member
tags, and save that back onto the group as "overarching_question".

Only paragraph groups are processed (not section groups), per the current
ask. Uses the same prompt-caching (cache_utils.py) and per-item response
caching (resume-safe if interrupted) pattern as extract_fine_grained.py.

Usage:
    python3 summarize_groups.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from anthropic import Anthropic

from cache_utils import cached_system, log_cache_usage

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"
CACHE_DIR = OUTPUT_DIR / "_cache" / "group_summaries"

SYSTEM_PROMPT = """You will be given a list of short questions/phrases, each describing the role a \
specific paragraph plays in an academic paper. These paragraphs come from DIFFERENT papers but were \
grouped together because their questions are similar to each other.

Identify the overarching research question these paragraphs collectively answer, or the overall \
purpose they play across these papers -- something like "What overarching research question do \
these questions answer?" or "What overall purpose do these questions play within the research paper?"

Answer with a single short question or phrase (same style as the input -- not a fixed category, \
under ~12 words) that captures this shared theme. Give just the one overarching tag, not a list or \
an explanation."""

USER_PROMPT_TEMPLATE = """Questions from this group:
{questions}

Identify the overarching question/purpose using the record_overarching_question tool."""


def _build_tool() -> dict:
    return {
        "name": "record_overarching_question",
        "description": "Record the overarching research question or purpose that unifies a group of paragraph-level tags.",
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


def _cache_path(group_id: str) -> Path:
    return CACHE_DIR / f"{group_id}.json"


def summarize_group(group_id: str, tags: list[str], model: str = DEFAULT_MODEL) -> str:
    cache_path = _cache_path(group_id)
    if cache_path.exists():
        print(f"    {group_id}: using cached response")
        return json.loads(cache_path.read_text())["overarching_question"]

    questions = "\n".join(f"- {t}" for t in tags)
    client = Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=200,
        system=cached_system(SYSTEM_PROMPT),
        messages=[{"role": "user", "content": USER_PROMPT_TEMPLATE.format(questions=questions)}],
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
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"overarching_question": result}, indent=2))
            return result

    raise RuntimeError(f"Model did not call record_overarching_question for group {group_id!r}")


def main() -> None:
    path = OUTPUT_DIR / "quote_groups.json"
    data = json.loads(path.read_text())

    groups = data.get("paragraphs", [])
    print(f"Summarizing {len(groups)} paragraph groups ...")
    for group in groups:
        tags = [m["tag"] for m in group["members"]]
        overarching = summarize_group(group["group_id"], tags)
        group["overarching_question"] = overarching
        print(f"  {group['group_id']} ({len(tags)} members): {overarching!r}")

    path.write_text(json.dumps(data, indent=2))
    print(f"\nupdated {path}")


if __name__ == "__main__":
    main()
