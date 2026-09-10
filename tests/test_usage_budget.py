import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from helpers import run_sherlock_five as sherlock
from helpers.run_sherlock_five import run
from helpers.usage_budget import ResponseLedger
from pipeline.files import write_json
from pipeline.llm.client import SkillBudgetExceeded


class UsageBudgetTest(unittest.TestCase):
    def test_counts_rejected_responses_once_across_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_json(
                path / "failed.json",
                {
                    "usage": {"input_tokens": 1_000_000, "output_tokens": 100_000},
                    "response": {"stop_reason": "max_tokens"},
                },
            )
            ledger = ResponseLedger(path)
            self.assertEqual(ledger.spent, 3)
            ledger.refresh()
            self.assertEqual(ledger.spent, 3)
            self.assertEqual(ResponseLedger(path).spent, 3)
            with self.assertRaises(SkillBudgetExceeded):
                ledger.require_headroom(5, 3)

    def test_missing_usage_is_not_treated_as_free(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_json(path / "unknown.json", {"usage": {}})
            with self.assertRaises(ValueError):
                ResponseLedger(path)
            for usage in [
                {"output_tokens": 1},
                {"input_tokens": -1, "output_tokens": 1},
                {"input_tokens": "100", "output_tokens": 1},
                {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": -1},
            ]:
                write_json(path / "unknown.json", {"usage": usage})
                with self.assertRaises(ValueError):
                    ResponseLedger(path)

    def test_launcher_stops_before_next_paid_call_and_records_failed_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_path = root / "runs/test"
            client = SimpleNamespace(
                model="claude-sonnet-5", response_dir=run_path / "cache/responses"
            )

            def paid_response(*args, **kwargs):
                write_json(
                    client.response_dir / "rejected.json",
                    {"usage": {"input_tokens": 1_000_000, "output_tokens": 100_000}},
                )
                raise ValueError("Mock invalid JSON after a paid response")

            def start(*args):
                with self.assertRaisesRegex(ValueError, "Mock invalid JSON"):
                    sherlock.ClaudeSkills._run(client)
                sherlock.ClaudeSkills._run(client)

            with (
                patch.object(sherlock, "ROOT", root),
                patch.object(sherlock, "RUN", run_path),
                patch.object(sherlock, "start_graph", side_effect=start),
                patch.object(sherlock.ClaudeSkills, "_run", side_effect=paid_response) as paid,
            ):
                with self.assertRaises(SkillBudgetExceeded):
                    run("start", 5)
                self.assertEqual(paid.call_count, 1)
            self.assertEqual(
                sherlock.read_json(run_path / "budget.json")["estimated_token_cost_usd"], 3
            )

    def test_invalid_budgets_fail_before_start(self):
        for amount in [float("nan"), float("inf"), -1, 0, 3]:
            with self.assertRaises(ValueError):
                run("start", amount)
