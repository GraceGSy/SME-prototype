"""Deterministic graph mutations, classification, serialization, and replay."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

import networkx as nx

from .journal import RevisionJournal
from .models import Classification, Level


def stable_id(prefix: str, *parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:12]}"


class QuestionGraph:
    """Own deterministic question-group state and replay events."""

    def __init__(self, journal: RevisionJournal):
        self.graph = nx.MultiDiGraph()
        self.journal = journal
        self.paper_order: list[str] = []

    def add_paper(self, paper_id: str, title: str, paper_index: int) -> None:
        self.paper_order.append(paper_id)
        self.journal.event("paper_added", paper_index=paper_index, paper_id=paper_id, title=title)

    def group_ids(self, level: Level, parent_id: str | None = None) -> list[str]:
        return sorted(
            node_id
            for node_id, data in self.graph.nodes(data=True)
            if data["level"] == level and data.get("parent_id") == parent_id
        )

    def create_group(
        self,
        *,
        level: Level,
        parent_id: str | None,
        member_id: str,
        paper_id: str,
        paper_index: int,
        ordinal: int,
        unit_kind: str = "section",
        parent_unit_id: str | None = None,
        family_id: str | None = None,
        owner_group_id: str | None = None,
    ) -> str:
        prefix = "section-group" if level == "section" else "paragraph-group"
        node_id = stable_id(prefix, parent_id or "root", paper_id, member_id)
        if node_id in self.graph:
            raise ValueError(f"Question-group ID collision: {node_id}")
        member = _member(
            paper_id, member_id, ordinal, unit_kind, parent_unit_id, family_id, owner_group_id
        )
        self.graph.add_node(
            node_id,
            level=level,
            parent_id=parent_id,
            members=[member],
            generated_question="",
            classification=None,
            created_paper_index=paper_index,
        )
        self.journal.event(
            "node_created",
            paper_index=paper_index,
            node_id=node_id,
            level=level,
            parent_id=parent_id,
            member=member,
        )
        return node_id

    def add_member(
        self,
        node_id: str,
        member_id: str,
        paper_id: str,
        paper_index: int,
        ordinal: int,
        unit_kind: str = "section",
        parent_unit_id: str | None = None,
        family_id: str | None = None,
        owner_group_id: str | None = None,
    ) -> None:
        members = self.graph.nodes[node_id]["members"]
        if any(existing["paper_id"] == paper_id for existing in members):
            raise ValueError(f"Question group {node_id} already contains a member from {paper_id}")
        member = _member(
            paper_id, member_id, ordinal, unit_kind, parent_unit_id, family_id, owner_group_id
        )
        if member in members:
            return
        members.append(member)
        members.sort(key=lambda item: (self.paper_order.index(item["paper_id"]), item["unit_id"]))
        self.journal.event(
            "member_added",
            paper_index=paper_index,
            node_id=node_id,
            member=member,
        )

    def add_hierarchy_edge(
        self,
        parent_group_id: str,
        child_group_id: str,
        *,
        paper_id: str,
        paper_index: int,
    ) -> None:
        edge_id = stable_id("contains", paper_id, parent_group_id, child_group_id)
        if self.graph.has_edge(parent_group_id, child_group_id, edge_id):
            return
        self.graph.add_edge(
            parent_group_id,
            child_group_id,
            key=edge_id,
            edge_id=edge_id,
            kind="contains",
            paper_id=paper_id,
            created_paper_index=paper_index,
        )
        self.journal.event(
            "edge_created",
            paper_index=paper_index,
            edge_id=edge_id,
            source=parent_group_id,
            target=child_group_id,
            kind="contains",
            paper_id=paper_id,
        )

    def structural_family(self, node_ids: list[str]) -> set[str]:
        """Return structural groups connected by paper-specific containment edges."""

        structural = nx.Graph()
        structural.add_nodes_from(self.group_ids("section"))
        structural.add_edges_from(
            (source, target)
            for source, target, data in self.graph.edges(data=True)
            if data.get("kind") == "contains"
        )
        family: set[str] = set()
        for node_id in node_ids:
            if node_id in structural:
                family.update(nx.node_connected_component(structural, node_id))
        return family

    def paragraph_groups_for_family(self, structural_group_ids: set[str], paper_id: str) -> list[str]:
        return sorted(
            node_id
            for node_id, data in self.nodes("paragraph")
            if not any(member["paper_id"] == paper_id for member in data["members"])
            and any(member.get("owner_group_id") in structural_group_ids for member in data["members"])
        )

    def classify(self, level: Level, paper_index: int) -> dict[str, Classification]:
        classifications: dict[str, Classification] = {}
        for node_id, _ in self.nodes(level):
            data = self.graph.nodes[node_id]
            coverage = len({member["paper_id"] for member in data["members"]})
            denominator = len(self.paper_order)
            if denominator and coverage * 2 >= denominator:
                classification: Classification = "common_structure"
            elif len(data["members"]) > 1:
                classification = "alignable_difference"
            else:
                classification = "non_alignable_difference"
            classifications[node_id] = classification
            previous = data.get("classification")
            data["classification"] = classification
            if previous != classification:
                self.journal.event(
                    "classification_changed",
                    paper_index=paper_index,
                    node_id=node_id,
                    level=level,
                    previous=previous,
                    classification=classification,
                    paper_coverage=coverage,
                    eligible_papers=denominator,
                )
        return classifications

    def set_question(
        self,
        node_id: str,
        question: str,
        paper_index: int,
        attempt_id: str | None,
        *,
        source: str = "model",
    ) -> None:
        normalized = question.strip()
        previous = self.graph.nodes[node_id].get("generated_question", "")
        self.graph.nodes[node_id]["generated_question"] = normalized
        self.journal.event(
            "question_generated",
            paper_index=paper_index,
            node_id=node_id,
            previous=previous,
            question=normalized,
            attempt_id=attempt_id,
            source=source,
        )

    def members(self, node_id: str) -> list[dict[str, Any]]:
        return list(self.graph.nodes[node_id]["members"])

    def nodes(self, level: Level | None = None) -> Iterable[tuple[str, dict[str, Any]]]:
        for node_id, data in sorted(self.graph.nodes(data=True)):
            if level is None or data["level"] == level:
                yield node_id, data

    def serialize(self) -> dict[str, Any]:
        nodes = [{"node_id": node_id, **_json_attrs(data)} for node_id, data in self.nodes()]
        edges = [
            {"source": source, "target": target, "key": key, **_json_attrs(data)}
            for source, target, key, data in sorted(self.graph.edges(keys=True, data=True))
        ]
        return {"schema_version": 1, "paper_order": self.paper_order, "nodes": nodes, "edges": edges}

    def graph_hash(self) -> str:
        payload = json.dumps(self.serialize(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def replay_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "mode": "incremental_graph_replay",
            "paper_order": self.paper_order,
            "final_graph_hash": self.graph_hash(),
            "layouts": self._layouts(),
            "hierarchy_layouts": {"section": _hierarchy_layout(self.graph, self.group_ids("section"))},
            "events": self.journal.events,
        }

    def _layouts(self) -> dict[str, dict[str, dict[str, float]]]:
        return {
            "section": _layout(self.group_ids("section")),
            "paragraph": _layout([node_id for node_id, _ in self.nodes("paragraph")]),
        }


def graph_from_events(events: list[dict[str, Any]]) -> nx.MultiDiGraph:
    """Rebuild graph topology and visible metadata from replay events."""

    graph = nx.MultiDiGraph()
    for event in events:
        action = event["action"]
        if action == "node_created":
            graph.add_node(
                event["node_id"],
                level=event["level"],
                parent_id=event.get("parent_id"),
                members=[event["member"]],
                generated_question="",
                classification=None,
            )
        elif action == "member_added":
            graph.nodes[event["node_id"]]["members"].append(event["member"])
        elif action == "edge_created":
            graph.add_edge(
                event["source"],
                event["target"],
                key=event["edge_id"],
                edge_id=event["edge_id"],
                kind=event["kind"],
                attempt_id=event.get("attempt_id"),
                paper_id=event.get("paper_id"),
            )
        elif action == "classification_changed":
            graph.nodes[event["node_id"]]["classification"] = event["classification"]
        elif action == "question_generated":
            graph.nodes[event["node_id"]]["generated_question"] = event["question"]
    return graph


def _layout(node_ids: list[str]) -> dict[str, dict[str, float]]:
    if not node_ids:
        return {}
    if len(node_ids) == 1:
        return {node_ids[0]: {"x": 0.5, "y": 0.5}}
    subgraph = nx.Graph()
    subgraph.add_nodes_from(node_ids)
    positions = nx.spring_layout(subgraph, seed=42, iterations=100)
    xs = [float(point[0]) for point in positions.values()]
    ys = [float(point[1]) for point in positions.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = max(max_x - min_x, 1e-9)
    height = max(max_y - min_y, 1e-9)
    return {
        node_id: {
            "x": round(0.08 + 0.84 * (float(positions[node_id][0]) - min_x) / width, 6),
            "y": round(0.08 + 0.84 * (float(positions[node_id][1]) - min_y) / height, 6),
        }
        for node_id in sorted(node_ids)
    }


def _hierarchy_layout(graph: nx.MultiDiGraph, node_ids: list[str]) -> dict[str, dict[str, float]]:
    hierarchy = nx.DiGraph()
    hierarchy.add_nodes_from(node_ids)
    hierarchy.add_edges_from(
        (source, target)
        for source, target, data in graph.edges(data=True)
        if data.get("kind") == "contains" and source in hierarchy and target in hierarchy
    )
    if not node_ids:
        return {}
    depths = {node_id: 0 for node_id in node_ids}
    for node_id in nx.topological_sort(hierarchy) if nx.is_directed_acyclic_graph(hierarchy) else node_ids:
        for child in hierarchy.successors(node_id):
            depths[child] = max(depths[child], depths[node_id] + 1)
    max_depth = max(depths.values(), default=0)
    positions: dict[str, dict[str, float]] = {}
    for depth in range(max_depth + 1):
        row = sorted(
            (node_id for node_id in node_ids if depths[node_id] == depth),
            key=lambda node_id: (
                sum(member["ordinal"] for member in graph.nodes[node_id]["members"])
                / len(graph.nodes[node_id]["members"]),
                node_id,
            ),
        )
        for index, node_id in enumerate(row, start=1):
            positions[node_id] = {
                "x": round(index / (len(row) + 1), 6),
                "y": round((depth + 1) / (max_depth + 2), 6),
            }
    return positions


def _member(
    paper_id: str,
    unit_id: str,
    ordinal: int,
    unit_kind: str,
    parent_unit_id: str | None,
    family_id: str | None,
    owner_group_id: str | None,
) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "unit_id": unit_id,
        "ordinal": ordinal,
        "unit_kind": unit_kind,
        "parent_unit_id": parent_unit_id,
        "family_id": family_id,
        "owner_group_id": owner_group_id,
    }


def _json_attrs(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in sorted(value)}
