"""Normalize extracted paper JSON into the pipeline's stable input model."""

from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
import re
from typing import Any

import yaml

from .models import Paper, PaperManifest, Paragraph, Section


class InputError(ValueError):
    """Raised when extracted paper data cannot be normalized safely."""


def load_manifest(path: Path) -> tuple[PaperManifest, list[Paper]]:
    path = path.resolve()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise InputError(f"Could not load paper manifest {path}: {error}") from error
    manifest = PaperManifest.model_validate(payload)
    papers = [load_paper((path.parent / entry.file).resolve(), entry.paper_id, entry.title) for entry in manifest.papers]
    return manifest, papers


def load_paper(path: Path, paper_id: str, title: str) -> Paper:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InputError(f"Could not load paper JSON {path}: {error}") from error
    if isinstance(payload, list):
        return _from_extracted_sections(payload, paper_id, title)
    if isinstance(payload, dict):
        return _from_sectioned_paper(payload, paper_id, title)
    raise InputError(f"Paper JSON {path} must be an object or a list of sections")


def _safe_id(value: Any, fallback: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return compact or fallback


def _from_extracted_sections(payload: list[dict[str, Any]], paper_id: str, title: str) -> Paper:
    sections: list[Section] = []
    used_section_ids: set[str] = set()
    used_paragraph_ids: set[str] = set()
    for section_index, raw_section in enumerate(payload, start=1):
        section_id = _unique_id(
            _safe_id(raw_section.get("section_number"), f"s{section_index}"),
            used_section_ids,
        )
        paragraphs: list[Paragraph] = []
        for paragraph_index, (raw_paragraph, parent_label) in enumerate(
            _nested_paragraphs(raw_section), start=1
        ):
            paragraph_id = _unique_id(f"{section_id}-p{paragraph_index}", used_paragraph_ids)
            text = str(raw_paragraph.get("text") or "").strip()
            if not text:
                continue
            raw_label = str(raw_paragraph.get("paragraph_number", "")).strip()
            label = " / ".join(part for part in (parent_label, raw_label) if part)
            paragraphs.append(Paragraph(
                id=paragraph_id,
                label=label,
                text=text,
                question=_question(raw_paragraph),
                ordinal=paragraph_index,
            ))
        section_text = "\n\n".join(paragraph.text for paragraph in paragraphs)
        if not section_text:
            section_text = str(raw_section.get("text") or "").strip()
        if not section_text:
            continue
        sections.append(Section(
            id=section_id,
            label=str(raw_section.get("section_name") or raw_section.get("title") or section_id),
            text=section_text,
            paragraphs=paragraphs,
            question=_question(raw_section),
            ordinal=section_index,
        ))
    return Paper(paper_id=paper_id, title=title, sections=sections)


def _from_sectioned_paper(payload: dict[str, Any], paper_id: str, title: str) -> Paper:
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list):
        raise InputError("Canonical paper JSON must contain a sections list")
    flat_paragraphs: dict[str, list[dict[str, Any]]] = {}
    for paragraph in payload.get("paragraphs") or []:
        flat_paragraphs.setdefault(str(paragraph.get("section_id") or ""), []).append(paragraph)

    sections: list[Section] = []
    used_section_ids: set[str] = set()
    used_paragraph_ids: set[str] = set()
    for section_index, raw_section in enumerate(raw_sections, start=1):
        section_id = _unique_id(_safe_id(raw_section.get("id"), f"s{section_index}"), used_section_ids)
        raw_paragraphs = raw_section.get("paragraphs") or flat_paragraphs.get(str(raw_section.get("id") or ""), [])
        paragraphs: list[Paragraph] = []
        for paragraph_index, raw_paragraph in enumerate(raw_paragraphs, start=1):
            paragraph_id = _unique_id(
                _safe_id(raw_paragraph.get("id"), f"{section_id}-p{paragraph_index}"),
                used_paragraph_ids,
            )
            text = str(raw_paragraph.get("text") or "").strip()
            if text:
                paragraphs.append(Paragraph(
                    id=paragraph_id,
                    label=str(raw_paragraph.get("title") or ""),
                    text=text,
                    question=_question(raw_paragraph),
                    ordinal=paragraph_index,
                ))
        section_text = str(raw_section.get("text") or "").strip() or "\n\n".join(p.text for p in paragraphs)
        if section_text:
            sections.append(Section(
                id=section_id,
                label=str(raw_section.get("title") or raw_section.get("label") or section_id),
                text=section_text,
                paragraphs=paragraphs,
                question=_question(raw_section),
                ordinal=section_index,
            ))
    return Paper(paper_id=paper_id, title=title, sections=sections)


def _unique_id(candidate: str, used: set[str]) -> str:
    value = candidate
    suffix = 2
    while value in used:
        value = f"{candidate}-{suffix}"
        suffix += 1
    used.add(value)
    return value


def _question(value: dict[str, Any]) -> str:
    for field in ("question_this_text_answers", "question_this_section_answers", "question", "tag"):
        question = str(value.get(field) or "").strip()
        if question:
            return question
    return ""


def _nested_paragraphs(section: dict[str, Any]) -> Iterator[tuple[dict[str, Any], str]]:
    """Yield a top-level section's paragraphs in document reading order."""

    for paragraph in section.get("paragraphs") or []:
        yield paragraph, ""
    for subsection in section.get("subsections") or []:
        subsection_label = str(subsection.get("section_name") or "").strip()
        for paragraph in subsection.get("paragraphs") or []:
            yield paragraph, subsection_label
