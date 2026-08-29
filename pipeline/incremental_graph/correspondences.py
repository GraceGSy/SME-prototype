"""Deterministically combine reciprocal matches and directional fan-in evidence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .graph import QuestionGraph


def build_correspondences(
    graph: QuestionGraph,
    events: list[dict[str, Any]],
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
    grouped: dict[tuple[int, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in matches:
        grouped[
            (event["paper_index"], event["level"], event["direction"], event["chosen_id"])
        ].append(event)

    fan_in_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (paper_index, level, direction, target_id), claims in grouped.items():
        unique_claims = {claim["focus_id"]: claim for claim in claims}
        if len(unique_claims) < 2:
            continue
        target_group_id = _target_group_id(graph, paper_index, level, direction, target_id)
        if target_group_id is None:
            continue
        reverse_direction = "group_to_new" if direction == "new_to_group" else "new_to_group"
        reverse = decisions.get((paper_index, level, reverse_direction, target_id))
        normalized_claims = [
            {
                "source_id": source_id,
                "status": (
                    "confirmed"
                    if reverse and reverse.get("chosen_id") == source_id
                    else "one_directional"
                ),
                "attempt_id": claim["attempt_id"],
            }
            for source_id, claim in sorted(unique_claims.items())
        ]
        fan_in_by_group[target_group_id].append({
            "paper_index": paper_index,
            "inserted_paper_id": graph.paper_order[paper_index - 1],
            "direction": direction,
            "target_id": target_id,
            "claims": normalized_claims,
        })

    levels: dict[str, list[dict[str, Any]]] = {"section": [], "paragraph": []}
    for group_id, data in graph.nodes():
        fan_in = sorted(
            fan_in_by_group.get(group_id, []),
            key=lambda item: (item["paper_index"], item["direction"], item["target_id"]),
        )
        if len(data["members"]) < 2 and not fan_in:
            continue
        levels[data["level"]].append({
            "group_id": group_id,
            "members": data["members"],
            "fan_in": fan_in,
        })

    return {
        "schema_version": 1,
        "levels": levels,
        "stats": {
            f"{level}_fan_in_groups": sum(len(row["fan_in"]) for row in rows)
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
