"""Construct source-grounded evidence payloads; no model calls or graph mutations."""

from __future__ import annotations

from typing import Any

from .evidence_encoding import source_address
from .graph import RoleGraph
from .models import InsertionState, Paper, Paragraph, Section


class Evidence:
    def __init__(self, graph: RoleGraph):
        self.graph = graph
        self.section_lookup: dict[tuple[str, str], Section] = {}
        self.paragraph_lookup: dict[tuple[str, str], tuple[Section, Paragraph]] = {}
        self.paragraph_positions: dict[tuple[str, str], int] = {}
        self.paper_keys: dict[str, str] = {}
        self.paper_titles: dict[str, str] = {}
        self.section_positions: dict[tuple[str, str], int] = {}
        self.section_spans: dict[tuple[str, str], list[tuple[int, int, int]]] = {}
        self.source_ordinals: dict[str, int] = {}
        self.section_numbers: dict[str, str] = {}  # Positional IDs, not printed numbers.

    def register(self, paper: Paper) -> None:
        self.paper_keys[paper.paper_id] = f"paper-{len(self.paper_keys) + 1}"
        key = self.paper_keys[paper.paper_id]
        self.paper_titles[key] = paper.title
        for index, section in enumerate(paper.sections, 1):
            # Printed numbers can be missing (Abstract) or absent from a whole paper, so
            # IDs use document position; the printed number appears in the heading.
            self.section_numbers[f"{key}:{index}"] = str(index)
            self.section_positions[paper.paper_id, section.id] = index
            self.section_lookup[(paper.paper_id, section.id)] = section
            self.source_ordinals[self.address(key, index)] = len(self.section_lookup)
            for position, paragraph in enumerate(section.paragraphs):
                self.paragraph_lookup[(paper.paper_id, paragraph.id)] = (section, paragraph)
                self.source_ordinals[self.address(key, index, position + 1)] = len(
                    self.paragraph_lookup
                )
                self.paragraph_positions[(paper.paper_id, paragraph.id)] = position

        for section in paper.sections:
            index = self.section_positions[paper.paper_id, section.id]
            texts = [p.text for p in section.paragraphs]
            self.section_spans[paper.paper_id, section.id] = (
                [(index, n, len(text)) for n, text in enumerate(texts, 1)]
                if texts and "\n\n".join(texts) == section.text
                else [(index, 0, len(section.text))]
            )

    def address(self, paper, sec, pos=0):
        return source_address(paper, sec, pos, numbers=self.section_numbers)

    def group_context(self, group_id: str) -> dict[str, Any]:
        data = self.graph.node(group_id)
        return {
            "group_id": group_id,
            "role_statement": data.get("role_statement", ""),
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
            "paper_key": self.paper_keys[paper_id],
            "section_id": section.id,
            "section_label": section.label,
            "unit_kind": section.kind,
            "parent_unit_id": section.parent_id,
            "family_id": section.family_id,
            "ordinal": section.ordinal,
            "role_statement": section.role_statement,
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
            "paper_key": self.paper_keys[paper_id],
            "paragraph_id": paragraph.id,
            "paragraph_label": paragraph.label,
            "ordinal": paragraph.ordinal,
            "role_statement": paragraph.role_statement,
            "full_text": paragraph.text,
            "parent_section": {
                "section_id": section.id,
                "section_label": section.label,
                "unit_kind": section.kind,
                "family_id": section.family_id,
                "role_statement": section.role_statement,
            },
        }

    def paragraph_match_context(
        self,
        paper_id: str,
        paragraph_id: str,
        *,
        selection_id: str | None = None,
    ) -> dict[str, Any]:
        """Keep source coordinates so overlapping windows can share one passage."""

        section, paragraph = self.paragraph_lookup[(paper_id, paragraph_id)]
        position = self.paragraph_positions[(paper_id, paragraph_id)]
        context = {
            "paper_key": self.paper_keys[paper_id],
            "source_position": [self.section_positions[paper_id, section.id], position + 1],
            "previous_paragraph": self.neighbor_text(
                section.paragraphs[position - 1] if position else None
            ),
            "paragraph_under_consideration": {
                "full_text": paragraph.text,
                "role_statement": paragraph.role_statement,
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
            "role_statement": data.get("role_statement", ""),
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

    def node_match_context(self, group_id: str, *, selectable: bool = False) -> dict[str, Any]:
        """Use the same role evidence for both directions of singleton realignment."""
        if self.graph.node(group_id)["level"] == "paragraph":
            return self.paragraph_group_match_context(
                group_id, selection_id=group_id if selectable else None
            )
        context = self.structural_match_group(group_id)
        context.pop("group_id")
        if selectable:
            context["selection_id"] = group_id
        return context

    def match_unit_context(
        self, paper_id: str, unit_id: str, level: str, *, selectable: bool = False
    ) -> dict[str, Any]:
        if level == "paragraph":
            return self.paragraph_match_context(
                paper_id, unit_id, selection_id=unit_id if selectable else None
            )
        return {
            **self.section_context(paper_id, unit_id),
            "source_section": self.section_positions[paper_id, unit_id],
            "source_spans": self.section_spans[paper_id, unit_id],
        }

    def structural_match_group(self, group_id: str) -> dict[str, Any]:
        group = self.group_context(group_id)
        for member in group["members"]:
            member["source_section"] = self.section_positions[
                member["paper_id"], member["section_id"]
            ]
            member["source_spans"] = self.section_spans[member["paper_id"], member["section_id"]]
        return group

    def match_group_context(self, group_id: str, *, selectable: bool = False) -> dict[str, Any]:
        if self.graph.node(group_id)["level"] == "paragraph":
            return self.paragraph_group_match_context(
                group_id, selection_id=group_id if selectable else None
            )
        return self.structural_match_group(group_id)

    def jev_annotations(
        self, context: dict, shared_root_id: str | None, *, candidate_papers: bool = True
    ) -> dict:
        """Show each node's latest paper in full and its earlier members' own units.

        A request therefore carries one complete paper per participating node, not
        every paper that has ever joined a node. Without ``candidate_papers`` only
        the focus's paper is complete; candidates keep their own member units.
        """
        nodes = [context["focus"], *context["candidates"]]
        node_units = [node.get("members", [node]) for node in nodes]
        full_papers = {
            max((u["paper_key"] for u in units), key=_paper_number)
            for units in (node_units if candidate_papers else node_units[:1])
        }
        locations = [[_unit_location(u) for u in units] for units in node_units]
        member_sections = {loc[:2] for node in locations for loc in node}
        node_members = {
            frozenset(self.address(*loc) for loc in node) for node in locations if len(node) > 1
        }
        sections, paragraphs, metadata = {}, [], {}
        section_level = context["scope"]["level"] == "section"
        for (paper_id, sid), section in self.section_lookup.items():
            paper, sec = self.paper_keys[paper_id], self.section_positions[paper_id, sid]
            full = paper in full_papers
            if not full and (paper, sec) not in member_sections:
                continue
            addr = self.address(paper, sec)
            if section_level:
                sections[addr] = (
                    self.paper_titles[paper],
                    f"{section.number} {section.label}".strip(),
                    section.role_statement,
                    section.text,
                )
                continue
            metadata[addr] = (f"{section.number} {section.label}".strip(), section.role_statement)
            if full:
                for i, para in enumerate(section.paragraphs, 1):
                    metadata[self.address(paper, sec, i)] = ("", para.role_statement)
                    paragraphs.append((paper, sec, i, para.text))

        # Only the decision's own nodes, plus the structural scope for paragraph work.
        scope_parent = context["scope"].get("parent_group_id")
        groups = {}
        for level in ("section",) if section_level else ("section", "paragraph"):
            for gid, node in self.graph.nodes(level):
                if gid == shared_root_id or len(node["members"]) < 2:
                    continue
                members = {}
                for m in node["members"]:
                    key = m["paper_id"], m["unit_id"]
                    if level == "paragraph":
                        section = self.paragraph_lookup[key][0]
                        sec = self.section_positions[key[0], section.id]
                        pos = self.paragraph_positions[key] + 1
                    else:
                        sec, pos = self.section_positions[key], 0
                    members[self.address(self.paper_keys[key[0]], sec, pos)] = m.get(
                        "membership_role"
                    )
                if gid != scope_parent and frozenset(members) not in node_members:
                    continue
                # The label and off-screen roster depend on source order, not on
                # whether members were appended, merged or restored from events.
                ordered = sorted(members, key=self.source_ordinals.__getitem__)
                label = f"{level[0].upper()}{self.source_ordinals[ordered[0]]}"
                groups[label] = {
                    "members": {addr: members[addr] for addr in ordered},
                    "role_statement": node.get("role_statement", ""),
                }
        annotations = {"groups": groups, "numbers": dict(self.section_numbers)}
        if section_level:
            return {**annotations, "sections": sections}
        return {**annotations, "units": metadata, "paragraphs": paragraphs}

    def latest_paper_context(self, group_id: str) -> dict[str, Any]:
        """The full paper of a node's latest member; member passages appear only once."""
        data = self.graph.node(group_id)
        members = data["members"]
        paper_id = max(
            (m["paper_id"] for m in members), key=lambda p: _paper_number(self.paper_keys[p])
        )
        own = {m["unit_id"] for m in members if m["paper_id"] == paper_id}
        sections = []
        for (pid, _), section in self.section_lookup.items():
            if pid != paper_id:
                continue
            if data["level"] == "section" and section.id in own:
                sections.append({"section_label": section.label, "group_member": True})
                continue
            sections.append(
                {
                    "section_label": section.label,
                    "paragraphs": [
                        {"group_member": True} if p.id in own else p.text
                        for p in section.paragraphs
                    ]
                    or [section.text],
                }
            )
        return {
            "paper_key": self.paper_keys[paper_id],
            "title": self.paper_titles[self.paper_keys[paper_id]],
            "sections": sections,
        }

    def scope_context(self, level: str, parent_id: str | None) -> dict[str, Any]:
        scope = {"level": level, "parent_group_id": parent_id}
        if parent_id:
            scope["parent_group_role_statement"] = self.graph.node(parent_id).get(
                "role_statement", ""
            )
        return scope


def _paper_number(paper_key: str) -> int:
    return int(paper_key.removeprefix("paper-"))


def _unit_location(unit: dict[str, Any]) -> tuple[str, int, int]:
    if "source_position" in unit:
        return unit["paper_key"], *unit["source_position"]
    return unit["paper_key"], unit["source_section"], 0
