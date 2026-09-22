"""Transport contracts. No SDK, graph logic, or provider wire formats."""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Protocol

from jsonschema import ValidationError


class StructuredOutputValidationError(ValueError):
    """Expose schema failures so callers can retry only explicitly allowed errors."""

    def __init__(self, response_id: str, errors: list[ValidationError]) -> None:
        super().__init__(f"Model response {response_id} violates the requested schema")
        self.errors = errors


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


class SkillClient(Protocol):
    def register(self, skill_path: Path) -> SkillRef: ...

    def run_json(
        self,
        skills: Iterable[SkillRef],
        prompt: str,
        schema: dict[str, Any],
        *,
        policy: SkillCallPolicy,
        cacheable_prompt: str | None = None,
        cacheable_context: str | None = None,
    ) -> RunResult: ...

    def run_json_file(
        self,
        skill: SkillRef,
        prompt: str,
        input_path: Path,
        schema: dict[str, Any],
        *,
        policy: SkillCallPolicy,
        cacheable_prompt: str | None = None,
    ) -> RunResult: ...
