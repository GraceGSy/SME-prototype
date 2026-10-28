"""Structured LLM judgment with content-addressed caching."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from ..document import QUESTION_FIELD
from ..files import directory_hash, write_json
from ..prompts import REPO_ROOT, request_prompts
from ..providers.contracts import (
    SkillCallPolicy,
    SkillClient,
    SkillSessionBudget,
    StructuredOutputValidationError,
)
from ..providers.factory import create_skill_client
from ..providers.jev import JevSettings
from ..providers.settings import ModelSettings
from .configuration import CONTEXT_HEADER, PromptRepository, RenderedPrompt
from .evidence_encoding import encode_evidence
from .jev_selection import JevSelector
from .match_evidence import (
    EvidenceValidationError,
    JudgmentError,
    candidate_handle,
    center_texts,
    quote_length_feedback,
    validate_evidence,
)
from .models import JudgmentRequest, JudgmentResult

REPAIR_PROMPTS = request_prompts("evidence-repair")


class JudgmentProvider(Protocol):
    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        """Return one validated structured judgment."""


def inherited_structural_match(request: JudgmentRequest) -> JudgmentResult:
    """Record an inherited match without calling a selector or explanation model."""
    if request.output_kind != "match" or len(request.allowed_match_ids) != 1:
        raise ValueError("An inherited structural match requires exactly one candidate")
    rule = "single_paragraph_structural_match"
    target = request.allowed_match_ids[0]
    basis = (
        "Inherited the accepted section/subsection match: each structural unit represented here "
        "consists of exactly one paragraph. Quotations are deterministic source excerpts, "
        "not a new model judgment."
    )
    evidence = {
        side: [text.strip()[:240] for text in center_texts(value)]
        for side, value in (
            ("focus", request.context["focus"]),
            ("target", request.context["candidates"][0]),
        )
    }
    validate_evidence(request.context, target, evidence)
    context = json.dumps(request.context, ensure_ascii=False, sort_keys=True)
    return JudgmentResult(
        fingerprint=hashlib.sha256(f"{rule}:{context}".encode("utf-8")).hexdigest(),
        normalized={"target_id": target, "basis": basis, "evidence": evidence},
        raw_response={"rule": rule, "parent_group_id": request.context["scope"]["parent_group_id"]},
        rendered_system=basis,
        rendered_user=context,
        prompt_hash="",
        context_hash=hashlib.sha256(context.encode("utf-8")).hexdigest(),
        schema_hash="",
        model={"provider": "deterministic", "name": rule},
    )


class CachedJudgments:
    """Render, validate, and cache SMELTER judgments independently of the provider."""

    def __init__(
        self,
        prompts: PromptRepository,
        model: ModelSettings,
        cache_dir: Path,
        skill_root: Path,
        jev: JevSettings | None = None,
    ):
        self.prompts = prompts
        self.model = model
        self.cache_dir = cache_dir
        self.skill_root = skill_root
        self.skills: SkillClient | None = None
        self.jev = (
            JevSelector(jev, cache_dir / "jev", skill_root, prompts.prompt_root) if jev else None
        )
        cache_dir.mkdir(parents=True, exist_ok=True)

    def render_request(self, request: JudgmentRequest) -> RenderedPrompt:
        """Bind decoding to this pool without repairing model output."""
        rendered = self.prompts.render(
            request.prompt_ref,
            request.context_ref,
            request.context,
        )
        if request.output_kind == "match":
            if rendered.cacheable_context:
                prefix = json.loads(rendered.cacheable_context.split("\n\n", 1)[1])
                encoded = json.dumps(
                    encode_evidence(prefix), ensure_ascii=False, separators=(",", ":")
                )
                rendered = replace(
                    rendered,
                    cacheable_context=CONTEXT_HEADER + encoded,
                    prompt_hash=hashlib.sha256(
                        (rendered.prompt_hash + "\0shared-text-v1").encode()
                    ).hexdigest(),
                )
            schema = deepcopy(rendered.schema)
            schema["properties"]["target_id"] = (
                {
                    "anyOf": [
                        {"type": "string", "enum": list(request.allowed_match_ids)},
                        {"type": "null"},
                    ]
                }
                if request.allowed_match_ids
                else {"type": "null"}
            )
            encoded = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
            rendered = replace(
                rendered, schema=schema, schema_hash=hashlib.sha256(encoded).hexdigest()
            )
        return rendered

    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        # Retry attribution and quote-length failures, never unrelated contract errors.
        # Each attempt uses the same source pool and native Skill; only feedback changes.
        feedback = ""
        for attempt in range(3):
            try:
                return self._judge_once(request, feedback)
            except StructuredOutputValidationError as error:
                if (
                    request.output_kind != "match"
                    or not error.errors
                    or any(
                        item.validator != "maxLength"
                        or item.validator_value != 240
                        or len(item.absolute_path) != 3
                        or list(item.absolute_path)[:2]
                        not in (["evidence", "focus"], ["evidence", "target"])
                        or not isinstance(item.absolute_path[-1], int)
                        for item in error.errors
                    )
                ):
                    raise
                failure = EvidenceValidationError(
                    " ".join(
                        quote_length_feedback(
                            item.absolute_path[1], item.absolute_path[2], item.instance
                        )
                        for item in error.errors
                    )
                )
            except EvidenceValidationError as error:
                failure = error
            if attempt == 2:
                raise failure
            feedback = REPAIR_PROMPTS["retry"].format(error=failure)
        raise AssertionError("Unreachable retry state")

    def _judge_once(self, request: JudgmentRequest, feedback: str) -> JudgmentResult:
        rendered = self.render_request(request)
        skill_path = self.skill_root / request.skill_ref if request.skill_ref else None
        if not skill_path:
            raise JudgmentError(f"Every LLM judgment requires a configured Skill: {request.key}")
        if not skill_path.is_dir():
            raise JudgmentError(f"Skill directory does not exist: {skill_path}")
        skill_hash = directory_hash(skill_path)
        fingerprint = self._fingerprint(request, rendered, skill_hash)
        cache_path = self.cache_dir / f"{fingerprint}.json"
        if cache_path.is_file() and not request.force and not feedback:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            result = JudgmentResult.model_validate(payload)
            result.cache_hit = True
            self._validate(request, result.normalized)
            if self.jev and request.output_kind == "match":
                if result.normalized["target_id"] != result.raw_response["jev"]["target_id"]:
                    raise JudgmentError("Cached evidence changed Jev's selection")
            return result

        selection = None
        if self.jev and request.output_kind == "match":
            selection = self.jev.select(request, force=request.force and not feedback)
            target = selection["target_id"]
            if target is None:
                result = JudgmentResult(
                    fingerprint=fingerprint,
                    normalized={
                        "target_id": None,
                        "basis": "Jev found no supported match; no generative explanation was requested.",
                        "evidence": {"focus": [], "target": []},
                    },
                    raw_response={"jev": selection},
                    rendered_system=self.jev.instructions,
                    rendered_user=json.dumps(request.context, ensure_ascii=False),
                    prompt_hash=rendered.prompt_hash,
                    context_hash=rendered.context_hash,
                    schema_hash=rendered.schema_hash,
                    model={"jev": self.jev.settings.model_dump()},
                )
                self._validate(request, result.normalized)
                write_json(cache_path, result.model_dump(mode="json"))
                return result
            evidence_request = request.model_copy(
                update={
                    "context": {
                        **request.context,
                        "candidates": [
                            candidate
                            for candidate in request.context["candidates"]
                            if candidate_handle(candidate) == target
                        ],
                    },
                    "allowed_match_ids": [target],
                }
            )
            rendered = self.render_request(evidence_request)
            rendered.schema["properties"]["target_id"] = {"type": "string", "enum": [target]}
            rendered = replace(
                rendered,
                user=rendered.user + "\n\n" + json.dumps({"fixed_target_id": target}),
                schema_hash=hashlib.sha256(
                    json.dumps(rendered.schema, sort_keys=True).encode()
                ).hexdigest(),
            )

        if self.skills is None:
            self.skills = create_skill_client(
                REPO_ROOT,
                REPO_ROOT / "_cache" / "skill-registry.json",
                self.model.name,
                session_budget=SkillSessionBudget(
                    max_api_responses=self.model.max_api_responses_per_process,
                    max_input_tokens=self.model.max_session_input_tokens,
                    max_output_tokens=self.model.max_session_output_tokens,
                ),
                response_dir=self.cache_dir / "responses",
                provider=self.model.provider,
            )
        skill = self.skills.register(skill_path)
        user_prompt = rendered.user + feedback
        response = self.skills.run_json(
            [skill],
            user_prompt,
            rendered.schema,
            policy=SkillCallPolicy(
                max_tokens=request.max_tokens or self.model.max_tokens,
                effort=self.model.effort,
                thinking=self.model.thinking,
                max_input_tokens=request.max_input_tokens or self.model.max_input_tokens,
                max_prompt_characters=self.model.max_prompt_characters,
                context_management_trigger_tokens=(self.model.context_management_trigger_tokens),
            ),
            cacheable_prompt=rendered.system,
            cacheable_context=rendered.cacheable_context,
        )
        api_normalized = dict(response.value)
        model = {
            **self.model.model_dump(mode="json"),
            "effective_max_tokens": request.max_tokens or self.model.max_tokens,
            "effective_max_input_tokens": (request.max_input_tokens or self.model.max_input_tokens),
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
        if selection is not None:
            raw_response = {**raw_response, "jev": selection}
            model["jev"] = self.jev.settings.model_dump()

        normalized = api_normalized
        result = JudgmentResult(
            fingerprint=fingerprint,
            normalized=normalized,
            raw_response=raw_response,
            rendered_system=rendered.system,
            # Preserve all user evidence in the existing text provenance contract.
            rendered_user="\n\n".join(
                block for block in (rendered.cacheable_context, user_prompt) if block
            ),
            prompt_hash=rendered.prompt_hash,
            context_hash=rendered.context_hash,
            schema_hash=rendered.schema_hash,
            model=model,
            cache_hit=False,
        )
        try:
            if selection is not None and normalized.get("target_id") != selection["target_id"]:
                raise JudgmentError("Generative evidence must not change Jev's selection")
            self._validate(request, normalized)
        except JudgmentError as error:
            # Preserve paid evidence without accepting or repairing the rejected output.
            write_json(
                self.cache_dir / "rejected" / f"{fingerprint}-{uuid4().hex}.json",
                {
                    "request": request.model_dump(mode="json"),
                    "result": result.model_dump(mode="json"),
                    "error": str(error),
                },
            )
            if isinstance(error, EvidenceValidationError):
                # Retries are separate requests, so they cannot see the prior answer.
                raise EvidenceValidationError(
                    REPAIR_PROMPTS["rejected_response"].format(
                        error=error, response=json.dumps(normalized, ensure_ascii=False)
                    )
                ) from error
            raise
        write_json(cache_path, result.model_dump(mode="json"))
        return result

    def _fingerprint(self, request: JudgmentRequest, rendered, skill_hash: str | None) -> str:
        payload = {
            "output_kind": request.output_kind,
            "prompt_hash": rendered.prompt_hash,
            "context_hash": rendered.context_hash,
            "schema_hash": rendered.schema_hash,
            "model": self.model.result_settings(),
            "max_tokens": request.max_tokens or self.model.max_tokens,
            "skill_hash": skill_hash,
            "jev": self.jev.settings.result_settings() if self.jev else None,
        }
        if self.jev and request.output_kind == "match":
            payload["jev_request"] = self.jev.build_request(request.context)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validate(request: JudgmentRequest, value: dict) -> None:
        if request.output_kind == "question":
            if not isinstance(value, dict) or set(value) != {QUESTION_FIELD}:
                raise JudgmentError(f"{request.key} requires exactly {QUESTION_FIELD}")
            question = value.get(QUESTION_FIELD)
            if not isinstance(question, str) or not question.strip():
                raise JudgmentError(f"{request.key} returned an empty question")
            return
        if not isinstance(value, dict) or set(value) != {"target_id", "basis", "evidence"}:
            raise JudgmentError(f"{request.key} requires exactly target_id, basis, and evidence")
        if not isinstance(value["basis"], str) or not value["basis"].strip():
            raise JudgmentError(f"{request.key} requires a non-empty basis")
        chosen = value["target_id"]
        if chosen is not None and not isinstance(chosen, str):
            raise JudgmentError(f"{request.key} requires a string target_id or explicit null")
        if chosen is not None and chosen not in request.allowed_match_ids:
            raise JudgmentError(
                f"{request.key} selected {chosen!r}; allowed values are {request.allowed_match_ids} or null"
            )
        validate_evidence(request.context, chosen, value["evidence"])
