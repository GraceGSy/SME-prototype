"""Construct source-grounded evidence payloads; no model calls or graph mutations."""

from __future__ import annotations

from typing import Any

from .graph import QuestionGraph
from .models import InsertionState, Paper, Paragraph, Section


class Evidence:
    def __init__(self, graph: QuestionGraph):
        self.graph = graph
        self.section_lookup: dict[tuple[str, str], Section] = {}
        self.paragraph_lookup: dict[tuple[str, str], tuple[Section, Paragraph]] = {}
        self.paragraph_positions: dict[tuple[str, str], int] = {}

    def register(self, paper: Paper) -> None:
        for section in paper.sections:
            self.section_lookup[(paper.paper_id, section.id)] = section
            for position, paragraph in enumerate(section.paragraphs):
                self.paragraph_lookup[(paper.paper_id, paragraph.id)] = (section, paragraph)
                self.paragraph_positions[(paper.paper_id, paragraph.id)] = position

    def group_context(self, group_id: str) -> dict[str, Any]:
        data = self.graph.node(group_id)
        return {
            "group_id": group_id,
            "generated_question_metadata": data.get("generated_question", ""),
            "members": [
                self.unit_context(member["paper_id"], member["unit_id"], data["level"])
                for member in data["members"]
            ],
        }

    def unit_context(self, paper_id: str, unit_id: str, level: str) -> dict[str, Any]:
        if level == "section":
            return self.section_context(paper_id, unit_id)
        return self.paragraph_context(paper_id, unit_id)

    def unit_ordinal(self, paper_id: str, unit_id: str, level: str) -> int:
        if level == "section":
            return self.section_lookup[(paper_id, unit_id)].ordinal
        return self.paragraph_lookup[(paper_id, unit_id)][1].ordinal

    def member_metadata(
        self, insertion: InsertionState, unit_id: str, level: str
    ) -> dict[str, Any]:
        if level == "section":
            unit = self.section_lookup[(insertion.paper.paper_id, unit_id)]
            return {
                "unit_kind": unit.kind,
                "parent_unit_id": unit.parent_id,
                "family_id": unit.family_id,
            }
        owner, _ = self.paragraph_lookup[(insertion.paper.paper_id, unit_id)]
        return {
            "unit_kind": "paragraph",
            "parent_unit_id": owner.id,
            "family_id": owner.family_id,
            "owner_group_id": insertion.section_assignments[owner.id],
        }

    def section_context(self, paper_id: str, section_id: str) -> dict[str, Any]:
        section = self.section_lookup[(paper_id, section_id)]
        return {
            "paper_id": paper_id,
            "section_id": section.id,
            "section_label": section.label,
            "unit_kind": section.kind,
            "parent_unit_id": section.parent_id,
            "family_id": section.family_id,
            "ordinal": section.ordinal,
            "generated_question_metadata": section.question,
            "full_text": section.text,
        }

    @staticmethod
    def paper_context(paper: Paper) -> dict[str, str]:
        return {"paper_id": paper.paper_id, "title": paper.title}

    @staticmethod
    def paragraph_evidence(paragraph: Paragraph | None) -> dict[str, Any] | None:
        if paragraph is None:
            return None
        return {
            "paragraph_id": paragraph.id,
            "paragraph_label": paragraph.label,
            "ordinal": paragraph.ordinal,
            "full_text": paragraph.text,
        }

    def paragraph_context(self, paper_id: str, paragraph_id: str) -> dict[str, Any]:
        section, paragraph = self.paragraph_lookup[(paper_id, paragraph_id)]
        return {
            "paper_id": paper_id,
            "paragraph_id": paragraph.id,
            "paragraph_label": paragraph.label,
            "ordinal": paragraph.ordinal,
            "generated_question_metadata": paragraph.question,
            "full_text": paragraph.text,
            "parent_section": {
                "section_id": section.id,
                "section_label": section.label,
                "unit_kind": section.kind,
                "family_id": section.family_id,
                "generated_question_metadata": section.question,
            },
        }

    def paragraph_match_context(
        self,
        paper_id: str,
        paragraph_id: str,
        *,
        selection_id: str | None = None,
    ) -> dict[str, Any]:
        """Return paragraph evidence without leaking focus identity or position."""

        section, paragraph = self.paragraph_lookup[(paper_id, paragraph_id)]
        position = self.paragraph_positions[(paper_id, paragraph_id)]
        context = {
            "previous_paragraph": self.neighbor_text(
                section.paragraphs[position - 1] if position else None
            ),
            "paragraph_under_consideration": {
                "full_text": paragraph.text,
                "generated_question_metadata": paragraph.question,
            },
            "next_paragraph": self.neighbor_text(
                section.paragraphs[position + 1] if position + 1 < len(section.paragraphs) else None
            ),
        }
        if selection_id is not None:
            context["selection_id"] = selection_id
        return context

    def paragraph_group_match_context(
        self,
        group_id: str,
        *,
        selection_id: str | None = None,
    ) -> dict[str, Any]:
        """Return a paragraph node's evidence with only an optional output handle."""

        data = self.graph.node(group_id)
        context = {
            "generated_question_metadata": data.get("generated_question", ""),
            "members": [
                self.paragraph_match_context(member["paper_id"], member["unit_id"])
                for member in data["members"]
            ],
        }
        if selection_id is not None:
            context["selection_id"] = selection_id
        return context

    @staticmethod
    def neighbor_text(paragraph: Paragraph | None) -> dict[str, str] | None:
        if paragraph is None:
            return None
        return {"full_text": paragraph.text}

    def scope_context(self, level: str, parent_id: str | None) -> dict[str, Any]:
        scope = {"level": level, "parent_group_id": parent_id}
        if parent_id:
            scope["parent_group_question_metadata"] = self.graph.node(parent_id).get(
                "generated_question", ""
            )
        return scope
