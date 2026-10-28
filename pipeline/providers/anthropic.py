"""Shared Claude Skill transport for source extraction and graph judgments."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Iterable

from ..prompts import request_prompts
from .contracts import (
    RunResult,
    SkillBudgetExceeded,
    SkillCallPolicy,
    SkillRef,
    SkillSessionBudget,
)
from .limits import SessionLimits
from .registry import SkillRegistry, load_api_key
from .responses import parse_json, save_response, usage_record, without_constraints

MESSAGE_BETAS = [
    "code-execution-2025-08-25",
    "files-api-2025-04-14",
    "structured-outputs-2025-11-13",
    "context-management-2025-06-27",
]
FILE_BETAS = ["files-api-2025-04-14"]
CODE_EXECUTION_TOOL = {
    "type": "code_execution_20250825",
    "name": "code_execution",
}
FIVE_MINUTE_CACHE = {"type": "ephemeral"}
# Batch calls are adjacent, so the default five-minute TTL avoids pricier
# one-hour writes while still enabling server-tool-result caching.
CACHEABLE_SYSTEM = [
    {
        "type": "text",
        "text": request_prompts("providers")["anthropic"],
        "cache_control": FIVE_MINUTE_CACHE,
    }
]
API_TIMEOUT_SECONDS = 30 * 60


class ClaudeSkills(SessionLimits):
    def __init__(
        self,
        repo_root: Path,
        state_path: Path,
        model: str,
        *,
        session_budget: SkillSessionBudget | None = None,
        response_dir: Path | None = None,
    ) -> None:
        from anthropic import Anthropic

        super().__init__(session_budget)
        self.model = model
        self.response_dir = response_dir or state_path.parent / "responses"
        api_key = load_api_key(repo_root, "ANTHROPIC_API_KEY")
        self.client = Anthropic(
            api_key=api_key,
            timeout=API_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self.registry = SkillRegistry(repo_root, state_path, api_key)

    def register(self, skill_path: Path) -> SkillRef:
        return self.registry.register(skill_path, self._upload_skill)

    def _upload_skill(self, skill_path: Path, previous: SkillRef | None) -> tuple[str, str]:
        from anthropic.lib import files_from_dir

        files = files_from_dir(skill_path)
        if previous:
            try:
                response = self.client.beta.skills.versions.create(previous.skill_id, files=files)
                skill_id = previous.skill_id
                version = response.id
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise
                response = self.client.beta.skills.create(files=files)
                skill_id = response.id
                version = response.latest_version_id
        else:
            response = self.client.beta.skills.create(files=files)
            skill_id = response.id
            version = response.latest_version_id
        return skill_id, version

    def run_json(
        self,
        skills: Iterable[SkillRef],
        prompt: str,
        schema: dict[str, Any],
        *,
        policy: SkillCallPolicy,
        cacheable_prompt: str | None = None,
        cacheable_context: str | None = None,
    ) -> RunResult:
        self._validate_prompt(prompt, policy, cacheable_prompt, cacheable_context)
        content = _prompt_content(prompt, cacheable_prompt, cacheable_context)
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        return self._run_structured(skills, messages, schema, policy)

    def run_json_file(
        self,
        skill: SkillRef,
        prompt: str,
        input_path: Path,
        schema: dict[str, Any],
        *,
        policy: SkillCallPolicy,
        cacheable_prompt: str | None = None,
    ) -> RunResult:
        """Run a Skill over one attachment and return schema-constrained JSON."""

        self._validate_prompt(prompt, policy, cacheable_prompt)
        self._validate_attachment(input_path, policy)
        self._check_session_budget()
        uploaded = self.client.beta.files.upload(file=input_path, betas=FILE_BETAS)
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        *_prompt_content(prompt, cacheable_prompt),
                        {"type": "container_upload", "file_id": uploaded.id},
                    ],
                }
            ]
            return self._run_structured([skill], messages, schema, policy)
        finally:
            try:
                self.client.beta.files.delete(uploaded.id, betas=FILE_BETAS)
            except Exception as error:
                warnings.warn(
                    f"Could not delete temporary Anthropic file {uploaded.id}: {error}",
                    RuntimeWarning,
                    stacklevel=2,
                )

    def _run_structured(
        self,
        skills: Iterable[SkillRef],
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        policy: SkillCallPolicy,
    ) -> RunResult:
        response, usage = self._run(skills, messages, policy=policy, schema=schema)
        # Earlier text belongs to intermediate server-tool iterations, not the answer.
        boundary = max(
            (
                i
                for i, block in enumerate(response.content)
                if getattr(block, "type", "") == "server_tool_use"
                or getattr(block, "type", "").endswith("_tool_result")
            ),
            default=-1,
        )
        text = "".join(
            block.text
            for block in response.content[boundary + 1 :]
            if getattr(block, "type", "") == "text"
        )
        if not text.strip():
            raise RuntimeError(f"Claude response {response.id} contained no structured text output")
        value = parse_json(text, schema, response.id)
        return self._result(
            response,
            value,
            usage=usage,
            policy=policy,
            raw_text=text,
        )

    def _run(
        self,
        skills: Iterable[SkillRef],
        messages: list[dict[str, Any]],
        *,
        policy: SkillCallPolicy,
        schema: dict[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        skill_values = [
            {"type": "custom", "skill_id": skill.skill_id, "version": skill.version}
            for skill in skills
        ]
        self._check_session_budget()
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=policy.max_tokens,
            betas=MESSAGE_BETAS,
            container={"skills": skill_values},
            system=CACHEABLE_SYSTEM,
            messages=messages,
            tools=[CODE_EXECUTION_TOOL],
            thinking={"type": policy.thinking},
            output_config={
                "effort": policy.effort,
                "format": {
                    "type": "json_schema",
                    "schema": without_constraints(schema, {"minimum", "minLength"}),
                },
            },
            context_management={
                "edits": [
                    {
                        "type": "clear_tool_uses_20250919",
                        "trigger": {
                            "type": "input_tokens",
                            "value": policy.context_management_trigger_tokens,
                        },
                        "keep": {"type": "tool_uses", "value": 2},
                        "clear_at_least": {"type": "input_tokens", "value": 10_000},
                        "clear_tool_inputs": True,
                    }
                ]
            },
        )
        response_usage = response.usage.model_dump(mode="json") if response.usage else {}
        # Persist paid evidence before any budget, stop-reason, or JSON rejection.
        save_response(
            getattr(self, "response_dir", None),
            provider="anthropic",
            response=response.model_dump(mode="json"),
            usage=response_usage,
            policy=policy,
            schema=schema,
            messages=messages,
            input_tokens=_input_token_volume(response_usage),
        )
        self._record_session_usage(
            _input_token_volume(response_usage),
            int(response_usage.get("output_tokens") or 0),
            response.id,
        )
        usage = usage_record(response.id, response_usage, self.session_usage)
        input_tokens = _input_token_volume(usage)
        if policy.max_input_tokens is not None and input_tokens > policy.max_input_tokens:
            raise SkillBudgetExceeded(
                f"Claude Skill response reported {input_tokens:,} aggregate input-usage tokens "
                f"(uncached={response_usage.get('input_tokens', 0):,}, "
                f"cache_write={response_usage.get('cache_creation_input_tokens', 0):,}, "
                f"cache_read={response_usage.get('cache_read_input_tokens', 0):,}); "
                f"usage guard is {policy.max_input_tokens:,}, not a context-window limit. "
                "No output was accepted; the paid response is retained when response storage is configured.",
                response_id=response.id,
                usage=usage,
            )
        if response.stop_reason == "pause_turn":
            raise SkillBudgetExceeded(
                f"Claude response {response.id} paused before completing. The adapter never "
                "sends a follow-up turn; simplify or split the task before retrying.",
                response_id=response.id,
                usage=usage,
            )
        if response.stop_reason not in {"end_turn", "stop_sequence"}:
            if response.stop_reason == "max_tokens":
                raise SkillBudgetExceeded(
                    f"Claude response {response.id} reached the {policy.max_tokens}-token "
                    "output limit",
                    response_id=response.id,
                    usage=usage,
                )
            raise RuntimeError(f"Claude response {response.id} stopped with {response.stop_reason}")
        return response, usage

    @staticmethod
    def _result(
        response: Any,
        value: Any = None,
        *,
        usage: dict[str, Any] | None = None,
        policy: SkillCallPolicy | None = None,
        raw_text: str | None = None,
    ) -> RunResult:
        container_id = getattr(getattr(response, "container", None), "id", None)
        return RunResult(
            response.id,
            response.stop_reason,
            usage or {},
            container_id,
            value,
            raw_text,
            response.model_dump(mode="json"),
            policy.as_dict() if policy else None,
        )


def _prompt_content(
    prompt: str, cacheable_prompt: str | None, cacheable_context: str | None = None
) -> list[dict[str, Any]]:
    """Cache instructions and evidence before the changing focus in one user turn."""

    content: list[dict[str, Any]] = []
    for prefix in (cacheable_prompt, cacheable_context):
        if prefix:
            content.append(
                {
                    "type": "text",
                    "text": prefix,
                    "cache_control": FIVE_MINUTE_CACHE,
                }
            )
    content.append({"type": "text", "text": prompt})
    return content


def _input_token_volume(usage: dict[str, Any]) -> int:
    return sum(
        int(usage.get(field) or 0)
        for field in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    )
