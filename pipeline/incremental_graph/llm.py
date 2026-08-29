"""Structured LLM judgment with content-addressed caching."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from .configuration import PromptRepository
from .models import JudgmentRequest, JudgmentResult, ModelSettings
from .skill_api import ClaudeSkills, directory_hash


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
        if skill_path and not skill_path.is_dir():
            raise JudgmentError(f"Matching Skill directory does not exist: {skill_path}")
        skill_hash = directory_hash(skill_path) if skill_path else None
        fingerprint = self._fingerprint(request, rendered, skill_hash)
        cache_path = self.cache_dir / f"{fingerprint}.json"
        if cache_path.is_file() and not request.force:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            result = JudgmentResult.model_validate(payload)
            result.cache_hit = True
            self._validate(request, result.normalized)
            return result

        if skill_path:
            if self.skills is None:
                self.skills = ClaudeSkills(
                    self.skill_root.parent,
                    self.cache_dir / "skill-registry.json",
                    self.model.name,
                )
            skill = self.skills.register(skill_path)
            response = self.skills.run_json(
                [skill],
                rendered.user,
                rendered.schema,
                max_tokens=max(self.model.max_tokens, 4096),
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
        else:
            normalized, raw_response, model = self._ordinary_call(rendered, request)

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

    def _ordinary_call(self, rendered, request: JudgmentRequest) -> tuple[dict, dict, dict]:
        try:
            from anthropic import Anthropic
        except ImportError as error:
            raise JudgmentError("Install requirements.txt before running LLM stages") from error

        client = Anthropic()
        tool_name = "record_question" if request.output_kind == "question" else "record_match"
        request_args = dict(
            model=self.model.name,
            max_tokens=self.model.max_tokens,
            system=rendered.system,
            messages=[{"role": "user", "content": rendered.user}],
            tools=[{
                "name": tool_name,
                "description": "Record the requested judgment in the required schema.",
                "input_schema": rendered.schema,
            }],
            tool_choice={"type": "tool", "name": tool_name},
        )
        if self.model.temperature is not None:
            request_args["extra_body"] = {"temperature": self.model.temperature}
        response = client.messages.create(**request_args)
        tool_blocks = [block for block in response.content if getattr(block, "type", "") == "tool_use"]
        if len(tool_blocks) != 1:
            raise JudgmentError(f"Expected one {tool_name} tool result; received {len(tool_blocks)}")
        return (
            dict(tool_blocks[0].input),
            response.model_dump(mode="json"),
            self.model.model_dump(mode="json"),
        )

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
            question = value.get("question")
            if not isinstance(question, str) or not question.strip():
                raise JudgmentError(f"{request.key} returned an empty question")
            return
        chosen = value.get("best_match_id")
        if chosen is not None and chosen not in request.allowed_match_ids:
            raise JudgmentError(
                f"{request.key} selected {chosen!r}; allowed values are {request.allowed_match_ids} or null"
            )
