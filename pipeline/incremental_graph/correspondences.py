"""Deterministically combine reciprocal matches and directional fan-in evidence."""

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
    """Return confirmed groups with any many-to-one directional claims attached."""

    matches = [
        event
        for event in events
        if event["action"] == "match_recorded" and event.get("chosen_id") is not None
    ]
    decisions = {
        (event["paper_index"], event["level"], event["direction"], event["focus_id"]): event
        for event in matches
    }
    grouped: dict[
        tuple[int, str, str, str, str],
        list[tuple[dict[str, Any], list[dict[str, Any]]]],
    ] = defaultdict(list)
    for event in matches:
        sources = _source_members(
            graph,
            event["paper_index"],
            event["level"],
            event["direction"],
            event["focus_id"],
        )
        for claiming_paper_id in sorted({source["paper_id"] for source in sources}):
            paper_sources = [
                source for source in sources
                if source["paper_id"] == claiming_paper_id
            ]
            grouped[
                (
                    event["paper_index"],
                    event["level"],
                    event["direction"],
                    event["chosen_id"],
                    claiming_paper_id,
                )
            ].append((event, paper_sources))

    fan_in_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (
        paper_index,
        level,
        direction,
        target_id,
        claiming_paper_id,
    ), claims in grouped.items():
        unique_claims = {
            claim["focus_id"]: (claim, sources)
            for claim, sources in claims
        }
        if len(unique_claims) < 2:
            continue
        target_group_id = _target_group_id(graph, paper_index, level, direction, target_id)
        if target_group_id is None:
            continue
        reverse_direction = "group_to_new" if direction == "new_to_group" else "new_to_group"
        reverse = decisions.get((paper_index, level, reverse_direction, target_id))
        normalized_claims = []
        for source_id, (claim, sources) in sorted(unique_claims.items()):
            status = (
                "confirmed"
                if reverse and reverse.get("chosen_id") == source_id
                else "one_directional"
            )
            normalized_claims.append({
                "source_id": source_id,
                "sources": sources,
                "status": status,
                "redundant": (
                    status == "one_directional"
                    and level == "section"
                    and _covered_by_target_family(graph, target_group_id, sources)
                ),
                "attempt_id": claim["attempt_id"],
            })
        fan_in_by_group[target_group_id].append({
            "paper_index": paper_index,
            "inserted_paper_id": graph.paper_order[paper_index - 1],
            "claiming_paper_id": claiming_paper_id,
            "direction": direction,
            "target_id": target_id,
            "claims": normalized_claims,
        })

    labels = _unit_labels(papers)
    levels: dict[str, list[dict[str, Any]]] = {"section": [], "paragraph": []}
    for group_id, data in graph.nodes():
        fan_in = sorted(
            fan_in_by_group.get(group_id, []),
            key=lambda item: (item["paper_index"], item["direction"], item["target_id"]),
        )
        if len(data["members"]) < 2 and not fan_in:
            continue
        raw_cells: dict[str, list[tuple[int, str, bool]]] = defaultdict(list)
        is_bidirectional = len(data["members"]) > 1
        for member in data["members"]:
            raw_cells[member["paper_id"]].append(
                (member["ordinal"], _label(labels, data["level"], member), is_bidirectional)
            )
        for item in fan_in:
            for claim in item["claims"]:
                if claim["status"] != "one_directional" or claim["redundant"]:
                    continue
                for source in claim["sources"]:
                    entry = (source["ordinal"], _label(labels, data["level"], source), False)
                    if entry not in raw_cells[source["paper_id"]]:
                        raw_cells[source["paper_id"]].append(entry)
        if data["level"] == "paragraph":
            for entries in raw_cells.values():
                entries.sort(key=lambda entry: entry[0])
        cells = {
            paper_id: [(label, confirmed) for _, label, confirmed in entries]
            for paper_id, entries in raw_cells.items()
        }
        levels[data["level"]].append({
            "group_id": group_id,
            "members": data["members"],
            "fan_in": fan_in,
            "cells": cells,
        })

    return {
        "schema_version": 1,
        "levels": levels,
        "stats": {
            f"{level}_fan_in_groups": sum(len(row["fan_in"]) for row in rows)
            for level, rows in levels.items()
        } | {
            f"{level}_correspondence_rows": len(rows)
            for level, rows in levels.items()
        },
    }


def _target_group_id(
    graph: QuestionGraph,
    paper_index: int,
    level: str,
    direction: str,
    target_id: str,
) -> str | None:
    if direction == "new_to_group":
        return target_id if target_id in graph.graph else None

    paper_id = graph.paper_order[paper_index - 1]
    for group_id, data in graph.nodes(level):
        if any(
            member["paper_id"] == paper_id and member["unit_id"] == target_id
            for member in data["members"]
        ):
            return group_id
    return None


def _source_members(
    graph: QuestionGraph,
    paper_index: int,
    level: str,
    direction: str,
    source_id: str,
) -> list[dict[str, Any]]:
    if direction == "group_to_new":
        return graph.members(source_id)

    paper_id = graph.paper_order[paper_index - 1]
    for _, data in graph.nodes(level):
        for member in data["members"]:
            if member["paper_id"] == paper_id and member["unit_id"] == source_id:
                return [member]
    return []


def _covered_by_target_family(
    graph: QuestionGraph,
    target_group_id: str,
    sources: list[dict[str, Any]],
) -> bool:
    target_families = {
        (member["paper_id"], member.get("family_id"))
        for member in graph.members(target_group_id)
    }
    return any(
        (source["paper_id"], source.get("family_id")) in target_families
        for source in sources
    )


def _unit_labels(papers: list[Paper]) -> dict[tuple[str, str, str], str]:
    labels: dict[tuple[str, str, str], str] = {}
    for paper in papers:
        sections = {section.id: section for section in paper.sections}
        family_sizes = defaultdict(int)
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
