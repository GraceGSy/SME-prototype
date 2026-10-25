"""Known partitions exercise coverage, fixed-identity graphs, and lexical scores."""

import unittest

from pipeline.comparison_metrics import membership_metrics, question_similarity


def group(members, question="What role do these passages share?"):
    return {
        "id": "/".join(members),
        "members": sorted(members),
        "full_members": sorted(members),
        "scope": [],
        "question": question,
    }


class ComparisonMetricsTest(unittest.TestCase):
    def test_fan_in_counts_cross_paper_pairs_not_same_paper_pairs(self):
        sources = {"a1": {"paper": "a"}, "a2": {"paper": "a"}, "b1": {"paper": "b"}}
        result = membership_metrics(
            [group(["a1", "a2", "b1"])], [group(["a1", "b1"]), group(["a2"])], sources
        )
        self.assertEqual(result["coverage"]["left"]["cross_paper_pairs"], 2)
        self.assertEqual(result["coverage"]["left"]["matched_units"], 3)
        self.assertEqual(result["coverage"]["right"]["matched_units"], 2)
        self.assertEqual(result["graph"]["pair_jaccard"], 0.5)
        self.assertEqual(result["graph"]["fixed_identity_edge_edits"], 1)
        self.assertEqual(result["graph"]["lost_coverage"], ["a2"])

    def test_same_unlabelled_shape_is_not_same_source_matching(self):
        sources = {key: {"paper": key} for key in "abc"}
        result = membership_metrics(
            [group(["a", "b"]), group(["c"])], [group(["a"]), group(["b", "c"])], sources
        )
        self.assertFalse(result["graph"]["identity_isomorphic"])
        self.assertEqual(result["graph"]["pair_jaccard"], 0)
        self.assertEqual(result["graph"]["fixed_identity_edge_edits"], 2)

    def test_networkx_alignment_is_global_not_greedy(self):
        sources = {key: {"paper": key[0]} for key in ("a0", "a1", "a2", "b0", "b1", "b2", "b3")}
        left = [group(["a0", "a1", "b0", "b1", "b2"]), group(["a2", "b3"])]
        right = [group(["a0", "b0", "b1", "a2", "b3"]), group(["a1", "b2"])]
        result = membership_metrics(left, right, sources)["group_alignment"]
        self.assertEqual(result["aligned_groups"], 2)
        self.assertEqual(sum(len(row["shared_members"]) for row in result["rows"]), 4)
        self.assertEqual(result["left_groups_overlapping_multiple_right"], 1)
        self.assertEqual(result["right_groups_overlapping_multiple_left"], 1)

    def test_no_matches_is_not_a_perfect_similarity_score(self):
        sources = {key: {"paper": key} for key in "ab"}
        groups = [group([key]) for key in "ab"]
        result = membership_metrics(groups, groups, sources)
        self.assertEqual(result["coverage"]["left"]["fraction"], 0)
        self.assertIsNone(result["graph"]["pair_jaccard"])
        self.assertIsNone(result["graph"]["mean_peer_jaccard_active_units"])
        self.assertIsNone(result["group_alignment"]["mean_member_jaccard_with_unmatched_zero"])

    def test_lexical_questions_normalize_case_not_meaning(self):
        result = question_similarity(
            [
                {"left": "What enables access?", "right": "WHAT enables access!"},
                {"left": "What enables access?", "right": "What prevents access?"},
                {"left": "", "right": "A question"},
            ]
        )
        same, different, missing = result["rows"]
        self.assertTrue(same["normalized_exact"])
        self.assertAlmostEqual(same["tfidf_cosine"], 1)
        self.assertEqual(same["token_jaccard"], 1)
        self.assertFalse(different["normalized_exact"])
        self.assertLess(different["tfidf_cosine"], 1)
        self.assertIsNone(missing["tfidf_cosine"])
        self.assertEqual(result["compared"], 2)
        self.assertEqual(result["missing_left"], 1)


if __name__ == "__main__":
    unittest.main()
