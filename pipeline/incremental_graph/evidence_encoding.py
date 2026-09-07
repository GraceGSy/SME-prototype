"""Lossless wire representation: share text, never collapse candidate identities."""

from typing import Any


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
            "Every full_text_refs list is the complete original text: look up each ID "
            "in source_texts in list order and join with two newline characters. "
            "Read all referenced text. References share storage only, not candidate identity. "
            "Return only the candidate handle required by the matching instructions, never a text ID."
        ),
        "source_texts": texts,
        **encoded,
    }
