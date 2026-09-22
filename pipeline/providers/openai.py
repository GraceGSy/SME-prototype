"""OpenAI Responses transport using native Skills and hosted shell execution."""

from __future__ import annotations

import json
import mimetypes
import warnings
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from jsonschema import Draft202012Validator

from ..files import directory_hash, write_json
from .contracts import (
    RunResult,
    SkillBudgetExceeded,
    SkillCallPolicy,
    SkillRef,
    SkillSessionBudget,
    StructuredOutputValidationError,
)
from .limits import SessionLimits
from .registry import _credential_registry, load_api_key
from .schemas import without_constraints

INSTRUCTIONS = (
    "Use the configured Agent Skill on the complete input in the user message. "
    "Read its SKILL.md and relevant supporting files using the hosted shell. "
    "Finish within this single Responses API request and return only the "
    "schema-constrained result."
)


class OpenAISkills(SessionLimits):
    def __init__(
        self,
        repo_root: Path,
        state_path: Path,
        model: str,
        *,
        session_budget: SkillSessionBudget | None = None,
        response_dir: Path | None = None,
    ) -> None:
        from openai import OpenAI

        self.repo_root = repo_root
        self.state_path = state_path
        self.model = model
        self.response_dir = response_dir or state_path.parent / "responses"
        api_key = load_api_key(repo_root, "OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key, timeout=30 * 60, max_retries=0)
        self.session_budget = session_budget or SkillSessionBudget()
        self.session_usage = {"api_responses": 0, "input_tokens": 0, "output_tokens": 0}
        stored_state = (
            json.loads(state_path.read_text(encoding="utf-8"))
            if state_path.exists()
            else {"schema_version": 1, "accounts": {}}
        )
        self.state_document, self.state = _credential_registry(stored_state, api_key)

    def register(self, skill_path: Path) -> SkillRef:
        skill_path = skill_path.resolve()
        relative = skill_path.relative_to(self.repo_root).as_posix()
        fingerprint = directory_hash(skill_path)
        existing = self.state.get(relative)
        if existing and existing["source_sha256"] == fingerprint:
            return SkillRef(relative, existing["skill_id"], existing["version"], fingerprint)

        # Multipart paths retain the single top-level skill folder and supporting files.
        files = [
            (
                path.relative_to(skill_path.parent).as_posix(),
                path.read_bytes(),
                mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
            for path in sorted(skill_path.rglob("*"))
            if path.is_file()
        ]
        if existing:
            response = self.client.skills.versions.create(existing["skill_id"], files=files)
            skill_id, version = existing["skill_id"], response.version
        else:
            response = self.client.skills.create(files=files)
            skill_id, version = response.id, response.latest_version
        if not version:
            raise RuntimeError(f"Skills API did not return a version for {relative}")
        self.state[relative] = {
            "skill_id": skill_id,
            "version": version,
            "source_sha256": fingerprint,
        }
        write_json(self.state_path, self.state_document)
        return SkillRef(relative, skill_id, version, fingerprint)

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
        return self._run(skills, content, schema, policy)

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
        self._validate_prompt(prompt, policy, cacheable_prompt)
        size = input_path.stat().st_size
        if size > policy.max_attachment_bytes:
            raise SkillBudgetExceeded(
                f"Attachment {input_path.name} is {size} bytes; configured maximum is "
                f"{policy.max_attachment_bytes}"
            )
        self._check_session_budget()
        uploaded = self.client.files.create(file=input_path, purpose="user_data")
        try:
            return self._run(
                [skill],
                _prompt_content(prompt, cacheable_prompt),
                schema,
                policy,
                file_ids=[uploaded.id],
            )
        finally:
            try:
                self.client.files.delete(uploaded.id)
            except Exception as error:
                warnings.warn(
                    f"Could not delete temporary OpenAI file {uploaded.id}: {error}",
                    RuntimeWarning,
                    stacklevel=2,
                )

    def _run(
        self,
        skills: Iterable[SkillRef],
        content: list[dict[str, Any]],
        schema: dict[str, Any],
        policy: SkillCallPolicy,
        *,
        file_ids: list[str] | None = None,
    ) -> RunResult:
        self._check_session_budget()
        api_schema = without_constraints(schema, {"minLength", "maxLength"})
        wrapped = schema.get("type") != "object"
        # Responses requires an object root; extraction's canonical result is an array.
        if wrapped:
            api_schema = {
                "type": "object",
                "properties": {"result": api_schema},
                "required": ["result"],
                "additionalProperties": False,
            }
        environment = {
            "type": "container_auto",
            "network_policy": {"type": "disabled"},
            "skills": [
                {"type": "skill_reference", "skill_id": skill.skill_id, "version": skill.version}
                for skill in skills
            ],
        }
        if file_ids:
            environment["file_ids"] = file_ids
        messages = [{"role": "user", "content": content}]
        response = self.client.responses.create(
            model=self.model,
            instructions=INSTRUCTIONS
            + (
                " Put the Skill's canonical result in the required result field." if wrapped else ""
            ),
            input=messages,
            tools=[{"type": "shell", "environment": environment}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "result",
                    "strict": True,
                    "schema": api_schema,
                }
            },
            reasoning={"effort": policy.effort if policy.thinking == "adaptive" else "none"},
            max_output_tokens=policy.max_tokens,
            truncation="disabled",
            store=False,
            # The pinned SDK predates explicit cache controls, but preserves extra_body.
            extra_body={"prompt_cache_options": {"mode": "explicit", "ttl": "30m"}},
        )
        raw_response = response.model_dump(mode="json")
        raw_usage = response.usage.model_dump(mode="json") if response.usage else {}
        # OpenAI input_tokens already includes cache reads and writes. Do not add them again.
        input_tokens = int(raw_usage.get("input_tokens") or 0)
        write_json(
            self.response_dir / f"{uuid4().hex}.json",
            {
                "provider": "openai",
                "response": raw_response,
                "usage": raw_usage,
                "policy": policy.as_dict(),
                "schema": schema,
                "api_schema": api_schema,
                "messages": messages,
                "request_text_characters": sum(len(block["text"]) for block in content),
                "input_usage_tokens": input_tokens,
            },
        )
        self._record_session_usage(
            input_tokens, int(raw_usage.get("output_tokens") or 0), response.id
        )
        usage = {
            **raw_usage,
            "request_count": 1,
            "responses": [{"response_id": response.id, "usage": raw_usage}],
            "session": dict(self.session_usage),
        }
        if input_tokens > policy.max_input_tokens:
            raise SkillBudgetExceeded(
                f"OpenAI response {response.id} reported {input_tokens:,} input tokens; "
                f"usage guard is {policy.max_input_tokens:,}. The paid response is retained.",
                response_id=response.id,
                usage=usage,
            )
        if response.status == "incomplete":
            reason = (raw_response.get("incomplete_details") or {}).get("reason")
            raise SkillBudgetExceeded(
                f"OpenAI response {response.id} is incomplete: {reason}",
                response_id=response.id,
                usage=usage,
            )
        if response.status != "completed":
            raise RuntimeError(f"OpenAI response {response.id} stopped with {response.status}")
        # Intermediate commentary and tool output must never become the structured answer.
        boundary = max(
            (
                i
                for i, item in enumerate(response.output)
                if item.type not in {"message", "reasoning"}
            ),
            default=-1,
        )
        messages_out = [item for item in response.output[boundary + 1 :] if item.type == "message"]
        if not messages_out:
            raise RuntimeError(f"OpenAI response {response.id} contained no final message")
        blocks = [block for message in messages_out for block in message.content]
        if any(block.type == "refusal" for block in blocks):
            raise RuntimeError(f"OpenAI response {response.id} refused the requested output")
        text = "".join(block.text for block in blocks if block.type == "output_text")
        value = json.loads(text)
        wire_errors = list(Draft202012Validator(api_schema).iter_errors(value))
        if wire_errors:
            raise StructuredOutputValidationError(response.id, wire_errors) from wire_errors[0]
        if wrapped:
            value = value["result"]
        errors = list(Draft202012Validator(schema).iter_errors(value))
        if errors:
            raise StructuredOutputValidationError(response.id, errors) from errors[0]
        return RunResult(
            response.id,
            response.status,
            usage,
            None,
            value,
            text,
            raw_response,
            policy.as_dict(),
        )


def _prompt_content(
    prompt: str,
    cacheable_prompt: str | None,
    cacheable_context: str | None = None,
) -> list[dict[str, Any]]:
    content = []
    for prefix in (cacheable_prompt, cacheable_context):
        if prefix:
            content.append(
                {
                    "type": "input_text",
                    "text": prefix,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }
            )
    content.append({"type": "input_text", "text": prompt})
    return content
