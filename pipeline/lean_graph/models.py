"""Plain dataclasses for the lean incremental question-group pipeline.

No pydantic: this pipeline has exactly one accepted paper input shape (see
input_data.py) and no config/request/response objects that would benefit from schema
validation the way pipeline 2's did -- every deterministic operation here is plain
Python over these structures. Serialization is hand-written (to_json/from_json on
Graph) rather than relying on a validation library's own dump/parse.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

Level = Literal["section", "paragraph"]
Classification = Literal["common_structure", "alignable_difference", "non_alignable_difference"]


@dataclass
class Paragraph:
    id: str
    label: str
    text: str
    question: str = ""


@dataclass
class Section:
    id: str
    label: str
    text: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    question: str = ""


@dataclass
class Paper:
    paper_id: str
    title: str
    sections: list[Section]


@dataclass
class Member:
    paper_id: str
    unit_id: str


@dataclass
class Node:
    node_id: str
    level: Level
    parent_id: Optional[str]
    members: list[Member] = field(default_factory=list)
    question: str = ""
    classification: Optional[Classification] = None


@dataclass
class Edge:
    source: str
    target: str
    kind: str = "alignable_difference"


@dataclass
class Graph:
    paper_order: list[str] = field(default_factory=list)
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "paper_order": self.paper_order,
            "nodes": {node_id: asdict(node) for node_id, node in self.nodes.items()},
            "edges": [asdict(edge) for edge in self.edges],
        }

    @classmethod
    def from_json(cls, payload: dict) -> "Graph":
        nodes: dict[str, Node] = {}
        for node_id, raw in payload.get("nodes", {}).items():
            members = [Member(**m) for m in raw.get("members", [])]
            nodes[node_id] = Node(
                node_id=raw["node_id"],
                level=raw["level"],
                parent_id=raw.get("parent_id"),
                members=members,
                question=raw.get("question", ""),
                classification=raw.get("classification"),
            )
        edges = [Edge(**e) for e in payload.get("edges", [])]
        return cls(paper_order=payload.get("paper_order", []), nodes=nodes, edges=edges)
