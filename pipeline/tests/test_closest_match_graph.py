from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from closest_match_graph import ClosestMatchGraph


def _row(p1_name, p1_num, p2_name, p2_num, basis, p1_sub=None, p1_sub_num=None, p2_sub=None, p2_sub_num=None):
    return {
        "paper1_section_name": p1_name,
        "paper1_section_number": p1_num,
        "paper1_subsection_name": p1_sub,
        "paper1_subsection_number": p1_sub_num,
        "paper2_section_name": p2_name,
        "paper2_section_number": p2_num,
        "paper2_subsection_name": p2_sub,
        "paper2_subsection_number": p2_sub_num,
        "basis": basis,
    }


def _unit(name, number, sub=None, sub_num=None):
    return {"section_name": name, "section_number": number, "subsection_name": sub, "subsection_number": sub_num}


class TestConfirmedMerge(unittest.TestCase):
    def test_bidirectional_agreement_merges_into_one_node(self) -> None:
        a_to_b = [_row("Introduction", "1", "Intro", "1", "both motivate the problem")]
        b_to_a = [_row("Intro", "1", "Introduction", "1", "confirmed reverse")]

        graph = ClosestMatchGraph()
        stats = graph.add_pair("paperA", "paperB", a_to_b, b_to_a)

        self.assertEqual(stats["merges"], 1)
        self.assertEqual(stats["one_directional_edges"], 0)

        node_a = graph.resolve("paperA", _unit("Introduction", "1"))
        node_b = graph.resolve("paperB", _unit("Intro", "1"))
        self.assertIsNotNone(node_a)
        self.assertEqual(node_a, node_b)
        self.assertEqual(len(graph.graph.nodes[node_a]["members"]), 2)
        self.assertEqual(len(graph.graph.nodes[node_a]["confirmations"]), 1)


class TestUnconfirmedMatch(unittest.TestCase):
    def test_one_directional_match_stays_as_edge_not_merge(self) -> None:
        a_to_b = [_row("Related Work", "2", "Background", "2", "A thinks these correspond")]
        b_to_a = [_row("Background", "2", None, None, "B finds no counterpart")]

        graph = ClosestMatchGraph()
        stats = graph.add_pair("paperA", "paperB", a_to_b, b_to_a)

        self.assertEqual(stats["merges"], 0)
        self.assertEqual(stats["one_directional_edges"], 1)

        node_a = graph.resolve("paperA", _unit("Related Work", "2"))
        node_b = graph.resolve("paperB", _unit("Background", "2"))
        self.assertNotEqual(node_a, node_b)
        self.assertEqual(graph.graph.number_of_edges(), 1)
        edge_data = list(graph.graph.get_edge_data(node_a, node_b).values())[0]
        self.assertEqual(edge_data["kind"], "one_directional_match")
        self.assertEqual(edge_data["direction"], "paperA->paperB")

    def test_no_match_either_direction_creates_singleton_nodes_only(self) -> None:
        a_to_b = [_row("Appendix", "A", None, None, "nothing corresponds")]
        b_to_a: list[dict] = []

        graph = ClosestMatchGraph()
        stats = graph.add_pair("paperA", "paperB", a_to_b, b_to_a)

        self.assertEqual(stats["merges"], 0)
        self.assertEqual(stats["one_directional_edges"], 0)
        self.assertEqual(graph.graph.number_of_nodes(), 1)
        self.assertEqual(graph.graph.number_of_edges(), 0)


