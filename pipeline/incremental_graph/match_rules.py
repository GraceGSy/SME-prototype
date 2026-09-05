"""Pure reciprocal-core and immediate-neighbor acceptance rules."""

from typing import Any

from .models import MatchBatch


def reciprocal_matches(batch: MatchBatch) -> dict[str, str]:
    reciprocal: dict[str, str] = {}
    for unit_id, forward in batch.forward.items():
        if not forward.target_id:
            continue
        reverse = batch.reverse.get(forward.target_id)
        if reverse and reverse.target_id == unit_id:
            reciprocal[unit_id] = forward.target_id
    return reciprocal


def adjacent_paragraph_fan_in(
    batch: MatchBatch,
    reciprocal: dict[str, str],
    ordinals: dict[str, int],
) -> dict[str, str]:
    """Attach only one-way paragraphs immediately beside a reciprocal anchor."""

    anchor_by_group = {group_id: unit_id for unit_id, group_id in reciprocal.items()}
    accepted: dict[str, str] = {}
    for unit_id, forward in batch.forward.items():
        selected_group = forward.target_id
        anchor_id = anchor_by_group.get(selected_group or "")
        if unit_id in reciprocal or anchor_id is None:
            continue
        ordinal = ordinals[unit_id]
        anchor_ordinal = ordinals[anchor_id]
        if abs(ordinal - anchor_ordinal) == 1 and selected_group is not None:
            accepted[unit_id] = selected_group
    return accepted


def adjacent_core_anchors(
    source_members: list[dict[str, Any]],
    target_members: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]] | None:
    target_members = [
        member for member in target_members if member.get("membership_role") != "fan_in"
    ]
    anchors = {}
    for member in source_members:
        candidates = [
            target
            for target in target_members
            if target["paper_id"] == member["paper_id"]
            and target.get("owner_group_id") == member.get("owner_group_id")
            and abs(target["ordinal"] - member["ordinal"]) == 1
        ]
        if not candidates:
            return None
        anchors[(member["paper_id"], member["unit_id"])] = min(
            candidates,
            key=lambda item: (item["ordinal"], item["unit_id"]),
        )
    return anchors
