"""Structured LLM judgment with content-addressed caching."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from ..document import QUESTION_FIELD
from .configuration import PromptRepository
from .models import JudgmentRequest, JudgmentResult, ModelSettings
from .skill_api import (
    ClaudeSkills,
    SkillCallPolicy,
    SkillSessionBudget,
    directory_hash,
)


class JudgmentError(RuntimeError):
    """Raised when a model response does not satisfy the requested contract."""


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
        rendered = self.prompts.render(request.prompt_ref, request.context_ref, request.context)
        skill_path = self.skill_root / request.skill_ref if request.skill_ref else None
        if not skill_path:
            raise JudgmentError(f"Every LLM judgment requires a configured Skill: {request.key}")
        if not skill_path.is_dir():
            raise JudgmentError(f"Skill directory does not exist: {skill_path}")
        skill_hash = directory_hash(skill_path)
        fingerprint = self._fingerprint(request, rendered, skill_hash)
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
        prompt = f"{rendered.system}\n\n{rendered.user}"
        response = self.skills.run_json(
            [skill],
            prompt,
            rendered.schema,
            policy=SkillCallPolicy(
                max_tokens=self.model.max_tokens,
                effort=self.model.effort,
                thinking=self.model.thinking,
                task_budget_tokens=self.model.task_budget_tokens,
                max_input_tokens=self.model.max_input_tokens,
                max_continuations=self.model.max_continuations,
                max_prompt_characters=self.model.max_prompt_characters,
                context_management_trigger_tokens=(
                    self.model.context_management_trigger_tokens
                ),
            ),
        )
        normalized = dict(response.value)
        model = {
            **self.model.model_dump(mode="json"),
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
        chosen = value.get("target_id")
        if chosen is not None and chosen not in request.allowed_match_ids:
            raise JudgmentError(
                f"{request.key} selected {chosen!r}; allowed values are {request.allowed_match_ids} or null"
            )
