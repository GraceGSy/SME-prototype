"""Load pipeline, prompt, and context configuration from human-readable files."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from jsonschema import Draft202012Validator
from pydantic import Field

from .models import PipelineConfig, StrictModel


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
    validate_pipeline_config(config)
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
        included = context_config.include
        unknown = [field for field in included if field not in context]
        if unknown:
            raise ConfigurationError(
                f"Context {context_ref} requests unavailable fields: {unknown}"
            )
        filtered = {field: context[field] for field in included}
        # Evidence order is intentional: focus before candidates, previous/center/next.
        context_json = json.dumps(filtered, indent=2, ensure_ascii=False)
        self._validate_context_size(context_ref, context_config, context_json)

        if self._PLACEHOLDER not in user_template:
            raise ConfigurationError(
                f"Prompt {prompt_ref}/user.md must contain {self._PLACEHOLDER}"
            )
        unresolved = re.findall(r"{{[^{}]+}}", user_template.replace(self._PLACEHOLDER, ""))
        if unresolved:
            raise ConfigurationError(
                f"Prompt {prompt_ref} has unresolved placeholders: {unresolved}"
            )
        user = user_template.replace(self._PLACEHOLDER, context_json)
        return RenderedPrompt(
            system=system,
            user=user,
            schema=schema,
            prompt_hash=_sha256_text(system + "\0" + user_template),
            context_hash=_sha256_text(context_json),
            schema_hash=_sha256_text(schema_text),
        )

    def _load_context(self, context_ref: str) -> ContextConfig:
        path = self.context_root / f"{context_ref}.yaml"
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ConfigurationError(f"Could not load context {context_ref}: {error}") from error
        return ContextConfig.model_validate(payload)

    @staticmethod
    def _validate_context_size(context_ref: str, config: ContextConfig, context_json: str) -> None:
        maximum = config.max_characters
        if maximum and len(context_json) > maximum:
            raise ConfigurationError(
                f"Context {context_ref} is {len(context_json)} characters; configured maximum is {maximum}"
            )

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ConfigurationError(f"Could not read {path}: {error}") from error


class ContextConfig(StrictModel):
    include: list[str] = Field(min_length=1)
    max_characters: int = Field(ge=0)
    overflow: Literal["fail"]


# The implemented algorithm has one dependency order, not a general workflow engine.
STAGE_ORDER = (
    ("ingest", "ingest_paper", "structural"),
    ("section_questions", "generate_section_questions", "structural"),
    ("section_matching", "match_sections", "structural"),
    ("section_reconciliation", "reconcile_sections", "structural"),
    ("section_group_questions", "generate_section_group_questions", "structural"),
    ("section_rerepresentation", "rerepresent_section_singletons", "structural"),
    (
        "section_rerepresentation_questions",
        "regenerate_rerepresented_section_questions",
        "structural",
    ),
    ("paragraph_questions", "generate_paragraph_questions", "paragraph"),
    ("paragraph_matching", "match_paragraphs", "paragraph"),
    ("paragraph_reconciliation", "reconcile_paragraphs", "paragraph"),
    ("paragraph_group_questions", "generate_paragraph_group_questions", "paragraph"),
    ("paragraph_rerepresentation", "rerepresent_paragraph_singletons", "paragraph"),
    (
        "paragraph_rerepresentation_questions",
        "regenerate_rerepresented_paragraph_questions",
        "paragraph",
    ),
)


def validate_pipeline_config(config: PipelineConfig) -> None:
    if tuple((stage.id, stage.handler, stage.phase) for stage in config.stages) != STAGE_ORDER:
        raise ConfigurationError(
            "Stages must follow the implemented algorithm's exact dependency order"
        )
    repository = PromptRepository(config.prompt_root, config.context_root)
    for stage in config.stages:
        references: list[tuple[str, str]] = []
        if stage.handler in {
            "match_sections",
            "match_paragraphs",
            "rerepresent_section_singletons",
            "rerepresent_paragraph_singletons",
        }:
            directions = (
                {"singleton_to_group", "group_to_singleton"}
                if stage.handler.startswith("rerepresent_")
                else {"new_to_group", "group_to_new"}
            )
            if (
                set(stage.prompts) != directions
                or set(stage.contexts) != directions
                or stage.prompt
                or stage.context
            ):
                raise ConfigurationError(
                    f"Stage {stage.id} requires exactly these directions: {sorted(directions)}"
                )
            references = [(stage.prompts[key], stage.contexts[key]) for key in sorted(directions)]
        elif stage.handler.startswith(("generate_", "regenerate_")):
            if not stage.prompt or not stage.context or stage.prompts or stage.contexts:
                raise ConfigurationError(f"Stage {stage.id} requires one prompt and context")
            references = [(stage.prompt, stage.context)]
        elif stage.prompt or stage.context or stage.prompts or stage.contexts or stage.skill:
            raise ConfigurationError(
                f"Deterministic stage {stage.id} does not accept model settings"
            )
        if references:
            if not stage.skill or not (config.skill_root / stage.skill / "SKILL.md").is_file():
                raise ConfigurationError(f"Stage {stage.id} references a missing Skill")
            for prompt, context in references:
                spec = repository._load_context(context)
                rendered = repository.render(
                    prompt, context, {field: None for field in spec.include}
                )
                Draft202012Validator.check_schema(rendered.schema)
