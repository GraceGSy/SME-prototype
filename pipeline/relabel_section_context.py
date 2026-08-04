"""Relabel fixed paragraphs using only their complete source section.

This treatment freezes paragraph text, ids, order, section membership, and
relations. Claude receives one section per request, so it cannot use text from
other sections while inferring each paragraph's implicit question.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from typing import Any

from anthropic import Anthropic

from cache_utils import cached_system, log_cache_usage
from pipeline_paths import output_dir
from section_schema import SectionedPaper

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
OUTPUT_DIR = output_dir()
CACHE_DIR = OUTPUT_DIR / "_cache" / "fixed_section_context"

SYSTEM_PROMPT = """You label fixed paragraphs in an academic paper by the implicit questions they answer.

You will receive exactly ONE complete source section and every fixed target paragraph that belongs to
that section. Use the complete section to infer each paragraph's conceptual and argumentative role in
the paper, not merely its local topic or shared vocabulary. Do not assume access to any other section.

For EVERY paragraph id, return one grammatical, standalone question ending in a question mark. The
question must be understandable on its own and should normally be concise. A question may describe an
evidentiary or connective role, such as "What evidence supports the previous claim?", when appropriate.
Do not merge, split, omit, or reorder paragraph ids. Do not return categories, noun phrases,
explanations, or confidence values."""

USER_PROMPT_TEMPLATE = """Paper id: {paper_id}
Paper title: {paper_title}
Section id: {section_id}
Section title: {section_title}
Section-level question: {section_question}

Complete source section:

<complete_section_text>
{section_text}
</complete_section_text>

Fixed target paragraphs from this section:

{formatted_paragraphs}

