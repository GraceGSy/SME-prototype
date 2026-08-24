"""Normalize extracted paper JSON into the pipeline's stable input model."""

from __future__ import annotations

import json
import re
from pathlib import Path
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
        return _from_pseudo_sections(payload, paper_id, title)
    if isinstance(payload, dict):
        return _from_sectioned_paper(payload, paper_id, title)
    raise InputError(f"Paper JSON {path} must be an object or a list of sections")


def _safe_id(value: Any, fallback: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return compact or fallback


def _from_pseudo_sections(payload: list[dict[str, Any]], paper_id: str, title: str) -> Paper:
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
                paragraphs.append(Paragraph(id=paragraph_id, label=str(raw_paragraph.get("title") or ""), text=text))
        section_text = str(raw_section.get("text") or "").strip() or "\n\n".join(p.text for p in paragraphs)
        if section_text:
            sections.append(Section(
                id=section_id,
                label=str(raw_section.get("title") or raw_section.get("label") or section_id),
                text=section_text,
                paragraphs=paragraphs,
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
