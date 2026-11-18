"""Structured LLM judgment with content-addressed caching."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from ..document import ROLE_FIELD, is_role_statement
from ..files import directory_hash, write_json
from ..prompts import REPO_ROOT, request_prompts
from ..providers.contracts import (
    SkillCallPolicy,
    SkillClient,
    SkillSessionBudget,
    StructuredOutputValidationError,
)
from ..providers.factory import create_skill_client
from ..providers.jev import JevSettings, encode_request
from ..providers.settings import ModelSettings
from .configuration import CONTEXT_HEADER, PromptRepository, RenderedPrompt
from .evidence_encoding import (
    EVIDENCE_PROMPTS,
    encode_evidence,
    paragraph_comparison,
    paragraph_options,
    passage_state,
)
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
        self.jev = JevSelector(jev, cache_dir / "jev") if jev else None
        cache_dir.mkdir(parents=True, exist_ok=True)

    def render_request(
        self, request: JudgmentRequest, labels: dict[str, str] | None = None
    ) -> RenderedPrompt:
        """Bind decoding to this pool without repairing model output."""
        comparison = (
            paragraph_comparison(request.context, labels)
            if request.output_kind == "match"
            else None
        )
        instructions = None
        if comparison:
            wording = request_prompts("jev")[comparison.direction]
            instructions = (
                (
                    instructions
                    or (
                        wording["match"] + " Return the option label or null. "
                        "Explain the decision. Quote each side's members in member-number order, one short verbatim "
                        "quote per member. If none fits, return empty evidence arrays."
                    )
                )
                + "\n"
                + wording["guide"]
            )
        rendered = self.prompts.render(
            request.prompt_ref,
            request.context_ref,
            request.context,
            instructions=instructions,
        )
        if request.output_kind == "match":
            state = None if comparison else passage_state(request.context)
            if comparison:
                rendered = replace(
                    rendered,
                    cacheable_context=comparison.prefix or None,
                    user=comparison.remainder,
                    context_hash=hashlib.sha256(
                        (rendered.context_hash + "\0" + comparison.text).encode()
                    ).hexdigest(),
                )
            elif state is not None:
                # Keep a reusable candidate prefix only when it precedes the focus
                # in paper order. Never split overlapping windows into two blocks.
                prefix_papers = {}
                for paper, rows in state["papers"].items():
                    if any(
                        "focus" in tag or "focus_group" in tag
                        for row in rows
                        for tag in row.get("roles", [row])
                    ):
                        break
                    prefix_papers[paper] = rows
                other_papers = {k: v for k, v in state["papers"].items() if k not in prefix_papers}

                def dump(value):
                    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

                prefix = {**state, "papers": prefix_papers} if prefix_papers else None
                rendered = replace(
                    rendered,
                    system=rendered.system + "\n\n" + EVIDENCE_PROMPTS["passage_layout"],
                    user=dump({"papers": other_papers} if prefix else state),
                    cacheable_context=CONTEXT_HEADER + dump(prefix) if prefix else None,
                    prompt_hash=hashlib.sha256(
                        (
                            rendered.prompt_hash
                            + "\0source-order-v1\0"
                            + EVIDENCE_PROMPTS["passage_layout"]
                        ).encode()
                    ).hexdigest(),
                )
            elif rendered.cacheable_context:
                prefix = json.loads(rendered.cacheable_context.split("\n\n", 1)[1])
                encoded = json.dumps(
                    encode_evidence(prefix, candidate_handles=self.jev is None),
                    ensure_ascii=False,
                    separators=(",", ":"),
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
                        {
                            "type": "string",
                            "enum": list(comparison.labels.values())
                            if comparison
                            else list(request.allowed_match_ids),
                        },
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

    def vote(self, request: JudgmentRequest, *, rank_only: bool = False) -> JudgmentResult:
        """Record a directional Jev result without commissioning an explanation."""
        selection = self.jev.select(request, force=request.force, rank_only=rank_only)
        calls = selection["calls"]
        return JudgmentResult(
            fingerprint=hashlib.sha256(
                json.dumps([c["fingerprint"] for c in calls]).encode()
            ).hexdigest(),
            normalized={"target_id": selection["target_id"]},
            raw_response={"jev": selection},
            model={"jev": self.jev.settings.model_dump()},
            rendered_system="",
            rendered_user="",
            prompt_hash="",
            context_hash="",
            schema_hash="",
            cache_hit=bool(calls) and all(c["cache_hit"] for c in calls),
        )

    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        # Retry attribution and quote-length failures, never unrelated contract errors.
        # Each attempt uses the same source pool and native Skill; only feedback changes.
        if self.jev and request.output_kind == "match":
            # Jev's selection is the match decision; no generative explanation follows it.
            raise JudgmentError("Jev match decisions use vote(), not a generative judgment")
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
        skill_ref = request.skill_ref
        skill_path = self.skill_root / skill_ref if skill_ref else None
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
            return result

        validation_request = request
        options = paragraph_options(request.context) if request.output_kind == "match" else None
        labels = options[1] if options else {}

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

        normalized = api_normalized
        if labels and api_normalized.get("target_id") is not None:
            by_label = {label: key for key, label in labels.items()}
            if api_normalized["target_id"] not in by_label:
                raise JudgmentError("Returned an unknown paragraph comparison label")
            normalized = {**api_normalized, "target_id": by_label[api_normalized["target_id"]]}
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
            if labels:
                # Repair messages must describe only the visible options, by their wire labels.
                candidates = [
                    {**c, "selection_id": labels[candidate_handle(c)]}
                    for c in validation_request.context["candidates"]
                ]
                validation_request = validation_request.model_copy(
                    update={
                        "context": {**validation_request.context, "candidates": candidates},
                        "allowed_match_ids": [candidate_handle(c) for c in candidates],
                    }
                )
            self._validate(validation_request, api_normalized)
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
                        error=error, response=json.dumps(api_normalized, ensure_ascii=False)
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
        if payload["jev"] and request.output_kind != "match":
            # Long context changes only Jev answers; Claude's roles keep their cache entries.
            payload["jev"].pop("long_context_retry", None)
        if self.jev and request.output_kind == "match":
            phases = (
                ("has_match", "match") if len(request.allowed_match_ids) > 1 else ("has_match",)
            )
            payload["jev_requests"] = [
                hashlib.sha256(
                    encode_request(self.jev.build_request(request.context, phase))
                ).hexdigest()
                for phase in phases
            ]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validate(request: JudgmentRequest, value: dict) -> None:
        if request.output_kind == "role_statement":
            if not isinstance(value, dict) or set(value) != {ROLE_FIELD}:
                raise JudgmentError(f"{request.key} requires exactly {ROLE_FIELD}")
            role_statement = value.get(ROLE_FIELD)
            if not is_role_statement(role_statement):
                raise JudgmentError(
                    f"{request.key} requires one nonempty declarative role statement"
                )
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
