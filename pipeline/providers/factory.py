"""Choose a transport; application code depends only on SkillClient."""

from pathlib import Path

from .contracts import SkillClient, SkillSessionBudget


def create_skill_client(
    repo_root: Path,
    state_path: Path,
    model: str,
    *,
    provider: str = "anthropic",
    session_budget: SkillSessionBudget | None = None,
    response_dir: Path | None = None,
) -> SkillClient:
    if provider == "anthropic":
        from .anthropic import ClaudeSkills

        return ClaudeSkills(
            repo_root, state_path, model, session_budget=session_budget, response_dir=response_dir
        )
    if provider == "openai":
        from .openai import OpenAISkills

        return OpenAISkills(
            repo_root,
            state_path.with_name(f"{state_path.stem}-openai{state_path.suffix}"),
            model,
            session_budget=session_budget,
            response_dir=response_dir or state_path.parent / "openai-responses",
        )
    raise ValueError(f"Unsupported provider: {provider}")
