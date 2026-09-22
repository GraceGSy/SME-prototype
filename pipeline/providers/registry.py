"""Credentials and account-scoped registration state shared by provider adapters."""

import hashlib
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError


def load_api_key(repo_root: Path, variable: str) -> str:
    """Load the API key without copying it into pipeline output or logs."""
    key = os.environ.get(variable)
    if key:
        return key

    for directory in [repo_root, *repo_root.parents]:
        env_path = directory / ".env"
        if not env_path.exists():
            continue
        values: dict[str, str] = {}
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip("\"'")
        key = values.get(variable)
        if key:
            os.environ[variable] = key
            return key
    raise RuntimeError(f"No {variable} was found in the environment or an ancestor .env")


def _credential_registry(
    state: dict[str, Any],
    api_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the current registry only; legacy caches must be discarded explicitly."""

    skill_record = {
        "type": "object",
        "additionalProperties": False,
        "required": ["skill_id", "version", "source_sha256"],
        "properties": {
            "skill_id": {"type": "string", "minLength": 1},
            "version": {"type": "string", "minLength": 1},
            "source_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        },
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "accounts"],
        "properties": {
            "schema_version": {"const": 1},
            "accounts": {
                "type": "object",
                "propertyNames": {"pattern": "^[a-f0-9]{64}$"},
                "additionalProperties": {"type": "object", "additionalProperties": skill_record},
            },
        },
    }
    try:
        Draft202012Validator(schema).validate(state)
    except ValidationError as error:
        raise ValueError(
            "Unsupported or malformed Skill registry; discard this cache explicitly"
        ) from error
    credential_id = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return state, state["accounts"].setdefault(credential_id, {})
