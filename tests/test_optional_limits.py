"""Execution caps are opt-in; usage accounting and explicit caps still work."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_jev import answer

from pipeline.incremental_graph.configuration import load_pipeline_config
from pipeline.incremental_graph.runs import DEFAULT_CONFIG
from pipeline.providers.contracts import SkillBudgetExceeded, SkillCallPolicy, SkillSessionBudget
from pipeline.providers.jev import JevClient, JevSettings
from pipeline.providers.limits import SessionLimits
from pipeline.providers.settings import ModelSettings


class OptionalLimitsTest(unittest.TestCase):
    def test_defaults_and_pipeline_stages_have_no_local_caps(self):
        config = load_pipeline_config(DEFAULT_CONFIG)
        for model in (ModelSettings(), config.model):
            for key in (
                "max_input_tokens",
                "max_prompt_characters",
                "max_api_responses_per_process",
                "max_session_input_tokens",
                "max_session_output_tokens",
            ):
                self.assertIsNone(getattr(model, key))
        self.assertTrue(all(stage.max_input_tokens is None for stage in config.stages))
        self.assertIsNone(JevSettings().max_calls)
        self.assertIsNone(JevSettings().max_input_tokens)

    def test_uncapped_usage_exceeds_previous_defaults_and_remains_recorded(self):
        limits = SessionLimits()
        limits.session_usage["api_responses"] = 10000
        limits._record_session_usage(100_000_000, 10_000_000, "large-response")
        limits._check_session_budget()
        self.assertEqual(limits.session_usage["api_responses"], 10001)
        self.assertEqual(limits.session_usage["input_tokens"], 100_000_000)
        policy = SkillCallPolicy(max_tokens=512)
        limits._validate_prompt("x" * 500_001, policy)
        attachment = Mock()
        attachment.stat.return_value.st_size = 10_000_000
        limits._validate_attachment(attachment, policy)

    def test_each_explicit_session_limit_still_stops(self):
        for key in ("api_responses", "input_tokens", "output_tokens"):
            with self.subTest(key=key):
                limits = SessionLimits(SkillSessionBudget(**{f"max_{key}": 1}))
                limits.session_usage[key] = 1
                with self.assertRaises(SkillBudgetExceeded):
                    limits._check_session_budget()
        for key in ("input_tokens", "output_tokens"):
            with self.subTest(post_response=key):
                limits = SessionLimits(SkillSessionBudget(**{f"max_{key}": 1}))
                with self.assertRaises(SkillBudgetExceeded):
                    limits._record_session_usage(2, 2, "paid-response")
                self.assertEqual(limits.session_usage["api_responses"], 1)

    def test_jev_accepts_usage_above_old_caps_without_changing_response(self):
        body = {"model": "jev-1.14.0", "questions": {"match": {"criteria": {"a": "A", "b": "B"}}}}
        payload = answer(body, "a")
        payload["usage"]["input_tokens"] = 2_003_822
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = JevClient(JevSettings(), root, root / "responses")
            client.calls = 500
            client.input_tokens = 2_000_000
            with (
                patch("pipeline.providers.jev.load_api_key", return_value="offline-key"),
                patch(
                    "pipeline.providers.jev.urlopen",
                    return_value=io.BytesIO(json.dumps(payload).encode()),
                ),
            ):
                self.assertEqual(client.choose(body), payload)
            self.assertEqual(client.calls, 501)
            self.assertEqual(client.input_tokens, 4_003_822)
            self.assertEqual(len(list((root / "responses").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
