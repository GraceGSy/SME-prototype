from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compute_group_balance import compute_balance


class ComputeGroupBalanceTest(unittest.TestCase):
    def test_counts_each_represented_paper_once(self) -> None:
        group = {
            "members": [
                {"paper": "paper_a", "unit_id": "p1"},
                {"paper": "paper_a", "unit_id": "p2"},
                {"paper": "paper_b", "unit_id": "p1"},
            ]
        }

        self.assertEqual(
            compute_balance(group, ["paper_a", "paper_b", "paper_c"]),
            66.7,
        )

    def test_ignores_members_outside_the_paper_manifest(self) -> None:
        group = {
            "members": [
                {"paper": "paper_a", "unit_id": "p1"},
                {"paper": "unknown_paper", "unit_id": "p1"},
            ]
        }

        self.assertEqual(compute_balance(group, ["paper_a", "paper_b"]), 50.0)

    def test_returns_zero_when_there_are_no_papers(self) -> None:
        group = {"members": [{"paper": "paper_a", "unit_id": "p1"}]}

        self.assertEqual(compute_balance(group, []), 0.0)


if __name__ == "__main__":
    unittest.main()