class TestIncrementalCrossPairMerge(unittest.TestCase):
    def test_third_paper_confirmed_pair_absorbs_into_existing_group(self) -> None:
        graph = ClosestMatchGraph()

        # Pair 1: paperA <-> paperB, confirmed on Introduction/Intro.
        graph.add_pair(
            "paperA",
            "paperB",
            [_row("Introduction", "1", "Intro", "1", "fwd")],
            [_row("Intro", "1", "Introduction", "1", "rev")],
        )
        node_before = graph.resolve("paperA", _unit("Introduction", "1"))
        self.assertEqual(len(graph.graph.nodes[node_before]["members"]), 2)

        # Pair 2: paperB <-> paperC, confirmed on Intro/Preliminaries. paperB's Intro
        # is already part of node_before -- this should grow that SAME node to 3
        # members rather than creating a new, disconnected node.
        stats2 = graph.add_pair(
            "paperB",
            "paperC",
            [_row("Intro", "1", "Preliminaries", "1", "fwd2")],
            [_row("Preliminaries", "1", "Intro", "1", "rev2")],
        )

        self.assertEqual(stats2["merges"], 1)
        node_after = graph.resolve("paperC", _unit("Preliminaries", "1"))
        self.assertEqual(node_after, node_before)
        members = graph.graph.nodes[node_after]["members"]
        self.assertEqual(len(members), 3)
        paper_ids = {m["paper_id"] for m in members}
        self.assertEqual(paper_ids, {"paperA", "paperB", "paperC"})
        # Total node count: still just 1 real node for this group (no duplicates).
        self.assertEqual(graph.graph.number_of_nodes(), 1)
        self.assertEqual(len(graph.paper_pairs_processed), 2)


