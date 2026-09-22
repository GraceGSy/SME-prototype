"""Budgeted fresh HCI experiment using normal start/add/retry, not recovery replay.

Token estimates use Sonnet 5 standard rates; $17 stop threshold leaves $2 for
in-flight uncertainty and tool fees. This is not a provider-enforced dollar cap.
"""

import argparse
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from helpers.usage_budget import token_cost
from pipeline.files import read_json, write_json
from pipeline.incremental_graph.runs import add_papers, retry_graph, start_graph
from pipeline.providers.anthropic import ClaudeSkills, SkillBudgetExceeded, SkillCallPolicy

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/hci-concise-fresh-20260907"
CONTENT = ROOT / "datasets/hci-five-paper/content"


def extension_policy(policy: SkillCallPolicy) -> SkillCallPolicy:
    """Allow aggregate native-Skill usage across iterations, not a larger prompt.

    Paralib's complete deduplicated pool produced 219,217 input-usage tokens,
    97.5% cache reads, with a normal 290-token response. Keep prompt/output
    limits and the separate dollar guard unchanged. Raw responses record this
    effective guard; saved run configuration remains intact for cache reuse.
    """
    if policy.max_input_tokens == 200_000:
        return replace(policy, max_input_tokens=300_000)
    return policy


def run(action):
    spent = sum(token_cost(read_json(p)["usage"]) for p in (RUN / "cache/responses").glob("*.json"))
    authorization_path = RUN / "remaining-two-budget.json"
    if action == "add-remaining":
        state = read_json(RUN / "run.json")
        if state["latest_revision"] != state["current_revision"]:
            raise ValueError("Retry the unfinished revision before adding papers")
        summary = read_json(RUN / "revisions" / state["current_revision"] / "summary.json")
        if summary["paper_order"] != ["abstractexplorer", "corpusstudio", "examplore_chi18"]:
            raise ValueError("Expected exactly the completed first three HCI papers")
        if not authorization_path.exists():
            write_json(
                authorization_path,
                {
                    "baseline_token_cost_usd": spent,
                    "reported_available_balance_usd": 25,
                    "additional_token_allowance_usd": 23,
                    "stop_threshold_usd": spent + 23,
                    "authorization": "User approved the remaining two HCI papers with $25 available",
                },
            )
    stop_threshold = (
        read_json(authorization_path)["stop_threshold_usd"] if authorization_path.exists() else 17
    )
    if action == "add" and spent > 9:
        raise ValueError(
            "Less than $10 of the original $19 remains; review before adding Examplore"
        )
    original = ClaudeSkills._run

    def bounded(client, *args, **kwargs):
        nonlocal spent
        if client.model != "claude-sonnet-5":
            raise ValueError("Budget rates apply only to claude-sonnet-5")
        if spent >= stop_threshold:
            raise SkillBudgetExceeded(
                f"Experiment reached its ${stop_threshold:.2f} cumulative estimated token-cost stop threshold"
            )
        usage = {}
        if authorization_path.exists():
            kwargs["policy"] = extension_policy(kwargs["policy"])
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
                    "stop_threshold_usd": stop_threshold,
                    "original_balance_usd": 19,
                    "excludes": "tool charges and unreported usage",
                },
            )

    with patch.object(ClaudeSkills, "_run", bounded):
        if action == "start":
            result = start_graph(CONTENT / "first-two.manifest.yaml", RUN)
        elif action == "add":
            result = add_papers(CONTENT / "third.manifest.yaml", RUN)
        elif action == "add-remaining":
            result = add_papers(CONTENT / "remaining-two.manifest.yaml", RUN)
        else:
            result = retry_graph(RUN)
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "add", "add-remaining", "retry"])
    run(parser.parse_args().action)
