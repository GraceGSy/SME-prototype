"""Export reciprocal nodes and accepted one-way graph additions."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .graph import QuestionGraph
from .models import Paper


def build_correspondences(
    graph: QuestionGraph,
    events: list[dict[str, Any]],
    papers: list[Paper],
) -> dict[str, Any]:
    """Return shared nodes with one-way additions distinguished from reciprocity."""

    fan_in_events = [
        event for event in events if event["action"] == "paragraph_fan_in_added"
    ]
    fan_in_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fan_in_members: set[tuple[str, str]] = set()
    for event in fan_in_events:
        member = _find_member(graph, event["node_id"], event["paper_id"], event["unit_id"])
        fan_in_members.add((event["paper_id"], event["unit_id"]))
        fan_in_by_node[event["node_id"]].append({
            "paper_index": event["paper_index"],
            "inserted_paper_id": event.get("inserted_paper_id", event["paper_id"]),
            "claiming_paper_id": event["paper_id"],
            "direction": event["direction"],
            "target_id": event["node_id"],
            "reciprocal_unit_id": event["reciprocal_unit_id"],
            "claims": [{
                "source_id": event["unit_id"],
                "sources": [member],
                "status": "accepted_adjacent",
                "redundant": False,
                "attempt_id": event["attempt_id"],
            }],
        })

    rerepresented_members = {
        (member["paper_id"], member["unit_id"])
        for event in events
        if event["action"] == "node_merged"
        and event.get("reason") == "structural_rerepresentation"
        for member in event["members"]
    }
    one_way_members = fan_in_members | rerepresented_members

    labels = _unit_labels(papers)
    levels: dict[str, list[dict[str, Any]]] = {"section": [], "paragraph": []}
    for group_id, data in graph.nodes():
        if len(data["members"]) < 2:
            continue
        cells: dict[str, list[tuple[str, bool]]] = defaultdict(list)
        for member in data["members"]:
            cells[member["paper_id"]].append((
                _label(labels, data["level"], member),
                (member["paper_id"], member["unit_id"]) not in one_way_members,
            ))
        levels[data["level"]].append({
            "group_id": group_id,
            "members": data["members"],
            "fan_in": fan_in_by_node.get(group_id, []),
            "cells": dict(cells),
        })

    return {
        "schema_version": 2,
        "levels": levels,
        "stats": {
            "section_fan_in_groups": 0,
            "section_rerepresented_members": len(rerepresented_members),
            "paragraph_fan_in_groups": sum(
                bool(row["fan_in"]) for row in levels["paragraph"]
            ),
            "paragraph_fan_in_members": len(fan_in_events),
            "section_correspondence_rows": len(levels["section"]),
            "paragraph_correspondence_rows": len(levels["paragraph"]),
        },
    }


def _find_member(
    graph: QuestionGraph,
    node_id: str,
    paper_id: str,
    unit_id: str,
) -> dict[str, Any]:
    return next(
        member
        for member in graph.members(node_id)
        if member["paper_id"] == paper_id and member["unit_id"] == unit_id
    )


def _unit_labels(papers: list[Paper]) -> dict[tuple[str, str, str], str]:
    labels: dict[tuple[str, str, str], str] = {}
    for paper in papers:
        sections = {section.id: section for section in paper.sections}
        family_sizes: dict[str, int] = defaultdict(int)
        for section in paper.sections:
            family_sizes[section.family_id] += 1
        for section in paper.sections:
            if section.kind == "subsection":
                parent = sections[section.parent_id]
                label = f"{parent.label or parent.id} > {section.label or section.id}"
            else:
                label = section.label or section.id
                if family_sizes[section.family_id] > 1:
                    label += " (whole)"
            labels[("section", paper.paper_id, section.id)] = label
            for paragraph in section.paragraphs:
                number = paragraph.label or str(paragraph.ordinal)
                labels[("paragraph", paper.paper_id, paragraph.id)] = f"¶{number}"
    return labels


def _label(
    labels: dict[tuple[str, str, str], str],
    level: str,
    member: dict[str, Any],
) -> str:
    return labels.get(
        (level, member["paper_id"], member["unit_id"]),
        member["unit_id"],
    )