Return one complete implicit question for every supplied paragraph id using the tool."""


def _tool(paragraph_ids: list[str]) -> dict[str, Any]:
    return {
        "name": "record_section_paragraph_questions",
        "description": "Record one complete implicit question for every fixed paragraph in this section.",
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


def format_target_paragraphs(paragraphs: list[Any]) -> str:
    return "\n\n".join(
        f'<paragraph id="{paragraph.id}">\n{paragraph.text.strip()}\n</paragraph>'
        for paragraph in paragraphs
    )


def relabel_section(
    paper: SectionedPaper,
    section_id: str,
    *,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    section = next((item for item in paper.sections if item.id == section_id), None)
    if section is None:
        raise ValueError(f"Paper {paper.paper_id!r} lacks section {section_id!r}")
    paragraphs = [
        paragraph
        for paragraph in paper.paragraphs
        if paragraph.parent_section_id == section_id
    ]
    if not paragraphs:
        raise ValueError(f"Section {paper.paper_id}:{section_id} has no fixed paragraphs")
    section_text = section.text.strip()
    if not section_text:
        raise ValueError(
            f"Section {paper.paper_id}:{section_id} lacks complete section text"
        )

    paragraph_ids = [paragraph.id for paragraph in paragraphs]
    prompt = USER_PROMPT_TEMPLATE.format(
        paper_id=paper.paper_id,
        paper_title=paper.title,
        section_id=section.id,
        section_title=section.title,
        section_question=section.tag,
        section_text=section_text,
        formatted_paragraphs=format_target_paragraphs(paragraphs),
    )
    tool = _tool(paragraph_ids)
    prompt_hash = hashlib.sha256(
        (
            f"{model}\n{SYSTEM_PROMPT}\n"
            + json.dumps(tool, sort_keys=True)
            + f"\n{prompt}"
        ).encode("utf-8")
    ).hexdigest()
    cache_path = CACHE_DIR / f"{paper.paper_id}__{section.id}__{prompt_hash[:16]}.json"
    if cache_path.is_file():
        result = json.loads(cache_path.read_text(encoding="utf-8"))
        result["cache_hit"] = True
    else:
        anthropic = client or Anthropic()
        last_error = "Claude did not call the fixed-section question tool"
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
                max_tokens=min(8_000, max(1_200, len(paragraph_ids) * 100)),
                system=cached_system(SYSTEM_PROMPT),
                messages=[{"role": "user", "content": prompt + repair}],
                tools=[tool],
                tool_choice={"type": "tool", "name": "record_section_paragraph_questions"},
            )
            log_cache_usage(f"{paper.paper_id}:{section.id} fixed-section context", response)
            try:
                raw = next(
                    block.input.get("paragraphs")
                    for block in response.content
                    if block.type == "tool_use"
                    and block.name == "record_section_paragraph_questions"
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
                    questions[paragraph_id] = _normalize_question(item.get("question", ""))
                missing = allowed - set(questions)
                if missing:
                    raise ValueError(f"Claude omitted {len(missing)} paragraph ids")
                result = {
                    "paper_id": paper.paper_id,
                    "section_id": section.id,
                    "section_title": section.title,
                    "model": model,
                    "prompt_hash": prompt_hash,
                    "context_mode": "complete_section_fixed_boundaries",
                    "input_characters": len(prompt),
                    "complete_section_characters": len(section_text),
                    "complete_section_sha256": hashlib.sha256(
                        section_text.encode("utf-8")
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
                    f"    {paper.paper_id}:{section.id}: invalid fixed-section response "
                    f"on attempt {attempt + 1}; retrying ..."
                )
        if result is None:
            raise RuntimeError(
                f"Could not relabel {paper.paper_id}:{section.id} with section context: "
                f"{last_error}"
            )
    return result["questions"], {
        key: value for key, value in result.items() if key != "questions"
    }


def relabel_paper(
    paper: SectionedPaper,
    *,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
) -> tuple[SectionedPaper, dict[str, Any]]:
    if not paper.paragraphs:
        raise ValueError(f"Paper {paper.paper_id!r} has no fixed paragraphs to relabel")
    paragraphs_by_section: dict[str, list[str]] = defaultdict(list)
    for paragraph in paper.paragraphs:
        paragraphs_by_section[paragraph.parent_section_id].append(paragraph.id)

    questions: dict[str, str] = {}
    section_records = []
    for section in paper.sections:
        if section.id not in paragraphs_by_section:
            continue
        section_questions, provenance = relabel_section(
            paper, section.id, model=model, client=client
        )
        questions.update(section_questions)
        section_records.append(provenance)

    expected = {paragraph.id for paragraph in paper.paragraphs}
    missing = expected - set(questions)
    if missing:
        raise ValueError(
            f"Fixed-section relabeling omitted {len(missing)} paragraphs in {paper.paper_id}"
        )
    original_questions = {paragraph.id: paragraph.tag for paragraph in paper.paragraphs}
    updated = paper.model_copy(
        update={
            "paragraphs": [
                paragraph.model_copy(update={"tag": questions[paragraph.id]})
                for paragraph in paper.paragraphs
            ]
        }
    )
    return updated, {
        "paper_id": paper.paper_id,
        "model": model,
        "context_mode": "complete_section_fixed_boundaries",
        "input_paragraph_ids": [paragraph.id for paragraph in paper.paragraphs],
        "sections": section_records,
        "changes": [
            {
                "paragraph_id": paragraph.id,
                "previous_question": original_questions[paragraph.id],
                "question": questions[paragraph.id],
            }
            for paragraph in paper.paragraphs
        ],
    }


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    client = Anthropic()
    records = []
    for entry in manifest:
        path = OUTPUT_DIR / entry["file"]
        paper = SectionedPaper.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
        section_count = len(
            {paragraph.parent_section_id for paragraph in paper.paragraphs}
        )
        print(
            f"[{paper.paper_id}] relabeling {len(paper.paragraphs)} fixed paragraphs "
            f"across {section_count} complete sections ..."
        )
        updated, provenance = relabel_paper(paper, client=client)
        path.write_text(json.dumps(updated.model_dump(), indent=2), encoding="utf-8")
        records.append(provenance)
    (OUTPUT_DIR / "paragraph_context_relabel.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "context_mode": "complete_section_fixed_boundaries",
                "papers": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
