"""Loads one paper's JSON file in the skills pipeline's own extracted-sections format --
the ONLY shape this pipeline accepts. Unlike pipeline 2's input_data.py, there is no
dual-format dispatch here: if you have data in a different shape, convert it before
calling this. That's the whole point of this pipeline existing -- one input contract,
not two silently distinguished by whether the JSON root happens to be a list or a dict.

The ID-generation and empty-content-filtering rules below are the same ones pipeline 2
established (deduplicated section/paragraph IDs, drop anything with no real text) --
reimplemented here as plain functions with no pydantic underneath, since that machinery
isn't needed for a single, fixed input shape.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import Paper, Paragraph, Section


class InputError(ValueError):
    """Raised when a paper's JSON cannot be normalized safely."""


def _safe_id(value: Any, fallback: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return compact or fallback


def _unique_id(candidate: str, used: set[str]) -> str:
    value = candidate
    suffix = 2
    while value in used:
        value = f"{candidate}-{suffix}"
        suffix += 1
    used.add(value)
    return value


def load_paper(path: Path, paper_id: str, title: str) -> Paper:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InputError(f"Could not read paper JSON {path}: {error}") from error
    if not isinstance(payload, list):
        raise InputError(
            f"{path} must be a list of sections (the skills pipeline's own "
            f"extracted-sections format: [{{section_name, section_number, paragraphs}}, ...]) "
            f"-- got a {type(payload).__name__}."
        )

    sections: list[Section] = []
    used_section_ids: set[str] = set()
    used_paragraph_ids: set[str] = set()
    for section_index, raw_section in enumerate(payload, start=1):
        section_id = _unique_id(
            _safe_id(raw_section.get("section_number"), f"s{section_index}"),
            used_section_ids,
        )
        paragraphs: list[Paragraph] = []
        for paragraph_index, raw_paragraph in enumerate(raw_section.get("paragraphs") or [], start=1):
            paragraph_id = _unique_id(
                f"{section_id}-{_safe_id(raw_paragraph.get('paragraph_number'), f'p{paragraph_index}')}",
                used_paragraph_ids,
            )
            text = str(raw_paragraph.get("text") or "").strip()
            if not text:
                continue
            paragraphs.append(Paragraph(
                id=paragraph_id,
                label=str(raw_paragraph.get("paragraph_number") or ""),
                text=text,
            ))
        section_text = "\n\n".join(p.text for p in paragraphs) or str(raw_section.get("text") or "").strip()
        if not section_text:
            continue
        sections.append(Section(
            id=section_id,
            label=str(raw_section.get("section_name") or section_id),
            text=section_text,
            paragraphs=paragraphs,
        ))
    return Paper(paper_id=paper_id, title=title, sections=sections)
