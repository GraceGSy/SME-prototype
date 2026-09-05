"""Canonical document contract shared by extraction, matching, and graphing.

Documents stay in the nested HCI JSON shape. Stable unit IDs are derived from
array positions so model-generated labels and questions never become identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Literal

QUESTION_FIELD = "question_this_text_answers"

_PARAGRAPH_FIELDS = {"paragraph_number", "text", QUESTION_FIELD}
_SUBSECTION_FIELDS = {"section_name", "section_number", "paragraphs", QUESTION_FIELD}
_SECTION_FIELDS = {*_SUBSECTION_FIELDS, "subsections"}


def content_schema() -> dict[str, Any]:
    paragraph = {
        "type": "object",
        "properties": {
            "paragraph_number": {"type": "integer", "minimum": 0},
            "text": {"type": "string", "minLength": 1},
        },
        "required": ["paragraph_number", "text"],
        "additionalProperties": False,
    }
    subsection = {
        "type": "object",
        "properties": {
            "section_name": {"type": "string", "minLength": 1},
            "section_number": {"type": ["string", "null"]},
            "paragraphs": {"type": "array", "items": paragraph},
        },
        "required": ["section_name", "section_number", "paragraphs"],
        "additionalProperties": False,
    }
    return {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "properties": {
                **subsection["properties"],
                "subsections": {"type": "array", "items": subsection},
            },
            "required": [*subsection["required"], "subsections"],
            "additionalProperties": False,
        },
    }


@dataclass(frozen=True)
class StructuralUnit:
    """One section or subsection plus its deterministic identity and evidence."""

    unit_id: str
    unit_type: Literal["section", "subsection"]
    name: str
    parent_unit_id: str | None
    source: dict[str, Any]
    own_paragraphs: list[dict[str, Any]]
    evidence: list[dict[str, str]]


def strip_questions(value: Any) -> Any:
    """Remove question metadata without changing document content or order."""

    if isinstance(value, dict):
        return {
            key: strip_questions(child) for key, child in value.items() if key != QUESTION_FIELD
        }
    if isinstance(value, list):
        return [strip_questions(child) for child in value]
    return value


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
            section_evidence.extend(_paragraph_evidence(subsection_id, subsection["paragraphs"]))
        yield StructuralUnit(
            unit_id=section_id,
            unit_type="section",
            name=section["section_name"],
            parent_unit_id=None,
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
                parent_unit_id=section_id,
                source=subsection,
                own_paragraphs=subsection["paragraphs"],
                evidence=_paragraph_evidence(subsection_id, subsection["paragraphs"]),
            )


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
    if (
        type(paragraph.get("paragraph_number")) is not int
        or paragraph["paragraph_number"] != expected_number
    ):
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
