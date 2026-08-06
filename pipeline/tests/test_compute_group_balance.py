from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compute_group_balance import compute_all_balances, compute_balance


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

    def test_writes_balance_for_every_saved_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "manifest.json").write_text(json.dumps([
                {"paper_id": "paper_a"},
                {"paper_id": "paper_b"},
            ]))
            for iteration, members in {
                1: [{"paper": "paper_a", "unit_id": "p1"}],
                2: [
                    {"paper": "paper_a", "unit_id": "p1"},
                    {"paper": "paper_b", "unit_id": "p2"},
                ],
            }.items():
                state = {
                    "groups": [{
                        "group_id": "group_1",
                        "overarching_question": f"Question {iteration}?",
                        "members": members,
                    }]
                }
                state_path = output_dir / f"paragraph_groups_iter{iteration}.json"
                state_path.write_text(json.dumps(state))

            results = compute_all_balances(output_dir)

            self.assertEqual(results[1][0]["group_balance"], 50.0)
            self.assertEqual(results[2][0]["group_balance"], 100.0)
            self.assertTrue((output_dir / "group_balance_iter1.json").exists())
            self.assertTrue((output_dir / "group_balance_iter2.json").exists())


if __name__ == "__main__":
    unittest.main()
