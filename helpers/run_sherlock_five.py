"""Explicitly authorized five-story start/retry with a persistent observed-cost guard.

No automatic retries or policy changes. A failure is inspected before retry.
The reserve reduces overshoot risk, but cannot hard-cap server-side Skill costs.
"""

import argparse
import math
from pathlib import Path
from unittest.mock import patch

from helpers.usage_budget import ResponseLedger
from pipeline.files import read_json, write_json
from pipeline.incremental_graph.configuration import load_pipeline_config
from pipeline.incremental_graph.models import PipelineConfig
from pipeline.incremental_graph.runs import DEFAULT_CONFIG, retry_graph, start_graph
from pipeline.providers.anthropic import ClaudeSkills

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "datasets/sherlock/famous-five/manifest.yaml"
RUN = ROOT / "runs/sherlock-famous-five-20260909"
RESERVE_USD = 3.0


def sherlock_config() -> PipelineConfig:
    config = load_pipeline_config(DEFAULT_CONFIG)
    # Measured offline envelope; never an automatic escalation during retry.
    config.model.max_prompt_characters = 900_000
    config.model.max_input_tokens = 1_000_000
    config.model.max_api_responses_per_process = 12_000
    config.model.max_session_input_tokens = 1_000_000_000
    config.model.max_session_output_tokens = 20_000_000
    return config


def run(action: str, budget_usd: float):
    if action not in {"start", "retry"}:
        raise ValueError("Expected start or retry")
    if not math.isfinite(budget_usd) or budget_usd <= RESERVE_USD:
        raise ValueError("Budget must be finite and exceed the $3 uncertainty reserve")
    if action == "start" and RUN.exists():
        raise FileExistsError("Use retry for this run, never reuse an old run as fresh input")
    if action == "retry":
        state = read_json(RUN / "run.json")
        if state["latest_revision"] == state["current_revision"]:
            raise ValueError("Run already completed; there is nothing to retry")
        if state["config"]["model"]["name"] != "claude-sonnet-5":
            raise ValueError("Budget rates apply only to Sonnet 5")
    ledger = ResponseLedger(RUN / "cache/responses")
    ledger.require_headroom(budget_usd, RESERVE_USD)
    original = ClaudeSkills._run

    def bounded(client, *args, **kwargs):
        if client.model != "claude-sonnet-5":
            raise ValueError("Budget rates apply only to Sonnet 5")
        if client.response_dir.resolve() != ledger.directory.resolve():
            raise ValueError("Paid responses must be saved in this run's cost ledger")
        ledger.require_headroom(budget_usd, RESERVE_USD)
        before = len(ledger.seen)
        try:
            return original(client, *args, **kwargs)
        finally:
            ledger.refresh()
            write_json(
                RUN / "budget.json",
                {
                    "authorized_budget_usd": budget_usd,
                    "reserve_usd": RESERVE_USD,
                    "estimated_token_cost_usd": ledger.spent,
                    "recorded_responses": len(ledger.seen),
                    "last_call_usage_known": len(ledger.seen) > before,
                    "excludes": "tool fees and unreported usage; not a provider-enforced cap",
                },
            )

    with patch.object(ClaudeSkills, "_run", bounded):
        if action == "start":
            config = sherlock_config()
            path = ROOT / "output/sherlock-five.config.json"
            write_json(path, config.model_dump(mode="json"))
            result = start_graph(MANIFEST, RUN, path)
        else:
            result = retry_graph(RUN)
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "retry"])
    parser.add_argument(
        "--budget-usd",
        type=float,
        required=True,
        help="Total authorized run budget, not additional credit",
    )
    args = parser.parse_args()
    run(args.action, args.budget_usd)
