"""Structured LLM judgment with content-addressed caching."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from .configuration import PromptRepository
from .models import JudgmentRequest, JudgmentResult, ModelSettings


class JudgmentError(RuntimeError):
    """Raised when a model response does not satisfy the requested contract."""


class JudgmentProvider(Protocol):
    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        """Return one validated structured judgment."""


class AnthropicJudgmentProvider:
    """Use one forced Anthropic tool call per judgment and cache by full input."""

    def __init__(self, prompts: PromptRepository, model: ModelSettings, cache_dir: Path):
        self.prompts = prompts
        self.model = model
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        rendered = self.prompts.render(request.prompt_ref, request.context_ref, request.context)
        fingerprint = self._fingerprint(request, rendered)
        cache_path = self.cache_dir / f"{fingerprint}.json"
        if cache_path.is_file() and not request.force:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            result = JudgmentResult.model_validate(payload)
            result.cache_hit = True
            self._validate(request, result.normalized)
            return result

        try:
            from anthropic import Anthropic
        except ImportError as error:
            raise JudgmentError("Install pipeline/requirements.txt before running LLM stages") from error

        client = Anthropic()
        tool_name = "record_question" if request.output_kind == "question" else "record_match"
        response = client.messages.create(
            model=self.model.name,
            max_tokens=self.model.max_tokens,
            temperature=self.model.temperature,
            system=rendered.system,
            messages=[{"role": "user", "content": rendered.user}],
            tools=[{
                "name": tool_name,
                "description": "Record the requested judgment in the required schema.",
                "input_schema": rendered.schema,
            }],
            tool_choice={"type": "tool", "name": tool_name},
        )
        tool_blocks = [block for block in response.content if getattr(block, "type", "") == "tool_use"]
        if len(tool_blocks) != 1:
            raise JudgmentError(f"Expected one {tool_name} tool result; received {len(tool_blocks)}")
        normalized = dict(tool_blocks[0].input)
        self._validate(request, normalized)
        result = JudgmentResult(
            fingerprint=fingerprint,
            normalized=normalized,
            raw_response=response.model_dump(mode="json"),
            rendered_system=rendered.system,
            rendered_user=rendered.user,
            prompt_hash=rendered.prompt_hash,
            context_hash=rendered.context_hash,
            schema_hash=rendered.schema_hash,
            model=self.model.model_dump(mode="json"),
            cache_hit=False,
        )
        cache_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return result

    def _fingerprint(self, request: JudgmentRequest, rendered) -> str:
        payload = {
            "output_kind": request.output_kind,
            "prompt_hash": rendered.prompt_hash,
            "context_hash": rendered.context_hash,
            "schema_hash": rendered.schema_hash,
            "model": self.model.model_dump(mode="json"),
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
