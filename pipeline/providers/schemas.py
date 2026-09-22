"""Project canonical schemas onto API subsets; always validate the original locally."""

from typing import Any


def without_constraints(schema: dict[str, Any], excluded: set[str]) -> dict[str, Any]:
    result = {}
    for key, value in schema.items():
        if key in excluded:
            continue
        if key in {"properties", "$defs", "definitions"}:
            value = {name: without_constraints(child, excluded) for name, child in value.items()}
        elif key in {"items", "additionalProperties"} and isinstance(value, dict):
            value = without_constraints(value, excluded)
        elif key in {"anyOf", "allOf", "oneOf", "prefixItems"}:
            value = [without_constraints(child, excluded) for child in value]
        result[key] = value
    return result
