"""Relabel fixed paragraph boundaries while giving Claude the complete paper.

This treatment deliberately changes only paragraph-question generation. Source
paragraph text, ids, order, section membership, and discourse relations remain
unchanged so downstream differences can be attributed to the added context.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from anthropic import Anthropic
from cache_utils import cached_system, log_cache_usage
from pdf_text import extract_pdf_text
from pipeline_paths import output_dir
from section_schema import SectionedPaper

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
OUTPUT_DIR = output_dir()
CACHE_DIR = OUTPUT_DIR / "_cache" / "full_paper_context"

SYSTEM_PROMPT = """You label fixed paragraphs in an academic paper by the implicit questions they answer.

You will receive the COMPLETE paper text followed by its fixed target paragraphs, divided into their
existing sections. Every bounded paragraph is a target. Use the whole paper to infer each paragraph's conceptual and
argumentative role in the greater scheme of the paper, not merely its local topic or section heading.

For EVERY paragraph id, return one grammatical, standalone question ending in a question mark. The
question must be understandable on its own and should normally be concise. A question may describe an
evidentiary or connective role, such as "What evidence supports the previous claim?", when appropriate.
Do not merge, split, omit, or reorder paragraph ids. Do not return categories, noun phrases, explanations,
or confidence values."""

USER_PROMPT_TEMPLATE = """Paper id: {paper_id}
Paper title: {title}

Complete paper source and fixed paragraph targets:

{formatted_paper}

