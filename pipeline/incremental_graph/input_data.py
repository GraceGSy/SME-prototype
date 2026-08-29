"""Normalize extracted paper JSON into the pipeline's stable input model."""

from __future__ import annotations

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
    structural_ordinal = 0
    for section_index, raw_section in enumerate(payload, start=1):
        section_id = _unique_id(
            _safe_id(raw_section.get("section_number"), f"s{section_index}"),
            used_section_ids,
        )
        paragraph_ordinal = 0

        def build_paragraphs(owner_id: str, raw_paragraphs: list[dict[str, Any]]) -> list[Paragraph]:
            nonlocal paragraph_ordinal
            built: list[Paragraph] = []
            for raw_paragraph in raw_paragraphs:
                text = str(raw_paragraph.get("text") or "").strip()
                if not text:
                    continue
                paragraph_ordinal += 1
                paragraph_id = _unique_id(f"{owner_id}-p{len(built) + 1}", used_paragraph_ids)
                built.append(Paragraph(
                    id=paragraph_id,
                    label=str(raw_paragraph.get("paragraph_number", "")).strip(),
                    text=text,
                    question=_question(raw_paragraph),
                    ordinal=paragraph_ordinal,
                ))
            return built

        direct_paragraphs = build_paragraphs(section_id, raw_section.get("paragraphs") or [])
        children: list[Section] = []
        for subsection_index, raw_subsection in enumerate(raw_section.get("subsections") or [], start=1):
            subsection_key = (
                raw_subsection.get("section_number")
                or raw_subsection.get("section_name")
                or f"sub{subsection_index}"
            )
            subsection_id = _unique_id(
                f"{section_id}-sub-{_safe_id(subsection_key, f'sub{subsection_index}')}",
                used_section_ids,
            )
            subsection_paragraphs = build_paragraphs(
                subsection_id, raw_subsection.get("paragraphs") or []
            )
            subsection_text = "\n\n".join(paragraph.text for paragraph in subsection_paragraphs)
            if not subsection_text:
                continue
            children.append(Section(
                id=subsection_id,
                label=str(raw_subsection.get("section_name") or subsection_id),
                text=subsection_text,
                paragraphs=subsection_paragraphs,
                question=_question(raw_subsection),
                ordinal=1,
                kind="subsection",
                parent_id=section_id,
                family_id=section_id,
            ))

        section_text = "\n\n".join(
            paragraph.text
            for paragraph in [*direct_paragraphs, *(p for child in children for p in child.paragraphs)]
        ) or str(raw_section.get("text") or "").strip()
        if not section_text and not children:
            continue
        structural_ordinal += 1
        section_ordinal = structural_ordinal
        sections.append(Section(
            id=section_id,
            label=str(raw_section.get("section_name") or raw_section.get("title") or section_id),
            text=section_text,
            paragraphs=direct_paragraphs,
            question=_question(raw_section),
            ordinal=section_ordinal,
            kind="section",
            family_id=section_id,
        ))
        for offset, child in enumerate(children, start=1):
            child.ordinal = section_ordinal + offset
        structural_ordinal = section_ordinal + len(children)
        sections.extend(children)
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
                kind=str(raw_section.get("kind") or "section"),
                parent_id=raw_section.get("parent_id"),
                family_id=str(
                    raw_section.get("family_id") or raw_section.get("parent_id") or section_id
                ),
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
