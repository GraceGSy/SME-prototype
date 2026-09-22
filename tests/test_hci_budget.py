import unittest

from helpers.run_hci_concise_20260907 import extension_policy, token_cost
from pipeline.providers.contracts import SkillCallPolicy


class HciBudgetTest(unittest.TestCase):
    def test_extension_only_adjusts_aggregate_usage_guard(self):
        policy = SkillCallPolicy(max_tokens=1024)
        adjusted = extension_policy(policy)
        expected = policy.as_dict() | {"max_input_tokens": 300_000}
        self.assertEqual(adjusted.as_dict(), expected)
        self.assertEqual(policy.max_input_tokens, 200_000)

    def test_extension_preserves_smaller_question_limits(self):
        policy = SkillCallPolicy(max_tokens=256, max_input_tokens=50_000)
        self.assertIs(extension_policy(policy), policy)

    def test_cache_write_tiers_are_not_double_counted(self):
        usage = {
            "input_tokens": 1_000_000,
            "cache_creation_input_tokens": 2_000_000,
            "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000},
            "cache_read_input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
        }
        self.assertAlmostEqual(token_cost(usage), 18.7)

    def test_empty_usage_has_no_estimated_charge(self):
        self.assertEqual(token_cost({}), 0)
