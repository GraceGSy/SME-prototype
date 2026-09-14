"""Explain singleton outcomes from saved events, without new model judgments."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..files import write_json
from .graph import graph_from_events
from .match_rules import recovery_admission


def _key(member: dict[str, Any]) -> tuple[str, str]:
    return member["paper_id"], member["unit_id"]


def _decision_history(events: list[dict[str, Any]]) -> dict:
    members = {}
    paper_ids = {}
    history = defaultdict(
        lambda: {"exposed_attempt_ids": [], "judgments": [], "selected_by_attempt_ids": []}
    )
    for event in events:
        action = event["action"]
        if action == "paper_added":
            paper_ids[event["paper_index"]] = event["paper_id"]
        elif action == "node_created":
            members[event["node_id"]] = [_key(event["member"])]
        elif action == "member_added":
            members[event["node_id"]].append(_key(event["member"]))
        elif action == "node_merged":
            members[event["target_node_id"]].extend(members.pop(event["source_node_id"]))
        elif action == "match_recorded" and event["level"] == "paragraph":
            direction = event["direction"]
            if direction not in {
                "new_to_group",
                "group_to_new",
                "singleton_to_group",
                "group_to_singleton",
            }:
                raise ValueError(f"Unsupported paragraph matching direction: {direction}")

            def resolve(handle: str, *, focus: bool) -> list[tuple[str, str]]:
                is_unit = (focus and direction == "new_to_group") or (
                    not focus and direction == "group_to_new"
                )
                return (
                    [(event.get("unit_paper_id", paper_ids[event["paper_index"]]), handle)]
                    if is_unit
                    else members[handle]
                )

            # Resolve at judgment time: later group additions were not in this call.
            focus = resolve(event["source_id"], focus=True)
            candidates = {
                key for handle in event["candidate_ids"] for key in resolve(handle, focus=False)
            }
            attempt_id = event["attempt_id"]
            for key in set(focus) | candidates:
                history[key]["exposed_attempt_ids"].append(attempt_id)
            for key in focus:
                history[key]["judgments"].append(
                    {
                        "attempt_id": attempt_id,
                        "direction": direction,
                        "target_id": event["target_id"],
                    }
                )
            if event["target_id"] is not None:
                for key in resolve(event["target_id"], focus=False):
                    history[key]["selected_by_attempt_ids"].append(attempt_id)
    return history


def build_singleton_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify recorded outcomes; do not infer semantic uniqueness or missed matches."""
    graph = graph_from_events(events)
    history = _decision_history(events)
    paragraphs = {
        node_id: data for node_id, data in graph.nodes(data=True) if data["level"] == "paragraph"
    }
    by_scope = defaultdict(list)
    for node_id, data in paragraphs.items():
        by_scope[data.get("parent_id")].append((node_id, data))
    rows = []
    for node_id, data in sorted(paragraphs.items()):
        if len({member["paper_id"] for member in data["members"]}) > 1:
            continue
        for member in data["members"]:
            evidence = history[_key(member)]
            if not evidence["exposed_attempt_ids"]:
                reason = "never_compared"
            elif evidence["selected_by_attempt_ids"] or any(
                j["target_id"] is not None for j in evidence["judgments"]
            ):
                reason = "selected_without_acceptance"
            elif evidence["judgments"]:
                reason = "model_abstained"
            else:
                reason = "candidate_only"
            scope = by_scope[data.get("parent_id")]
            established = [(key, value) for key, value in scope if len(value["members"]) > 1]
            eligible = [key for key, value in established if recovery_admission(data, value)]
            if len(data["members"]) != 1:
                recovery_status = "source_is_not_single_member"
                eligible = []
            elif not established:
                recovery_status = "no_established_group_in_scope"
            elif not eligible:
                recovery_status = "source_paper_already_in_groups"
            else:
                recovery_status = "eligible_established_group"
            parent = graph.nodes[data["parent_id"]] if data.get("parent_id") else None
            rows.append(
                {
                    "paper_id": member["paper_id"],
                    "paragraph_id": member["unit_id"],
                    "group_id": node_id,
                    "parent_id": data.get("parent_id"),
                    "parent_is_shared": parent is not None
                    and len({m["paper_id"] for m in parent["members"]}) > 1,
                    "reason": reason,
                    **evidence,
                    "recovery": {
                        "status": recovery_status,
                        "eligible_group_ids": sorted(eligible),
                        "other_paper_singleton_peers": sum(
                            len(value["members"]) == 1
                            and value["members"][0]["paper_id"] != member["paper_id"]
                            for _, value in scope
                        ),
                    },
                }
            )
    rows.sort(key=lambda row: (row["paper_id"], row["paragraph_id"]))
    return {
        "schema_version": 1,
        "paragraph_count": sum(len(data["members"]) for data in paragraphs.values()),
        "singleton_paragraph_count": len(rows),
        "reason_counts": dict(sorted(Counter(row["reason"] for row in rows).items())),
        "recovery_status_counts": dict(
            sorted(Counter(row["recovery"]["status"] for row in rows).items())
        ),
        "limitations": [
            "Recorded selection and abstention are not proof of semantic correctness or uniqueness.",
            "Recovery eligibility describes the final snapshot, not whether every candidate was tested.",
            "Recovery eligibility uses current code; historical runs may have used different rules.",
            "Singleton peers share a final scope; this count does not claim they were never compared.",
        ],
        "paragraphs": rows,
    }


def write_singleton_report(events: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    report = build_singleton_report(events)
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json(output_dir / "singletons.json", report)
    return report
