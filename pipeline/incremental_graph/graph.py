"""Deterministic graph mutations, classification, serialization, and replay."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Iterable

import networkx as nx

from .journal import RevisionJournal
from .models import Classification, Level


def stable_id(prefix: str, *parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:12]}"


class QuestionGraph:
    """A thin domain wrapper around a NetworkX directed multigraph."""

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
    ) -> str:
        prefix = "section-group" if level == "section" else "paragraph-group"
        node_id = stable_id(prefix, parent_id or "root", paper_id, member_id)
        if node_id in self.graph:
            raise ValueError(f"Question-group ID collision: {node_id}")
        member = {"paper_id": paper_id, "unit_id": member_id}
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

    def add_member(self, node_id: str, member_id: str, paper_id: str, paper_index: int) -> None:
        members = self.graph.nodes[node_id]["members"]
        member = {"paper_id": paper_id, "unit_id": member_id}
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

    def add_alignable_edge(
        self,
        source: str,
        target: str,
        *,
        attempt_id: str,
        paper_index: int,
    ) -> str:
        if self.graph.nodes[source]["level"] != self.graph.nodes[target]["level"]:
            raise ValueError("Alignable-difference edges cannot cross graph levels")
        if self.graph.nodes[source].get("parent_id") != self.graph.nodes[target].get("parent_id"):
            raise ValueError("Paragraph alignments cannot cross section question groups")
        edge_id = stable_id("edge", source, target, attempt_id)
        self.graph.add_edge(
            source,
            target,
            key=edge_id,
            edge_id=edge_id,
            kind="alignable_difference",
            attempt_id=attempt_id,
            created_paper_index=paper_index,
        )
        self.journal.event(
            "edge_created",
            paper_index=paper_index,
            edge_id=edge_id,
            source=source,
            target=target,
            kind="alignable_difference",
            attempt_id=attempt_id,
        )
        return edge_id

    def classify(self, level: Level, paper_index: int) -> dict[str, Classification]:
        classifications: dict[str, Classification] = {}
        for node_id, _ in self.nodes(level):
            data = self.graph.nodes[node_id]
            coverage = len({member["paper_id"] for member in data["members"]})
            denominator = self._classification_denominator(data)
            degree = self.graph.in_degree(node_id) + self.graph.out_degree(node_id)
            if denominator >= 2 and coverage > denominator / 2:
                classification: Classification = "common_structure"
            elif coverage >= 2 or degree > 0:
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

    def set_question(self, node_id: str, question: str, paper_index: int, attempt_id: str) -> None:
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
        )

    def members(self, node_id: str) -> list[dict[str, str]]:
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
            "events": self.journal.events,
        }

    def _classification_denominator(self, node: dict[str, Any]) -> int:
        if node["level"] == "section":
            return len(self.paper_order)
        parent_id = node.get("parent_id")
        if not parent_id or parent_id not in self.graph:
            return 0
        return len({member["paper_id"] for member in self.graph.nodes[parent_id]["members"]})

    def _layouts(self) -> dict[str, dict[str, dict[str, float]]]:
        layouts = {"section": _layout(self.graph, self.group_ids("section"))}
        parents: dict[str, list[str]] = defaultdict(list)
        for node_id, data in self.nodes("paragraph"):
            parents[data["parent_id"]].append(node_id)
        for parent_id, node_ids in sorted(parents.items()):
            layouts[f"paragraph:{parent_id}"] = _layout(self.graph, node_ids)
        return layouts


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
                attempt_id=event["attempt_id"],
            )
        elif action == "classification_changed":
            graph.nodes[event["node_id"]]["classification"] = event["classification"]
        elif action == "question_generated":
            graph.nodes[event["node_id"]]["generated_question"] = event["question"]
    return graph


def _layout(graph: nx.MultiDiGraph, node_ids: list[str]) -> dict[str, dict[str, float]]:
    if not node_ids:
        return {}
    if len(node_ids) == 1:
        return {node_ids[0]: {"x": 0.5, "y": 0.5}}
    subgraph = graph.subgraph(node_ids).to_undirected()
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


def _json_attrs(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in sorted(value)}
