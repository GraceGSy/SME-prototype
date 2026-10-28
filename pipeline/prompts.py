"""Locations and loading for the repository's model-facing prompt assets."""

from pathlib import Path

from .files import read_json

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_ROOT = REPO_ROOT / "prompts"
REQUEST_PROMPT_ROOT = PROMPT_ROOT / "requests"


def request_prompts(name: str) -> dict[str, str]:
    return read_json(REQUEST_PROMPT_ROOT / f"{name}.json")
