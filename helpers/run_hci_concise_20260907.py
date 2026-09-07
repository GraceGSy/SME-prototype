"""Budgeted fresh HCI experiment using normal start/add/retry, not recovery replay.

Token estimates use Sonnet 5 standard rates; $17 stop threshold leaves $2 for
in-flight uncertainty and tool fees. This is not a provider-enforced dollar cap.
"""

import argparse
from pathlib import Path
from unittest.mock import patch

from pipeline.files import read_json, write_json
from pipeline.incremental_graph.runs import add_papers, retry_graph, start_graph
from pipeline.llm.client import ClaudeSkills, SkillBudgetExceeded

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/hci-concise-fresh-20260907"
CONTENT = ROOT / "datasets/hci-five-paper/content"


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


def run(action):
    spent = sum(token_cost(read_json(p)["usage"]) for p in (RUN / "cache/responses").glob("*.json"))
    if action == "add" and spent > 9:
        raise ValueError(
            "Less than $10 of the original $19 remains; review before adding Examplore"
        )
    original = ClaudeSkills._run

    def bounded(client, *args, **kwargs):
        nonlocal spent
        if client.model != "claude-sonnet-5":
            raise ValueError("Budget rates apply only to claude-sonnet-5")
        if spent >= 17:
            raise SkillBudgetExceeded(
                "Experiment reached its $17 estimated token-cost stop threshold"
            )
        usage = {}
        try:
            response, usage = original(client, *args, **kwargs)
            return response, usage
        except SkillBudgetExceeded as error:
            usage = error.usage
            raise
        finally:
            spent += token_cost(usage)
            write_json(
                RUN / "budget.json",
                {
                    "estimated_token_cost_usd": spent,
                    "stop_threshold_usd": 17,
                    "original_balance_usd": 19,
                    "excludes": "tool charges and unreported usage",
                },
            )

    with patch.object(ClaudeSkills, "_run", bounded):
        if action == "start":
            result = start_graph(CONTENT / "first-two.manifest.yaml", RUN)
        elif action == "add":
            result = add_papers(CONTENT / "third.manifest.yaml", RUN)
        else:
            result = retry_graph(RUN)
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "add", "retry"])
    run(parser.parse_args().action)
