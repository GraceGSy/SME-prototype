"""Shared Claude Skill transport for source extraction and graph judgments."""

from __future__ import annotations

import hashlib
import json
import os
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from jsonschema import Draft202012Validator, ValidationError

from ..files import directory_hash, write_json

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
        "text": (
            "Use the configured Agent Skill on the complete input in the user message. "
            "Finish within this single Messages API request and return only the "
            "schema-constrained result."
        ),
        "cache_control": FIVE_MINUTE_CACHE,
    }
]
API_TIMEOUT_SECONDS = 30 * 60


class SkillBudgetExceeded(RuntimeError):
    """Raised when a request bound or observed-usage limit is reached."""

    def __init__(
        self,
        message: str,
        *,
        response_id: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.response_id = response_id
        self.usage = usage or {}


@dataclass(frozen=True)
class SkillCallPolicy:
    """Request bounds and post-response usage guards; not a guaranteed spend cap."""

    max_tokens: int
    effort: Literal["low", "medium", "high"] = "low"
    thinking: Literal["disabled", "adaptive"] = "disabled"
    max_input_tokens: int = 200_000
    max_prompt_characters: int = 500_000
    max_attachment_bytes: int = 500_000
    context_management_trigger_tokens: int = 50_000

    def __post_init__(self) -> None:
        positive = {
            "max_tokens": self.max_tokens,
            "max_input_tokens": self.max_input_tokens,
            "max_prompt_characters": self.max_prompt_characters,
            "max_attachment_bytes": self.max_attachment_bytes,
            "context_management_trigger_tokens": self.context_management_trigger_tokens,
        }
        invalid = [name for name, value in positive.items() if value <= 0]
        if invalid:
            raise ValueError(f"Skill call limits must be positive: {', '.join(invalid)}")

    def output_config(self, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "effort": self.effort,
            "format": {"type": "json_schema", "schema": schema},
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkillSessionBudget:
    """Process-local ceiling across many individually bounded Skill calls."""

    max_api_responses: int = 100
    max_input_tokens: int = 2_000_000
    max_output_tokens: int = 100_000

    def __post_init__(self) -> None:
        if (
            min(
                self.max_api_responses,
                self.max_input_tokens,
                self.max_output_tokens,
            )
            <= 0
        ):
            raise ValueError("Skill session budget values must be positive")


@dataclass(frozen=True)
class SkillRef:
    path: str
    skill_id: str
    version: str
    source_sha256: str

    def api_value(self) -> dict[str, str]:
        return {"type": "custom", "skill_id": self.skill_id, "version": self.version}


@dataclass(frozen=True)
class RunResult:
    response_id: str
    stop_reason: str
    usage: dict[str, Any]
    container_id: str | None
    value: Any = None
    raw_text: str | None = None
    raw_response: dict[str, Any] | None = None
    call_policy: dict[str, Any] | None = None


def load_api_key(repo_root: Path) -> str:
    """Load the API key without copying it into pipeline output or logs."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key

    for directory in [repo_root, *repo_root.parents]:
        env_path = directory / ".env"
        if not env_path.exists():
            continue
        values: dict[str, str] = {}
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip("\"'")
        key = values.get("ANTHROPIC_API_KEY")
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
            return key
    raise RuntimeError("No ANTHROPIC_API_KEY was found in the environment or an ancestor .env")


def _credential_registry(
    state: dict[str, Any],
    api_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the current registry only; legacy caches must be discarded explicitly."""

    skill_record = {
        "type": "object",
        "additionalProperties": False,
        "required": ["skill_id", "version", "source_sha256"],
        "properties": {
            "skill_id": {"type": "string", "minLength": 1},
            "version": {"type": "string", "minLength": 1},
            "source_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        },
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "accounts"],
        "properties": {
            "schema_version": {"const": 1},
            "accounts": {
                "type": "object",
                "propertyNames": {"pattern": "^[a-f0-9]{64}$"},
                "additionalProperties": {"type": "object", "additionalProperties": skill_record},
            },
        },
    }
    try:
        Draft202012Validator(schema).validate(state)
    except ValidationError as error:
        raise ValueError(
            "Unsupported or malformed Skill registry; discard this cache explicitly"
        ) from error
    credential_id = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return state, state["accounts"].setdefault(credential_id, {})


class ClaudeSkills:
    def __init__(
        self,
        repo_root: Path,
        state_path: Path,
        model: str,
        *,
        session_budget: SkillSessionBudget | None = None,
    ) -> None:
        from anthropic import Anthropic

        self.repo_root = repo_root
        self.state_path = state_path
        self.model = model
        api_key = load_api_key(repo_root)
        self.client = Anthropic(
            api_key=api_key,
            timeout=API_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self.session_budget = session_budget or SkillSessionBudget()
        self.session_usage = {
            "api_responses": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        stored_state = (
            json.loads(state_path.read_text(encoding="utf-8"))
            if state_path.exists()
            else {"schema_version": 1, "accounts": {}}
        )
        self.state_document, self.state = _credential_registry(stored_state, api_key)

    def register(self, skill_path: Path) -> SkillRef:
        from anthropic.lib import files_from_dir

        skill_path = skill_path.resolve()
        relative = skill_path.relative_to(self.repo_root).as_posix()
        fingerprint = directory_hash(skill_path)
        existing = self.state.get(relative)
        if existing and existing.get("source_sha256") == fingerprint:
            return SkillRef(relative, existing["skill_id"], existing["version"], fingerprint)

        files = files_from_dir(skill_path)
        if existing:
            try:
                response = self.client.beta.skills.versions.create(
                    existing["skill_id"], files=files
                )
                skill_id = existing["skill_id"]
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
        size = input_path.stat().st_size
        if size > policy.max_attachment_bytes:
            raise SkillBudgetExceeded(
                f"Attachment {input_path.name} is {size} bytes; configured maximum is "
                f"{policy.max_attachment_bytes}"
            )
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
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        if not text.strip():
            raise RuntimeError(f"Claude response {response.id} contained no structured text output")
        value = json.loads(text)
        try:
            Draft202012Validator(schema).validate(value)
        except ValidationError as error:
            raise ValueError(
                f"Claude response {response.id} violates the requested schema"
            ) from error
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
        skill_values = [skill.api_value() for skill in skills]
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
            output_config=policy.output_config(schema),
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
        self._record_session_usage(response_usage, response.id)
        usage = _single_response_usage(response.id, response_usage)
        usage["session"] = dict(self.session_usage)
        input_tokens = _input_token_volume(usage)
        if input_tokens > policy.max_input_tokens:
            raise SkillBudgetExceeded(
                f"Claude Skill call used {input_tokens:,} input tokens; configured "
                f"maximum is {policy.max_input_tokens:,}. No output was accepted.",
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
    def _validate_prompt(
        prompt: str,
        policy: SkillCallPolicy,
        cacheable_prompt: str | None = None,
        cacheable_context: str | None = None,
    ) -> None:
        total_characters = len(prompt) + len(cacheable_prompt or "") + len(cacheable_context or "")
        if total_characters > policy.max_prompt_characters:
            raise SkillBudgetExceeded(
                f"Skill prompt is {total_characters} characters; configured maximum is "
                f"{policy.max_prompt_characters}"
            )

    def _check_session_budget(self) -> None:
        if (
            self.session_usage["api_responses"] >= self.session_budget.max_api_responses
            or self.session_usage["input_tokens"] >= self.session_budget.max_input_tokens
            or self.session_usage["output_tokens"] >= self.session_budget.max_output_tokens
        ):
            raise SkillBudgetExceeded(
                "Skill process reached its response or observed-token limit",
                usage={"session": dict(self.session_usage)},
            )

    def _record_session_usage(self, usage: dict[str, Any], response_id: str) -> None:
        self.session_usage["api_responses"] += 1
        self.session_usage["input_tokens"] += _input_token_volume(usage)
        self.session_usage["output_tokens"] += int(usage.get("output_tokens") or 0)
        if (
            self.session_usage["input_tokens"] > self.session_budget.max_input_tokens
            or self.session_usage["output_tokens"] > self.session_budget.max_output_tokens
        ):
            raise SkillBudgetExceeded(
                "Skill process exceeded its cumulative token budget after response "
                f"{response_id}: {self.session_usage['input_tokens']:,} input and "
                f"{self.session_usage['output_tokens']:,} output tokens",
                response_id=response_id,
                usage={"session": dict(self.session_usage)},
            )

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


def _single_response_usage(response_id: str, usage: dict[str, Any]) -> dict[str, Any]:
    """Keep raw billing fields and make the one-request contract explicit."""

    return {
        **usage,
        "request_count": 1,
        "responses": [{"response_id": response_id, "usage": usage}],
    }


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
