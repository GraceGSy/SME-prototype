"""Canonical document contract shared by extraction, matching, and graphing.

Documents stay in the nested HCI JSON shape. Stable unit IDs are derived from
array positions so model-generated labels and questions never become identity.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal


QUESTION_FIELD = "question_this_text_answers"
SECTIONS_VIEW = "sections"
NESTED_VIEW = "sections_and_subsections"
CandidateView = Literal["sections", "sections_and_subsections"]

_PARAGRAPH_FIELDS = {"paragraph_number", "text", QUESTION_FIELD}
_SUBSECTION_FIELDS = {"section_name", "section_number", "paragraphs", QUESTION_FIELD}
_SECTION_FIELDS = {*_SUBSECTION_FIELDS, "subsections"}


@dataclass(frozen=True)
class StructuralUnit:
    """One section or subsection plus its deterministic identity and evidence."""

    unit_id: str
    unit_type: Literal["section", "subsection"]
    name: str
    number: str | None
    parent_unit_id: str | None
    parent_name: str | None
    source: dict[str, Any]
    own_paragraphs: list[dict[str, Any]]
    evidence: list[dict[str, str]]

    @property
    def question(self) -> str | None:
        return self.source.get(QUESTION_FIELD)

    def candidate(self) -> dict[str, Any]:
        """Return the one candidate shape used by every document matcher."""

        return {
            "unit_id": self.unit_id,
            "unit_type": self.unit_type,
            "name": self.name,
            "number": self.number,
            "parent_unit_id": self.parent_unit_id,
            "parent_name": self.parent_name,
            "paragraphs": copy.deepcopy(self.evidence),
            QUESTION_FIELD: self.question,
        }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    """Atomically write readable UTF-8 JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def strip_questions(value: Any) -> Any:
    """Remove question metadata without changing document content or order."""

    if isinstance(value, dict):
        return {
            key: strip_questions(child)
            for key, child in value.items()
            if key != QUESTION_FIELD
        }
    if isinstance(value, list):
        return [strip_questions(child) for child in value]
    return value


def flatten_to_single_section(
    document: list[dict[str, Any]],
    section_name: str,
) -> list[dict[str, Any]]:
    """Copy every paragraph into one ordered top-level section."""

    validate_document(document)
    paragraphs = []
    for unit in iter_structural_units(document):
        for paragraph in unit.own_paragraphs:
            paragraphs.append({
                "paragraph_number": len(paragraphs),
                "text": paragraph["text"],
            })
    if not paragraphs:
        raise ValueError("A flattened document must contain at least one paragraph")
    return [{
        "section_name": section_name,
        "section_number": None,
        "paragraphs": paragraphs,
        "subsections": [],
    }]


def section_unit_id(section_index: int) -> str:
    return f"s{section_index + 1:04d}"


def subsection_unit_id(section_index: int, subsection_index: int) -> str:
    return f"{section_unit_id(section_index)}.ss{subsection_index + 1:04d}"


def paragraph_unit_id(owner_unit_id: str, paragraph_index: int) -> str:
    return f"{owner_unit_id}.p{paragraph_index + 1:04d}"


def _paragraph_evidence(
    owner_unit_id: str,
    paragraphs: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "paragraph_id": paragraph_unit_id(owner_unit_id, index),
            "text": paragraph["text"],
        }
        for index, paragraph in enumerate(paragraphs)
    ]


def iter_structural_units(document: list[dict[str, Any]]) -> Iterator[StructuralUnit]:
    """Yield sections and their subsections once, in document order."""

    for section_index, section in enumerate(document):
        section_id = section_unit_id(section_index)
        section_evidence = _paragraph_evidence(section_id, section["paragraphs"])
        for subsection_index, subsection in enumerate(section["subsections"]):
            subsection_id = subsection_unit_id(section_index, subsection_index)
            section_evidence.extend(
                _paragraph_evidence(subsection_id, subsection["paragraphs"])
            )
        yield StructuralUnit(
            unit_id=section_id,
            unit_type="section",
            name=section["section_name"],
            number=section.get("section_number"),
            parent_unit_id=None,
            parent_name=None,
            source=section,
            own_paragraphs=section["paragraphs"],
            evidence=section_evidence,
        )
        for subsection_index, subsection in enumerate(section["subsections"]):
            subsection_id = subsection_unit_id(section_index, subsection_index)
            yield StructuralUnit(
                unit_id=subsection_id,
                unit_type="subsection",
                name=subsection["section_name"],
                number=subsection.get("section_number"),
                parent_unit_id=section_id,
                parent_name=section["section_name"],
                source=subsection,
                own_paragraphs=subsection["paragraphs"],
                evidence=_paragraph_evidence(subsection_id, subsection["paragraphs"]),
            )


