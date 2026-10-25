"""Provider selection and call limits saved with each run's configuration."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: Literal["anthropic", "openai"] = "anthropic"
    name: str = "claude-sonnet-5"
    max_tokens: int = Field(default=1024, gt=0)
    effort: Literal["low", "medium", "high"] = "low"
    thinking: Literal["disabled", "adaptive"] = "disabled"
    max_input_tokens: int = Field(default=200_000, gt=0)
    max_prompt_characters: int = Field(default=500_000, gt=0)
    context_management_trigger_tokens: int = Field(default=50_000, gt=0)
    max_api_responses_per_process: int = Field(default=200, gt=0)
    max_session_input_tokens: int = Field(default=2_000_000, gt=0)
    max_session_output_tokens: int = Field(default=100_000, gt=0)

    def result_settings(self) -> dict:
        """Exclude stop-only guards, not settings that affect generated content."""
        return self.model_dump(
            exclude={
                "max_input_tokens",
                "max_prompt_characters",
                "max_api_responses_per_process",
                "max_session_input_tokens",
                "max_session_output_tokens",
            }
        )

    @model_validator(mode="after")
    def validate_selection(self) -> "ModelSettings":
        if not self.name or self.name.strip() != self.name:
            raise ValueError("Model name must be non-empty with no surrounding whitespace")
        if self.provider == "openai" and self.name.startswith("claude-"):
            raise ValueError("Select an OpenAI model explicitly when provider is openai")
        return self
