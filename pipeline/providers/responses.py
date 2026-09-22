"""Shared response storage and strict validation; no provider response parsing."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator

from ..files import write_json
from .contracts import SkillCallPolicy, StructuredOutputValidationError


def validate_value(value: Any, schema: dict[str, Any], response_id: str) -> Any:
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        raise StructuredOutputValidationError(response_id, errors) from errors[0]
    return value


def parse_json(text: str, schema: dict[str, Any], response_id: str) -> Any:
    return validate_value(json.loads(text), schema, response_id)


def save_response(
    directory: Path | None,
    *,
    provider: str,
    response: dict[str, Any],
    usage: dict[str, Any],
    policy: SkillCallPolicy,
    schema: dict[str, Any],
    messages: list[dict[str, Any]],
    input_tokens: int,
    api_schema: dict[str, Any] | None = None,
) -> None:
    """Call before budget, completion, and JSON checks to retain paid responses."""
    if directory is None:
        return
    record = {
        "provider": provider,
        "response": response,
        "usage": usage,
        "policy": policy.as_dict(),
        "schema": schema,
        "messages": messages,
        "request_text_characters": sum(
            len(block.get("text", ""))
            for message in messages
            for block in message["content"]
            if isinstance(block, dict)
        ),
        "input_usage_tokens": input_tokens,
    }
    if api_schema is not None:
        record["api_schema"] = api_schema
    write_json(directory / f"{uuid4().hex}.json", record)


def usage_record(
    response_id: str, usage: dict[str, Any], session: dict[str, int]
) -> dict[str, Any]:
    """Retain the original billing fields and identify the one paid API request."""
    return {
        **usage,
        "request_count": 1,
        "responses": [{"response_id": response_id, "usage": usage}],
        "session": dict(session),
    }


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