def matching_candidates(
    document: list[dict[str, Any]],
    view: CandidateView,
) -> list[dict[str, Any]]:
    """Project a canonical document into the configured matching view."""

    if view not in {SECTIONS_VIEW, NESTED_VIEW}:
        raise ValueError(f"Unknown candidate view: {view}")
    return [
        unit.candidate()
        for unit in iter_structural_units(document)
        if view == NESTED_VIEW or unit.unit_type == "section"
    ]


def validate_document(
    document: Any,
    *,
    require_structural_questions: bool = False,
    require_paragraph_questions: bool = False,
) -> None:
    """Validate the sole nested document schema used by the active pipeline."""

    if not isinstance(document, list) or not document:
        raise ValueError("A document must be a non-empty JSON array")
    for section_index, section in enumerate(document):
        _validate_unit(
            section,
            f"section {section_index}",
            allowed_fields=_SECTION_FIELDS,
        )
        subsections = section.get("subsections")
        if not isinstance(subsections, list):
            raise ValueError(f"section {section_index} subsections must be an array")
        for subsection_index, subsection in enumerate(subsections):
            _validate_unit(
                subsection,
                f"section {section_index} subsection {subsection_index}",
                allowed_fields=_SUBSECTION_FIELDS,
            )

    if require_structural_questions:
        for unit in iter_structural_units(document):
            _validate_question(unit.source, bool(unit.evidence), unit.unit_id)
    if require_paragraph_questions:
        for unit in iter_structural_units(document):
            for paragraph_index, paragraph in enumerate(unit.own_paragraphs):
                _validate_question(
                    paragraph,
                    True,
                    paragraph_unit_id(unit.unit_id, paragraph_index),
                )


def _validate_unit(
    unit: Any,
    label: str,
    *,
    allowed_fields: set[str],
) -> None:
    if not isinstance(unit, dict):
        raise ValueError(f"{label} must be an object")
    unexpected = set(unit) - allowed_fields
    if unexpected:
        raise ValueError(f"{label} has unsupported fields: {sorted(unexpected)}")
    if not isinstance(unit.get("section_name"), str) or not unit["section_name"].strip():
        raise ValueError(f"{label} needs a non-empty section_name")
    if unit.get("section_number") is not None and not isinstance(unit["section_number"], str):
        raise ValueError(f"{label} section_number must be a string or null")
    paragraphs = unit.get("paragraphs")
    if not isinstance(paragraphs, list):
        raise ValueError(f"{label} paragraphs must be an array")
    for paragraph_index, paragraph in enumerate(paragraphs):
        _validate_paragraph(
            paragraph,
            f"{label} paragraph {paragraph_index}",
            paragraph_index,
        )
    if QUESTION_FIELD in unit:
        question = unit[QUESTION_FIELD]
        if question is not None and (not isinstance(question, str) or not question.strip()):
            raise ValueError(f"{label} has an invalid {QUESTION_FIELD}")


def _validate_paragraph(
    paragraph: Any,
    label: str,
    expected_number: int,
) -> None:
    if not isinstance(paragraph, dict):
        raise ValueError(f"{label} must be an object")
    unexpected = set(paragraph) - _PARAGRAPH_FIELDS
    if unexpected:
        raise ValueError(f"{label} has unsupported fields: {sorted(unexpected)}")
    if paragraph.get("paragraph_number") != expected_number:
        raise ValueError(f"{label} number must be zero-indexed and contiguous")
    if not isinstance(paragraph.get("text"), str) or not paragraph["text"].strip():
        raise ValueError(f"{label} needs non-empty text")
    if QUESTION_FIELD in paragraph:
        _validate_question(paragraph, True, label)


def _validate_question(
    value: dict[str, Any],
    has_evidence: bool,
    label: str,
) -> None:
    if QUESTION_FIELD not in value:
        raise ValueError(f"{label} is missing {QUESTION_FIELD}")
    question = value[QUESTION_FIELD]
    if has_evidence and (not isinstance(question, str) or not question.strip()):
        raise ValueError(f"{label} needs a non-empty {QUESTION_FIELD}")
    if not has_evidence and question is not None:
        raise ValueError(f"{label} must use null {QUESTION_FIELD} without evidence")
