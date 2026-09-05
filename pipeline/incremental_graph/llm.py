"""Structured LLM judgment with content-addressed caching."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from ..document import QUESTION_FIELD
from .configuration import PromptRepository, RenderedPrompt
from .models import JudgmentRequest, JudgmentResult, ModelSettings
from .skill_api import (
    ClaudeSkills,
    SkillCallPolicy,
    SkillSessionBudget,
    directory_hash,
)


class JudgmentError(RuntimeError):
    """Raised when a model response does not satisfy the requested contract."""


@dataclass(frozen=True)
class _BatchAliases:
    source_ids: dict[str, str]
    target_ids: dict[str, str]


def _alias_batch_request(
    request: JudgmentRequest,
) -> tuple[JudgmentRequest, _BatchAliases | None]:
    """Give batched choices short IDs while retaining stable IDs as evidence."""

    if request.output_kind != "match_batch":
        return request, None

    focus = request.context.get("focus")
    candidates = request.context.get("candidates")
    if not isinstance(focus, list) or len(focus) != len(request.expected_match_source_ids):
        raise JudgmentError(f"{request.key} has inconsistent batched focus units")
    if not isinstance(candidates, list) or len(candidates) != len(request.allowed_match_ids):
        raise JudgmentError(f"{request.key} has inconsistent batched candidates")

    source_ids = {
        f"S{index:04d}": stable_id
        for index, stable_id in enumerate(request.expected_match_source_ids, start=1)
    }
    target_ids = {
        f"T{index:04d}": stable_id
        for index, stable_id in enumerate(request.allowed_match_ids, start=1)
    }
    context = deepcopy(request.context)
    for item, alias in zip(context["focus"], source_ids, strict=True):
        if not isinstance(item, dict):
            raise JudgmentError(f"{request.key} has an invalid batched focus unit")
        item["selection_id"] = alias
    for item, alias in zip(context["candidates"], target_ids, strict=True):
        if not isinstance(item, dict):
            raise JudgmentError(f"{request.key} has an invalid batched candidate")
        item["selection_id"] = alias

    aliased = request.model_copy(update={
        "context": context,
        "expected_match_source_ids": list(source_ids),
        "allowed_match_ids": list(target_ids),
    })
    return aliased, _BatchAliases(source_ids=source_ids, target_ids=target_ids)


def _restore_batch_ids(value: dict, aliases: _BatchAliases | None) -> dict:
    if aliases is None:
        return value
    restored = dict(value)
    restored["matches"] = [
        {
            **item,
            "source_id": aliases.source_ids[item["source_id"]],
            "target_id": (
                aliases.target_ids[item["target_id"]]
                if item.get("target_id") is not None
                else None
            ),
        }
        for item in value["matches"]
    ]
    return restored


def _constrain_batch_schema(schema: dict, request: JudgmentRequest) -> dict:
    """Restrict structured batch IDs to the aliases supplied in this request."""

    if request.output_kind != "match_batch":
        return schema
    constrained = deepcopy(schema)
    properties = constrained["properties"]["matches"]["items"]["properties"]
    properties["source_id"] = {
        "type": "string",
        "enum": request.expected_match_source_ids,
    }
    properties["target_id"] = {
        "anyOf": [
            {"type": "string", "enum": request.allowed_match_ids},
            {"type": "null"},
        ]
    }
    return constrained


def _specialize_rendered_prompt(
    rendered: RenderedPrompt,
    request: JudgmentRequest,
) -> RenderedPrompt:
    if request.output_kind != "match_batch":
        return rendered
    schema = _constrain_batch_schema(rendered.schema, request)
    return replace(
        rendered,
        schema=schema,
        schema_hash=hashlib.sha256(
            json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    )


class JudgmentProvider(Protocol):
    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        """Return one validated structured judgment."""


class AnthropicJudgmentProvider:
    """Run structured Anthropic judgments and cache each complete input."""

    def __init__(
        self,
        prompts: PromptRepository,
        model: ModelSettings,
        cache_dir: Path,
        skill_root: Path,
    ):
        self.prompts = prompts
        self.model = model
        self.cache_dir = cache_dir
        self.skill_root = skill_root
        self.skills: ClaudeSkills | None = None
        cache_dir.mkdir(parents=True, exist_ok=True)

    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        api_request, aliases = _alias_batch_request(request)
        rendered = self.prompts.render(
            api_request.prompt_ref,
            api_request.context_ref,
            api_request.context,
        )
        rendered = _specialize_rendered_prompt(rendered, api_request)
        skill_path = self.skill_root / request.skill_ref if request.skill_ref else None
        if not skill_path:
            raise JudgmentError(f"Every LLM judgment requires a configured Skill: {request.key}")
        if not skill_path.is_dir():
            raise JudgmentError(f"Skill directory does not exist: {skill_path}")
        skill_hash = directory_hash(skill_path)
        fingerprint = self._fingerprint(api_request, rendered, skill_hash)
        cache_path = self.cache_dir / f"{fingerprint}.json"
        if cache_path.is_file() and not request.force:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            result = JudgmentResult.model_validate(payload)
            result.cache_hit = True
            self._validate(request, result.normalized)
            return result

        if self.skills is None:
            self.skills = ClaudeSkills(
                self.skill_root.parent,
                self.cache_dir / "skill-registry.json",
                self.model.name,
                session_budget=SkillSessionBudget(
                    max_api_responses=self.model.max_api_responses_per_process,
                    max_input_tokens=self.model.max_session_input_tokens,
                    max_output_tokens=self.model.max_session_output_tokens,
                ),
            )
        skill = self.skills.register(skill_path)
        response = self.skills.run_json(
            [skill],
            rendered.user,
            rendered.schema,
            policy=SkillCallPolicy(
                max_tokens=request.max_tokens or self.model.max_tokens,
                effort=self.model.effort,
                thinking=self.model.thinking,
                max_input_tokens=request.max_input_tokens or self.model.max_input_tokens,
                max_prompt_characters=self.model.max_prompt_characters,
                context_management_trigger_tokens=(
                    self.model.context_management_trigger_tokens
                ),
            ),
            cacheable_prompt=rendered.system,
        )
        api_normalized = dict(response.value)
        model = {
            **self.model.model_dump(mode="json"),
            "effective_max_tokens": request.max_tokens or self.model.max_tokens,
            "effective_max_input_tokens": (
                request.max_input_tokens or self.model.max_input_tokens
            ),
            "skill": {
                "path": skill.path,
                "skill_id": skill.skill_id,
                "version": skill.version,
                "source_sha256": skill.source_sha256,
            },
        }
        raw_response = response.raw_response or {
            "id": response.response_id,
            "stop_reason": response.stop_reason,
            "usage": response.usage,
        }

        self._validate(api_request, api_normalized)
        normalized = _restore_batch_ids(api_normalized, aliases)
        self._validate(request, normalized)
        result = JudgmentResult(
            fingerprint=fingerprint,
            normalized=normalized,
            raw_response=raw_response,
            rendered_system=rendered.system,
            rendered_user=rendered.user,
            prompt_hash=rendered.prompt_hash,
            context_hash=rendered.context_hash,
            schema_hash=rendered.schema_hash,
            model=model,
            cache_hit=False,
        )
        cache_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return result

    def _fingerprint(self, request: JudgmentRequest, rendered, skill_hash: str | None) -> str:
        payload = {
            "output_kind": request.output_kind,
            "prompt_hash": rendered.prompt_hash,
            "context_hash": rendered.context_hash,
            "schema_hash": rendered.schema_hash,
            "model": self.model.model_dump(mode="json"),
            "max_tokens": request.max_tokens or self.model.max_tokens,
            "max_input_tokens": request.max_input_tokens or self.model.max_input_tokens,
            "skill_hash": skill_hash,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validate(request: JudgmentRequest, value: dict) -> None:
        if request.output_kind == "question":
            question = value.get(QUESTION_FIELD)
            if not isinstance(question, str) or not question.strip():
                raise JudgmentError(f"{request.key} returned an empty question")
            return
        if request.output_kind == "match_batch":
            matches = value.get("matches")
            if not isinstance(matches, list):
                raise JudgmentError(f"{request.key} returned no match list")
            returned_ids = []
            for item in matches:
                if not isinstance(item, dict):
                    raise JudgmentError(f"{request.key} returned an invalid match item")
                source_id = item.get("source_id")
                target_id = item.get("target_id")
                if not isinstance(source_id, str) or not source_id:
                    raise JudgmentError(f"{request.key} returned a match without a source ID")
                if target_id is not None and target_id not in request.allowed_match_ids:
                    raise JudgmentError(
                        f"{request.key} selected {target_id!r}; allowed values are "
                        f"{request.allowed_match_ids} or null"
                    )
                returned_ids.append(source_id)
            if len(returned_ids) != len(set(returned_ids)):
                raise JudgmentError(f"{request.key} returned duplicate match source IDs")
            if set(returned_ids) != set(request.expected_match_source_ids):
                raise JudgmentError(
                    f"{request.key} returned source IDs {sorted(returned_ids)}; expected "
                    f"{sorted(request.expected_match_source_ids)}"
                )
            return
        chosen = value.get("target_id")
        if chosen is not None and chosen not in request.allowed_match_ids:
            raise JudgmentError(
                f"{request.key} selected {chosen!r}; allowed values are {request.allowed_match_ids} or null"
            )
