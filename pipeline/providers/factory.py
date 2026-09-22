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
    if provider != "anthropic":
        raise ValueError(f"Unsupported provider: {provider}")
    from .anthropic import ClaudeSkills

    return ClaudeSkills(
        repo_root, state_path, model, session_budget=session_budget, response_dir=response_dir
    )
