"""Lossless wire representation: share text, never collapse candidate identities."""

from typing import Any

from ..prompts import request_prompts

EVIDENCE_PROMPTS = request_prompts("evidence")


def encode_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    texts: dict[str, str] = {}
    references: dict[str, str] = {}

    def visit(value):
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key != "full_text":
                result[key] = visit(item)
                continue
            if not isinstance(item, str):
                raise TypeError("Evidence full_text must be a string")
            ids = []
            for text in item.split("\n\n"):
                if text not in references:
                    reference = f"text-{len(texts) + 1:04d}"
                    references[text] = reference
                    texts[reference] = text
                ids.append(references[text])
            result["full_text_refs"] = ids
        return result

    encoded = visit(evidence)
    return {
        "text_reference_contract": (
            EVIDENCE_PROMPTS["text_reference_contract"]
            + EVIDENCE_PROMPTS["candidate_handle_suffix"]
        ),
        "source_texts": texts,
        **encoded,
    }