Return one complete implicit question for every supplied paragraph id using the tool."""


def _tool(paragraph_ids: list[str]) -> dict[str, Any]:
    return {
        "name": "record_full_paper_paragraph_questions",
        "description": "Record one complete implicit question for every fixed paragraph.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "paragraphs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "paragraph_id": {"type": "string", "enum": paragraph_ids},
                            "question": {
                                "type": "string",
                                "description": "A grammatical standalone question ending in '?'.",
                            },
                        },
                        "required": ["paragraph_id", "question"],
                    },
                }
            },
            "required": ["paragraphs"],
        },
    }


def _normalize_question(value: str) -> str:
    question = " ".join(str(value).strip().split())
    if not question:
        raise ValueError("Claude returned an empty paragraph question")
    return question if question.endswith("?") else question.rstrip(".") + "?"


def format_complete_paper(
    paper: SectionedPaper, complete_paper_text: str | None = None
) -> str:
    """Render the full source plus every fixed target paragraph in source order."""
    sections = {section.id: section for section in paper.sections}
    target_blocks: list[str] = []
    previous_section_id: str | None = None
    for paragraph in paper.paragraphs:
        if paragraph.parent_section_id != previous_section_id:
            if previous_section_id is not None:
                target_blocks.append("</section>")
            previous_section_id = paragraph.parent_section_id
            section = sections.get(previous_section_id)
            target_blocks.append(
                f'<section id="{previous_section_id}" title="{section.title if section else ""}">'
            )
        target_blocks.append(
            f'<paragraph id="{paragraph.id}">\n{paragraph.text.strip()}\n</paragraph>'
        )
    if previous_section_id is not None:
        target_blocks.append("</section>")
    source_text = complete_paper_text
    if source_text is None:
        source_text = "\n\n".join(paragraph.text for paragraph in paper.paragraphs)
    return (
        "<complete_paper_text>\n"
        + source_text.strip()
        + "\n</complete_paper_text>\n\n"
        + "<fixed_target_paragraphs>\n"
        + "\n\n".join(target_blocks)
        + "\n</fixed_target_paragraphs>"
    )


def relabel_paper(
    paper: SectionedPaper,
    *,
    complete_paper_text: str | None = None,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
) -> tuple[SectionedPaper, dict[str, Any]]:
    if not paper.paragraphs:
        raise ValueError(f"Paper {paper.paper_id!r} has no fixed paragraphs to relabel")
    paragraph_ids = [paragraph.id for paragraph in paper.paragraphs]
    formatted_paper = format_complete_paper(paper, complete_paper_text)
    prompt = USER_PROMPT_TEMPLATE.format(
        paper_id=paper.paper_id,
        title=paper.title,
        formatted_paper=formatted_paper,
    )
    tool = _tool(paragraph_ids)
    prompt_hash = hashlib.sha256(
        (
            f"{model}\n{SYSTEM_PROMPT}\n"
            + json.dumps(tool, sort_keys=True)
            + f"\n{prompt}"
        ).encode("utf-8")
    ).hexdigest()
    cache_path = CACHE_DIR / f"{paper.paper_id}__{prompt_hash[:16]}.json"
    if cache_path.is_file():
        result = json.loads(cache_path.read_text(encoding="utf-8"))
        result["cache_hit"] = True
    else:
        anthropic = client or Anthropic()
        last_error = "Claude did not call the full-paper question tool"
        result = None
        for attempt in range(3):
            repair = ""
            if attempt:
                repair = (
                    "\n\nYour previous tool response was invalid. Return every supplied paragraph id "
                    "exactly once with a non-empty complete question."
                )
            response = anthropic.messages.create(
                model=model,
                max_tokens=min(32_000, max(4_000, len(paragraph_ids) * 100)),
                system=cached_system(SYSTEM_PROMPT),
                messages=[{"role": "user", "content": prompt + repair}],
                tools=[tool],
                tool_choice={
                    "type": "tool",
                    "name": "record_full_paper_paragraph_questions",
                },
            )
            log_cache_usage(f"{paper.paper_id} full-paper context", response)
            try:
                raw = next(
                    block.input.get("paragraphs")
                    for block in response.content
                    if block.type == "tool_use"
                    and block.name == "record_full_paper_paragraph_questions"
                    and isinstance(block.input, dict)
                )
                if not isinstance(raw, list):
                    raise TypeError("paragraphs was not an array")
                questions: dict[str, str] = {}
                allowed = set(paragraph_ids)
                for item in raw:
                    paragraph_id = str(item.get("paragraph_id", ""))
                    if paragraph_id not in allowed or paragraph_id in questions:
                        raise ValueError(
                            f"Invalid or duplicate paragraph id {paragraph_id!r}"
                        )
                    questions[paragraph_id] = _normalize_question(
                        item.get("question", "")
                    )
                missing = allowed - set(questions)
                if missing:
                    raise ValueError(f"Claude omitted {len(missing)} paragraph ids")
                result = {
                    "paper_id": paper.paper_id,
                    "model": model,
                    "prompt_hash": prompt_hash,
                    "context_mode": "full_paper_fixed_boundaries",
                    "input_characters": len(formatted_paper),
                    "complete_paper_characters": len(complete_paper_text or ""),
                    "complete_paper_sha256": hashlib.sha256(
                        (complete_paper_text or "").encode("utf-8")
                    ).hexdigest(),
                    "input_paragraph_ids": paragraph_ids,
                    "questions": questions,
                    "cache_hit": False,
                }
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
                break
            except (StopIteration, TypeError, ValueError) as exc:
                last_error = str(exc)
                print(
                    f"    {paper.paper_id}: invalid full-paper response on attempt "
                    f"{attempt + 1}; retrying ..."
                )
        if result is None:
            raise RuntimeError(
                f"Could not relabel {paper.paper_id!r} with full-paper context: {last_error}"
            )

    questions = result["questions"]
    original_questions = {paragraph.id: paragraph.tag for paragraph in paper.paragraphs}
    updated = paper.model_copy(
        update={
            "paragraphs": [
                paragraph.model_copy(update={"tag": questions[paragraph.id]})
                for paragraph in paper.paragraphs
            ]
        }
    )
    provenance = {key: value for key, value in result.items() if key != "questions"}
    provenance["changes"] = [
        {
            "paragraph_id": paragraph_id,
            "previous_question": original_questions[paragraph_id],
            "question": questions[paragraph_id],
        }
        for paragraph_id in paragraph_ids
    ]
    return updated, provenance


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    records = []
    for entry in manifest:
        path = OUTPUT_DIR / entry["file"]
        paper = SectionedPaper.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
        print(
            f"[{paper.paper_id}] relabeling {len(paper.paragraphs)} fixed paragraphs "
            "with complete-paper context ..."
        )
        complete_paper_text = extract_pdf_text(
            str(OUTPUT_DIR / "input_papers" / f"{paper.paper_id}.pdf")
        )
        updated, provenance = relabel_paper(
            paper, complete_paper_text=complete_paper_text
        )
        path.write_text(json.dumps(updated.model_dump(), indent=2), encoding="utf-8")
        records.append(provenance)
    (OUTPUT_DIR / "paragraph_context_relabel.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "context_mode": "full_paper_fixed_boundaries",
                "papers": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
