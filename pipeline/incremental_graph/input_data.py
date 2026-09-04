"""Load canonical nested document JSON into the incremental graph model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..document import (
    QUESTION_FIELD,
    iter_structural_units,
    paragraph_unit_id,
    read_json,
    validate_document,
)
from .models import Granularity, Paper, PaperManifest, Paragraph, Section


class InputError(ValueError):
    """Raised when canonical document data cannot be loaded safely."""


def load_manifest(path: Path) -> tuple[PaperManifest, list[Paper]]:
    path = path.resolve()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        manifest = PaperManifest.model_validate(payload)
        papers = [
            load_paper(
                (path.parent / entry.file).resolve(),
                entry.paper_id,
                entry.title,
                manifest.max_granularity,
            )
            for entry in manifest.papers
        ]
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise InputError(f"Could not load paper manifest {path}: {error}") from error
    return manifest, papers


def load_paper(
    path: Path,
    paper_id: str,
    title: str,
    max_granularity: Granularity = "section",
) -> Paper:
    try:
        payload = read_json(path)
        validate_document(payload)
        return _from_canonical_document(payload, paper_id, title, max_granularity)
    except (OSError, ValueError) as error:
        raise InputError(f"Could not load canonical document {path}: {error}") from error


def _from_canonical_document(
    document: list[dict[str, Any]],
    paper_id: str,
    title: str,
    max_granularity: Granularity,
) -> Paper:
    if max_granularity == "paragraph":
        if len(document) != 1 or document[0]["subsections"]:
            raise ValueError(
                "paragraph granularity requires exactly one top-level section and no subsections"
            )
    if max_granularity != "subsection":
        return _from_section_documents(document, paper_id, title)

    sections: list[Section] = []
    paragraph_ordinals: dict[str, int] = {}
    structural_ordinal = 0

    for unit in iter_structural_units(document):
        if not unit.evidence:
            continue
        family_id = unit.parent_unit_id or unit.unit_id
        paragraphs: list[Paragraph] = []
        for paragraph_index, raw_paragraph in enumerate(unit.own_paragraphs):
            paragraph_ordinals[family_id] = paragraph_ordinals.get(family_id, 0) + 1
            paragraphs.append(Paragraph(
                id=paragraph_unit_id(unit.unit_id, paragraph_index),
                label=str(raw_paragraph["paragraph_number"]),
                text=raw_paragraph["text"].strip(),
                question=_question(raw_paragraph),
                ordinal=paragraph_ordinals[family_id],
            ))

        structural_ordinal += 1
        sections.append(Section(
            id=unit.unit_id,
            label=unit.name,
            text="\n\n".join(paragraph["text"] for paragraph in unit.evidence),
            paragraphs=paragraphs,
            question=_question(unit.source),
            ordinal=structural_ordinal,
            kind=unit.unit_type,
            parent_id=unit.parent_unit_id,
            family_id=family_id,
        ))
    return Paper(paper_id=paper_id, title=title, sections=sections)


def _from_section_documents(
    document: list[dict[str, Any]],
    paper_id: str,
    title: str,
) -> Paper:
    """Load top-level sections and keep descendant paragraphs in source order."""

    units = list(iter_structural_units(document))
    sections = []
    for section_unit in (unit for unit in units if unit.unit_type == "section"):
        family = [
            unit
            for unit in units
            if unit.unit_id == section_unit.unit_id
            or unit.parent_unit_id == section_unit.unit_id
        ]
        paragraphs = []
        for unit in family:
            for paragraph_index, raw_paragraph in enumerate(unit.own_paragraphs):
                paragraphs.append(Paragraph(
                    id=paragraph_unit_id(unit.unit_id, paragraph_index),
                    label=str(raw_paragraph["paragraph_number"]),
                    text=raw_paragraph["text"].strip(),
                    question=_question(raw_paragraph),
                    ordinal=len(paragraphs) + 1,
                ))
        sections.append(Section(
            id=section_unit.unit_id,
            label=section_unit.name,
            text="\n\n".join(paragraph["text"] for paragraph in section_unit.evidence),
            paragraphs=paragraphs,
            question=_question(section_unit.source),
            ordinal=len(sections) + 1,
            kind="section",
            family_id=section_unit.unit_id,
        ))
    return Paper(paper_id=paper_id, title=title, sections=sections)


def _question(value: dict[str, Any]) -> str:
    question = value.get(QUESTION_FIELD)
    return question.strip() if isinstance(question, str) else ""
