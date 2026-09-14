"""Validate quotations against the selected centers, never neighboring context."""

from typing import Any


class JudgmentError(RuntimeError):
    """A model response violates the requested contract."""


class EvidenceValidationError(JudgmentError):
    """The selected correspondence lacks correctly attributed source quotations."""


def center_texts(value: dict[str, Any]) -> list[str]:
    """Preserve member order so quotation array positions identify exact sources."""
    if "members" in value:
        return [text for member in value["members"] for text in center_texts(member)]
    center = value.get("paragraph_under_consideration", value)
    text = center["full_text"]
    if not isinstance(text, str):
        raise ValueError("Matching source full_text must be a string")
    return [text]


def candidate_handle(value: dict[str, Any]) -> str:
    if "selection_id" in value:
        return value["selection_id"]
    if "group_id" in value:
        return value["group_id"]
    return value["section_id"]


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
                    f"evidence.{side}[{index}] is not an exact substring of its center; do not quote neighbors or another member"
                )
