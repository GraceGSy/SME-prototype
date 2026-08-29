"""Load pipeline, prompt, and context configuration from human-readable files."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import PipelineConfig


class ConfigurationError(ValueError):
    """Raised when declarative pipeline assets are incomplete or invalid."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_pipeline_config(path: Path) -> PipelineConfig:
    path = path.resolve()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ConfigurationError(f"Could not load pipeline config {path}: {error}") from error
    config = PipelineConfig.model_validate(payload)
    config.prompt_root = (path.parent / config.prompt_root).resolve()
    config.context_root = (path.parent / config.context_root).resolve()
    config.skill_root = (path.parent / config.skill_root).resolve()
    return config


@dataclass(frozen=True)
class RenderedPrompt:
    system: str
    user: str
    schema: dict[str, Any]
    prompt_hash: str
    context_hash: str
    schema_hash: str


class PromptRepository:
    """Render versioned prompt bundles using filtered, deterministic JSON context."""

    _PLACEHOLDER = "{{context_json}}"

    def __init__(self, prompt_root: Path, context_root: Path):
        self.prompt_root = prompt_root
        self.context_root = context_root

    def render(self, prompt_ref: str, context_ref: str, context: dict[str, Any]) -> RenderedPrompt:
        prompt_dir = self.prompt_root / prompt_ref
        system = self._read(prompt_dir / "system.md")
        user_template = self._read(prompt_dir / "user.md")
        schema_text = self._read(prompt_dir / "output.schema.json")
        try:
            schema = json.loads(schema_text)
        except json.JSONDecodeError as error:
            raise ConfigurationError(f"Invalid output schema for {prompt_ref}: {error}") from error

        context_config = self._load_context(context_ref)
        included = context_config.get("include", list(context))
        unknown = [field for field in included if field not in context]
        if unknown:
            raise ConfigurationError(f"Context {context_ref} requests unavailable fields: {unknown}")
        filtered = {field: deepcopy(context[field]) for field in included}
        for path in context_config.get("exclude", []):
            self._remove_path(filtered, str(path).split("."))
        context_json = json.dumps(filtered, indent=2, ensure_ascii=False, sort_keys=True)
        self._validate_context_size(context_ref, context_config, context_json)

        if self._PLACEHOLDER not in user_template:
            raise ConfigurationError(f"Prompt {prompt_ref}/user.md must contain {self._PLACEHOLDER}")
        user = user_template.replace(self._PLACEHOLDER, context_json)
        unresolved = re.findall(r"{{[^{}]+}}", user)
        if unresolved:
            raise ConfigurationError(f"Prompt {prompt_ref} has unresolved placeholders: {unresolved}")
        return RenderedPrompt(
            system=system,
            user=user,
            schema=schema,
            prompt_hash=_sha256_text(system + "\0" + user_template),
            context_hash=_sha256_text(context_json),
            schema_hash=_sha256_text(schema_text),
        )

    def _load_context(self, context_ref: str) -> dict[str, Any]:
        path = self.context_root / f"{context_ref}.yaml"
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as error:
            raise ConfigurationError(f"Could not load context {context_ref}: {error}") from error
        if not isinstance(payload, dict):
            raise ConfigurationError(f"Context {context_ref} must be a YAML object")
        return payload

    @staticmethod
    def _validate_context_size(context_ref: str, config: dict[str, Any], context_json: str) -> None:
        maximum = int(config.get("max_characters") or 0)
        if maximum and len(context_json) > maximum:
            policy = config.get("overflow", "fail")
            if policy != "fail":
                raise ConfigurationError(f"Unsupported overflow policy in {context_ref}: {policy}")
            raise ConfigurationError(
                f"Context {context_ref} is {len(context_json)} characters; configured maximum is {maximum}"
            )

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ConfigurationError(f"Could not read {path}: {error}") from error

    @classmethod
    def _remove_path(cls, value: Any, parts: list[str]) -> None:
        if not parts:
            return
        head, *tail = parts
        if isinstance(value, list):
            if head != "*":
                raise ConfigurationError("List fields in context exclude paths must use '*'")
            for item in value:
                cls._remove_path(item, tail)
            return
        if not isinstance(value, dict) or head not in value:
            return
        if tail:
            cls._remove_path(value[head], tail)
        else:
            del value[head]