class TestPersistence(unittest.TestCase):
    def test_save_and_load_round_trip_preserves_merged_membership(self) -> None:
        graph = ClosestMatchGraph()
        graph.add_pair(
            "paperA",
            "paperB",
            [
                _row("Introduction", "1", "Intro", "1", "fwd"),
                _row("Related Work", "2", "Background", "2", "unconfirmed fwd"),
            ],
            [
                _row("Intro", "1", "Introduction", "1", "rev"),
                _row("Background", "2", None, None, "no match"),
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            graph.save(path)
            self.assertTrue(path.exists())

            reloaded = ClosestMatchGraph.load(path)

        self.assertEqual(reloaded.summary(), graph.summary())
        self.assertEqual(reloaded.paper_pairs_processed, graph.paper_pairs_processed)

        node = reloaded.resolve("paperA", _unit("Introduction", "1"))
        self.assertIsNotNone(node)
        self.assertEqual(len(reloaded.graph.nodes[node]["members"]), 2)
        self.assertEqual(reloaded.graph.number_of_edges(), 1)


class TestRedundantEdges(unittest.TestCase):
    def test_sibling_subsection_flagged_when_parent_confirmed_to_same_exact_target(self) -> None:
        # Mirrors the real corpusstudio/examplore_chi18 case: "Qualitative Results"
        # (whole) is confirmed to "RESULTS > Qualitative Analysis"; a SIBLING
        # subsection of "Qualitative Results" also points at that exact same
        # target -- that sibling edge should be flagged as redundant.
        graph = ClosestMatchGraph()
        graph.add_pair(
            "corpusstudio",
            "examplore",
            [_row("Qualitative Results", "6", "RESULTS", None, "parent fwd", p2_sub="Qualitative Analysis")],
            [_row("RESULTS", None, "Qualitative Results", "6", "parent rev", p1_sub="Qualitative Analysis")],
        )
        # A second, unconfirmed pass: a different corpusstudio subsection under the
        # SAME "Qualitative Results" parent points at the exact same examplore target.
        graph.add_pair(
            "corpusstudio",
            "examplore",
            [
                _row(
                    "Qualitative Results", "6", "RESULTS", None, "sibling fwd",
                    p1_sub="Sentence-level Writing Support", p2_sub="Qualitative Analysis",
                )
            ],
            [_row("RESULTS", None, None, None, "no reverse match", p1_sub="Qualitative Analysis")],
        )

        flagged = graph.redundant_edges()
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["source_unit"]["subsection_name"], "Sentence-level Writing Support")
        self.assertEqual(flagged[0]["target_unit"]["section_name"], "RESULTS")
        self.assertEqual(flagged[0]["target_unit"]["subsection_name"], "Qualitative Analysis")

    def test_parent_edge_flagged_when_its_own_child_confirmed_to_same_exact_target(self) -> None:
        # Mirrors the "RESULTS (whole) -> Qualitative Results (whole)" case: examplore's
        # child "RESULTS > Qualitative Analysis" is already confirmed to corpusstudio's
        # "Qualitative Results" (whole); a separate edge from the PARENT "RESULTS"
        # (whole) to that same corpusstudio target should be flagged too.
        graph = ClosestMatchGraph()
        graph.add_pair(
            "examplore",
            "corpusstudio",
            [_row("RESULTS", None, "Qualitative Results", "6", "child fwd", p1_sub="Qualitative Analysis")],
            [_row("Qualitative Results", "6", "RESULTS", None, "child rev", p2_sub="Qualitative Analysis")],
        )
        graph.add_pair(
            "examplore",
            "corpusstudio",
            [_row("RESULTS", None, "Qualitative Results", "6", "parent fwd, unconfirmed")],
            [_row("Qualitative Results", "6", None, None, "no reverse match")],
        )

        flagged = graph.redundant_edges()
        self.assertEqual(len(flagged), 1)
        self.assertIsNone(flagged[0]["source_unit"]["subsection_name"])
        self.assertEqual(flagged[0]["target_unit"]["section_name"], "Qualitative Results")
        self.assertIsNone(flagged[0]["target_unit"]["subsection_name"])

    def test_not_flagged_when_target_is_confirmed_partners_parent_not_the_partner_itself(self) -> None:
        # Mirrors the Related Work case: "RELATED WORK" (whole) is confirmed to
        # "Background and Related Work" (whole). A sibling subsection then points to
        # a SPECIFIC SUBSECTION of "Background and Related Work" -- a different, more
        # refined target than the exact confirmed partner -- so it must NOT be flagged.
        graph = ClosestMatchGraph()
        graph.add_pair(
            "examplore",
            "corpusstudio",
            [_row("RELATED WORK", None, "Background and Related Work", "2", "whole fwd")],
            [_row("Background and Related Work", "2", "RELATED WORK", None, "whole rev")],
        )
        graph.add_pair(
            "examplore",
            "corpusstudio",
            [
                _row(
                    "RELATED WORK", None, "Background and Related Work", "2", "subsection fwd, unconfirmed",
                    p1_sub="Interfaces for Exploring Collections", p2_sub="Finding Relevant Examples",
                )
            ],
            [_row("Background and Related Work", "2", None, None, "no reverse match", p1_sub="Finding Relevant Examples")],
        )

        flagged = graph.redundant_edges()
        self.assertEqual(flagged, [])

    def test_no_confirmed_family_match_means_nothing_flagged(self) -> None:
        graph = ClosestMatchGraph()
        graph.add_pair(
            "paperA",
            "paperB",
            [_row("Appendix", "A", "Notes", "Z", "weak guess")],
            [_row("Notes", "Z", None, None, "no reverse match")],
        )
        self.assertEqual(graph.redundant_edges(), [])

    def test_summary_reports_redundant_edge_count(self) -> None:
        graph = ClosestMatchGraph()
        graph.add_pair(
            "corpusstudio",
            "examplore",
            [_row("Qualitative Results", "6", "RESULTS", None, "parent fwd", p2_sub="Qualitative Analysis")],
            [_row("RESULTS", None, "Qualitative Results", "6", "parent rev", p1_sub="Qualitative Analysis")],
        )
        graph.add_pair(
            "corpusstudio",
            "examplore",
            [
                _row(
                    "Qualitative Results", "6", "RESULTS", None, "sibling fwd",
                    p1_sub="Sentence-level Writing Support", p2_sub="Qualitative Analysis",
                )
            ],
            [_row("RESULTS", None, None, None, "no reverse match", p1_sub="Qualitative Analysis")],
        )
        self.assertEqual(graph.summary()["redundant_one_directional_edges"], 1)


class TestOneToManyCandidates(unittest.TestCase):
    def test_flags_family_linked_to_two_distinct_far_side_sections(self) -> None:
        # Mirrors the real "Corpus Studio" case: one corpusstudio section has a
        # CONFIRMED match to one examplore section (via its own subsection) AND a
        # separate ONE-DIRECTIONAL edge (from a sibling subsection) pointing at a
        # totally different examplore top-level section.
        graph = ClosestMatchGraph()
        graph.add_pair(
            "corpusstudio",
            "examplore",
            [_row("Corpus Studio", "3", "SCENARIO", None, "confirmed fwd", p1_sub="Usage Scenario")],
            [_row("SCENARIO", None, "Corpus Studio", "3", "confirmed rev", p2_sub="Usage Scenario")],
        )
        graph.add_pair(
            "corpusstudio",
            "examplore",
            [_row("Corpus Studio", "3", "SYNTHETIC CODE SKELETON", None, "unconfirmed fwd")],
            [_row("SYNTHETIC CODE SKELETON", None, None, None, "no reverse match")],
        )

        flagged = graph.one_to_many_candidates()
        target_families = {f["family"]["section_name"]: f for f in flagged}
        self.assertIn("Corpus Studio", target_families)

        far_sections = {t["family"]["section_name"] for t in target_families["Corpus Studio"]["far_side_targets"]}
        self.assertEqual(far_sections, {"SCENARIO", "SYNTHETIC CODE SKELETON"})

        statuses = {
            t["family"]["section_name"]: sorted({e["status"] for e in t["evidence"]})
            for t in target_families["Corpus Studio"]["far_side_targets"]
        }
        self.assertEqual(statuses["SCENARIO"], ["confirmed"])
        self.assertEqual(statuses["SYNTHETIC CODE SKELETON"], ["one_directional"])

    def test_not_flagged_when_all_links_point_at_the_same_far_side_section(self) -> None:
        # Three subsections all pointing into the SAME already-confirmed far-side
        # section (different subsections of it, but one section) should NOT be
        # flagged -- that's ordinary subsection-level refinement, not spanning
        # multiple sections.
        graph = ClosestMatchGraph()
        graph.add_pair(
            "examplore",
            "corpusstudio",
            [_row("RELATED WORK", None, "Background and Related Work", "2", "whole fwd")],
            [_row("Background and Related Work", "2", "RELATED WORK", None, "whole rev")],
        )
        graph.add_pair(
            "examplore",
            "corpusstudio",
            [
                _row(
                    "RELATED WORK", None, "Background and Related Work", "2", "sub fwd, unconfirmed",
                    p1_sub="Interfaces", p2_sub="Finding Relevant Examples",
                )
            ],
            [_row("Background and Related Work", "2", None, None, "no reverse match", p1_sub="Finding Relevant Examples")],
        )

        flagged = graph.one_to_many_candidates()
        target_families = {f["family"]["section_name"]: f for f in flagged}
        self.assertNotIn("RELATED WORK", target_families)

    def test_no_matches_at_all_means_nothing_flagged(self) -> None:
        graph = ClosestMatchGraph()
        graph.add_pair(
            "paperA",
            "paperB",
            [_row("Appendix", "A", "Notes", "Z", "weak guess")],
            [_row("Notes", "Z", None, None, "no reverse match")],
        )
        self.assertEqual(graph.one_to_many_candidates(), [])


class TestReconfirmationIsIdempotentOnNodeCount(unittest.TestCase):
    def test_reprocessing_same_confirmed_pair_does_not_duplicate_members(self) -> None:
        graph = ClosestMatchGraph()
        rows_fwd = [_row("Introduction", "1", "Intro", "1", "fwd")]
        rows_rev = [_row("Intro", "1", "Introduction", "1", "rev")]

        graph.add_pair("paperA", "paperB", rows_fwd, rows_rev)
        node_id = graph.resolve("paperA", _unit("Introduction", "1"))
        self.assertEqual(len(graph.graph.nodes[node_id]["members"]), 2)

        # Re-adding the same pair should merge_nodes(node, node) -- a no-op on
        # membership, just an extra confirmation record.
        graph.add_pair("paperA", "paperB", rows_fwd, rows_rev)
        node_id_again = graph.resolve("paperA", _unit("Introduction", "1"))
        self.assertEqual(node_id_again, node_id)
        self.assertEqual(len(graph.graph.nodes[node_id]["members"]), 2)
        self.assertEqual(len(graph.graph.nodes[node_id]["confirmations"]), 2)


if __name__ == "__main__":
    unittest.main()
