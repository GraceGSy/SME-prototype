"""Observed Sonnet 5 token costs for the HCI and Sherlock run helpers.

Rates verified 2026-09-09 against https://platform.claude.com/docs/en/about-claude/pricing.
Not an invoice: native tool fees and usage never returned by the provider are unknown.
"""

from pathlib import Path

from pipeline.files import read_json
from pipeline.providers.contracts import SkillBudgetExceeded


def token_cost(usage):
    writes = usage.get("cache_creation") or {}
    hour = writes.get("ephemeral_1h_input_tokens") or 0
    total_writes = usage.get("cache_creation_input_tokens") or 0
    return (
        (usage.get("input_tokens") or 0) * 2
        + (total_writes - hour) * 2.5
        + hour * 4
        + (usage.get("cache_read_input_tokens") or 0) * 0.2
        + (usage.get("output_tokens") or 0) * 10
    ) / 1_000_000


class ResponseLedger:
    """Count each saved paid response once, including rejected judgments."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.seen: set[str] = set()
        self.spent = 0.0
        self.refresh()

    def refresh(self):
        for path in sorted(self.directory.glob("*.json")):
            if path.name in self.seen:
                continue
            data = read_json(path)
            usage = data.get("usage")
            if not isinstance(usage, dict) or any(
                type(usage.get(field)) is not int or usage[field] < 0
                for field in ("input_tokens", "output_tokens")
            ):
                raise ValueError(f"Missing billing usage in {path.name}; reconcile before resuming")
            for field in ("cache_creation_input_tokens", "cache_read_input_tokens"):
                value = usage.get(field)
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError(f"Invalid {field} in {path.name}")
            writes = usage.get("cache_creation") or {}
            hour = writes.get("ephemeral_1h_input_tokens") or 0
            if type(hour) is not int or not 0 <= hour <= (
                usage.get("cache_creation_input_tokens") or 0
            ):
                raise ValueError(f"Invalid one-hour cache usage in {path.name}")
            self.spent += token_cost(usage)
            self.seen.add(path.name)

    def require_headroom(self, budget: float, reserve: float):
        self.refresh()
        if self.spent + reserve >= budget:
            raise SkillBudgetExceeded(
                f"Token estimate ${self.spent:.2f} leaves less than ${reserve:.2f} reserve within ${budget:.2f}; stopped before next call"
            )
