import unittest

from helpers.run_hci_concise_20260907 import token_cost


class HciBudgetTest(unittest.TestCase):
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
