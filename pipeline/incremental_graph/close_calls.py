"""Close Jev rankings: re-ask among the near-tied options, then hold if still close.

A ranking is close when another option's probability is within ``margin`` of the top
one. The runner re-asks Jev with only those options; if the narrower ranking is still
close, the source gets no pick. A held new section starts on its own, so singleton
recovery tries it again after each later paper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..files import write_json
from .graph import RoleGraph


def close_options(probabilities: dict[str, float], margin: float) -> list[str]:
    """Options within ``margin`` of the top probability, most likely first."""
    top = max(probabilities.values())
    # Rounding keeps 0.55 vs 0.45 (a 0.10 gap) out of a 0.10 margin despite float error.
    return sorted(
        (option for option, p in probabilities.items() if round(top - p, 9) < margin),
        key=lambda option: (-probabilities[option], option),
    )


def _status(graph: RoleGraph, level: str, paper_id: str, unit_id: str) -> dict[str, Any]:
    for node_id, data in graph.nodes(level):
        if any(m["paper_id"] == paper_id and m["unit_id"] == unit_id for m in data["members"]):
            return {
                "node_id": node_id,
                "member_count": len(data["members"]),
                "still_alone": len(data["members"]) == 1,
            }
    return {"node_id": None, "member_count": 0, "still_alone": None}


def write_close_call_report(
    events: list[dict[str, Any]], graph: RoleGraph, reports_dir: Path
) -> dict[str, Any]:
    """List every close ranking, its outcome, and where held units ended up."""
    calls = []
    for event in events:
        if event["action"] != "close_call":
            continue
        row = {k: v for k, v in event.items() if k not in {"action"}}
        if event["outcome"] == "held" and event.get("unit_id"):
            row["final"] = _status(graph, event["level"], event["paper_id"], event["unit_id"])
        calls.append(row)
    held = [c for c in calls if c["outcome"] == "held"]
    report = {
        "schema_version": 1,
        "close_calls": len(calls),
        "reasked": sum("reask" in c for c in calls),
        "resolved_by_reask": sum(c["outcome"] == "resolved" for c in calls),
        "held": len(held),
        "held_still_alone": sum(bool(c.get("final", {}).get("still_alone")) for c in held),
        "calls": calls,
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    write_json(reports_dir / "close-calls.json", report)
    return report
