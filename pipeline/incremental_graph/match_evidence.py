"""Validate quotations against the selected centers, never neighboring context."""

import json
from collections.abc import Iterator
from typing import Any


class JudgmentError(RuntimeError):
    """A model response violates the requested contract."""


class EvidenceValidationError(JudgmentError):
    """The selected correspondence lacks correctly attributed source quotations."""


def _centers(value: dict[str, Any], path: str) -> Iterator[tuple[str, dict[str, Any]]]:
    if "members" in value:
        for index, member in enumerate(value["members"]):
            yield from _centers(member, f"{path}.members[{index}]")
    else:
        yield path, value


def _center_text(value: dict[str, Any]) -> str:
    center = value.get("paragraph_under_consideration", value)
    text = center["full_text"]
    if not isinstance(text, str):
        raise ValueError("Matching source full_text must be a string")
    return text


def center_texts(value: dict[str, Any]) -> list[str]:
    """Preserve member order so quotation array positions identify exact sources."""
    return [_center_text(member) for _, member in _centers(value, "")]


def candidate_handle(value: dict[str, Any]) -> str:
    if "selection_id" in value:
        return value["selection_id"]
    if "group_id" in value:
        return value["group_id"]
    return value["section_id"]


def _source_name(path: str, value: dict[str, Any]) -> str:
    label = value.get("section_label")
    return f"{path} ({json.dumps(label, ensure_ascii=False)})" if label else path


def _text_locations(context: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Inspect only supplied evidence; neighbors are locations, never valid centers."""
    roots = [("focus", context["focus"])] + [
        (f"candidate {candidate_handle(candidate)!r}", candidate)
        for candidate in context["candidates"]
    ]
    for root, value in roots:
        for path, member in _centers(value, root):
            center_path = (
                f"{path}.paragraph_under_consideration"
                if "paragraph_under_consideration" in member
                else path
            )
            yield _source_name(center_path, member), _center_text(member)
            for neighbor in ("previous_paragraph", "next_paragraph"):
                if member.get(neighbor) is not None:
                    yield f"{path}.{neighbor} (context only)", member[neighbor]["full_text"]


def _attribution_feedback(
    context: dict[str, Any], chosen: str, side: str, index: int, quote: str, value: dict[str, Any]
) -> str:
    root = "focus" if side == "focus" else f"candidate {chosen!r}"
    path, member = list(_centers(value, root))[index]
    expected = _source_name(path, member)
    # One exact location is enough to explain the error without echoing the pool.
    location = next((path for path, text in _text_locations(context) if quote in text), None)
    occurrence = (
        f"An exact occurrence was found in {location}."
        if location is not None
        else "No exact occurrence was found in the supplied source text, including neighbors."
    )
    return (
        f"evidence.{side}[{index}]: quote {json.dumps(quote, ensure_ascii=False)} is not an exact "
        f"substring of its required center, {expected}. "
        f"{occurrence} Copy a short exact quotation from the required center's full_text "
        "or resolve its existing full_text_refs; do not borrow from another unit or neighbor. "
        "A quotation's presence elsewhere does not establish a role match."
    )


def validate_evidence(context: dict[str, Any], chosen: str | None, evidence: Any) -> None:
    if not isinstance(evidence, dict) or set(evidence) != {"focus", "target"}:
        raise EvidenceValidationError("evidence requires exactly focus and target quotation arrays")
    if chosen is None:
        if evidence != {"focus": [], "target": []}:
            raise EvidenceValidationError("An abstention requires empty evidence arrays")
        return
    candidates = [c for c in context["candidates"] if candidate_handle(c) == chosen]
    if len(candidates) != 1:
        raise ValueError("Matching request must identify exactly one selected candidate")
    for side, value in (("focus", context["focus"]), ("target", candidates[0])):
        texts = center_texts(value)
        quotes = evidence[side]
        if not texts or not isinstance(quotes, list) or len(quotes) != len(texts):
            raise EvidenceValidationError(
                f"evidence.{side} requires one quote per center, in member order"
            )
        for index, (quote, text) in enumerate(zip(quotes, texts, strict=True)):
            if not isinstance(quote, str) or not quote.strip() or len(quote) > 240:
                raise EvidenceValidationError(
                    f"evidence.{side}[{index}] requires a nonempty quote of at most 240 characters"
                )
            if quote not in text:
                raise EvidenceValidationError(
                    _attribution_feedback(context, chosen, side, index, quote, value)
                )
