"""Shared preflight checks and observed usage limits for provider transports."""

from .contracts import SkillBudgetExceeded, SkillCallPolicy, SkillSessionBudget


class SessionLimits:
    session_budget: SkillSessionBudget
    session_usage: dict[str, int]

    @staticmethod
    def _validate_prompt(
        prompt: str,
        policy: SkillCallPolicy,
        cacheable_prompt: str | None = None,
        cacheable_context: str | None = None,
    ) -> None:
        total = len(prompt) + len(cacheable_prompt or "") + len(cacheable_context or "")
        if total > policy.max_prompt_characters:
            raise SkillBudgetExceeded(
                f"Skill prompt is {total} characters; configured maximum is "
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

    def _record_session_usage(
        self, input_tokens: int, output_tokens: int, response_id: str
    ) -> None:
        self.session_usage["api_responses"] += 1
        self.session_usage["input_tokens"] += input_tokens
        self.session_usage["output_tokens"] += output_tokens
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
