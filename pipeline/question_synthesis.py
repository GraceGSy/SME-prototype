"""Claude-backed question synthesis from complete source paragraphs."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from cache_utils import cached_system, log_cache_usage

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You synthesize complete questions from source evidence in academic papers.

You will receive one or more COMPLETE paragraphs. Each paragraph includes stable provenance and an
earlier question tag. Read the paragraph text itself; do not merely aggregate or paraphrase the tags.
Identify the single overarching question that these paragraphs collectively answer in the larger
argument of their papers. Express it as a grammatical, standalone question ending in a question mark.
Keep it concise (normally under 18 words), but do not sacrifice completeness for brevity.

When exactly one previous question is supplied and it still accurately covers all of the evidence,
return that question verbatim. Revise it only when the evidence materially changes its scope or meaning.
When multiple previous questions are supplied for a merge, synthesize the narrowest coherent question
that covers their combined evidence.

Do not produce a category label, noun phrase, list, explanation, or confidence score."""

USER_PROMPT_TEMPLATE = """Previous questions for this lineage (retain one verbatim when it still fits; otherwise derive the question from the full paragraphs):
{previous_questions}

Complete source paragraphs:

{formatted_paragraphs}

Record the one complete overarching question using the tool."""


def _tool() -> dict[str, Any]:
    return {
        "name": "record_overarching_question",
        "description": "Record the complete overarching question answered by the supplied paragraphs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "overarching_question": {
                    "type": "string",
                    "description": "One grammatical standalone question ending in a question mark.",
                }
            },
            "required": ["overarching_question"],
        },
    }


def _safe_label(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "question"


def _normalize_question(value: str) -> str:
    question = " ".join(value.strip().split())
    if not question:
        raise ValueError("Claude returned an empty overarching question")
    return question if question.endswith("?") else question.rstrip(".") + "?"


def format_paragraphs(paragraphs: list[dict[str, Any]]) -> str:
    blocks = []
    for paragraph in paragraphs:
        provenance = (
            f"paper={paragraph['paper']} | section={paragraph.get('section_title') or paragraph.get('parent_section_id', '')} "
            f"| paragraph={paragraph['unit_id']} | earlier_question={paragraph.get('tag', '')}"
        )
        blocks.append(f"[{provenance}]\n{paragraph.get('text', '').strip()}")
    return "\n\n--- NEXT COMPLETE PARAGRAPH ---\n\n".join(blocks)


def synthesize_question(
    label: str,
    paragraphs: list[dict[str, Any]],
    cache_dir: Path,
    *,
    previous_questions: list[str] | None = None,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
) -> dict[str, Any]:
    if not paragraphs:
        raise ValueError(f"Cannot synthesize {label!r} without paragraphs")

    paragraph_text = format_paragraphs(paragraphs)
    prior = previous_questions or []
    prompt = USER_PROMPT_TEMPLATE.format(
        previous_questions=(
            "\n".join(f"- {question}" for question in prior) if prior else "(none)"
        ),
        formatted_paragraphs=paragraph_text,
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{_safe_label(label)}__{prompt_hash[:16]}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        cached["cache_hit"] = True
        return cached

    anthropic = client or Anthropic()
    response = anthropic.messages.create(
        model=model,
        max_tokens=300,
        system=cached_system(SYSTEM_PROMPT),
        messages=[{"role": "user", "content": prompt}],
        tools=[_tool()],
        tool_choice={"type": "tool", "name": "record_overarching_question"},
    )
    log_cache_usage(label, response)

    for block in response.content:
        if block.type != "tool_use" or block.name != "record_overarching_question":
            continue
        data = block.input
        if set(data.keys()) - {"overarching_question"} and len(data) == 1:
            data = next(iter(data.values()))
        result = {
            "overarching_question": _normalize_question(
                data.get("overarching_question", "")
            ),
            "model": model,
            "prompt_hash": prompt_hash,
            "input_paragraph_ids": [f"{p['paper']}:{p['unit_id']}" for p in paragraphs],
            "input_characters": sum(len(p.get("text", "")) for p in paragraphs),
            "cache_hit": False,
        }
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    raise RuntimeError(f"Claude did not synthesize a question for {label!r}")
