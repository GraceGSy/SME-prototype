import unittest
from unittest.mock import patch

from helpers.preflight_sherlock_five import scenario
from pipeline.llm.client import ClaudeSkills


class SherlockPreflightTest(unittest.TestCase):
    def test_all_singleton_capacity_is_measured_without_api_clients(self):
        with patch.object(ClaudeSkills, "__init__", side_effect=AssertionError("No paid clients")):
            report = scenario(0)
        self.assertEqual(report["matching_calls"], 3262)
        self.assertEqual(len(report["pools"]), 8)
        self.assertTrue(all(pool["passes_prompt_guard"] for pool in report["pools"]))
        self.assertTrue(any(not pool["passes_default_prompt_guard"] for pool in report["pools"]))
        self.assertTrue(all(pool["cacheable_characters"] > 0 for pool in report["pools"]))
