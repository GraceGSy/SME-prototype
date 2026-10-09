from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lean_graph.models import Paper, Section
from lean_graph.runner import run


class ScriptedJudge:
    """Fake judge for testing graph_ops/runner without any real API calls. Mirrors
    incremental_graph's own test pattern (see test_incremental_graph.py's
    ScriptedJudge), adapted to this pipeline's simpler generate_question/match_unit
    interface."""

    def __init__(self, questions: dict[str, str], matches: dict[tuple[str, str], str | None]):
        self.questions = questions
        self.matches = matches  # (kind, focus_text) -> chosen_id or None

    def generate_question(self, text: str, kind: str = "passage") -> str:
        return self.questions.get(text, f"What does {text[:20]!r} address?")

    def match_unit(self, focus_text: str, candidates: dict[str, str], kind: str = "passage"):
        if not candidates:
            return None
        return self.matches.get((kind, focus_text))


def make_paper(paper_id: str, sections: list[tuple[str, str]]) -> Paper:
    return Paper(
        paper_id=paper_id,
        title=paper_id.upper(),
        sections=[Section(id=section_id, label=section_id, text=text, paragraphs=[]) for section_id, text in sections],
    )


class LeanGraphTest(unittest.TestCase):
    def test_reciprocal_match_becomes_a_shared_common_structure_node(self) -> None:
        paper_a = make_paper("paper_a", [("a1", "Intro text A")])
        paper_b = make_paper("paper_b", [("b1", "Intro text B")])

        # create_group's ID scheme (graph_ops.create_group) is deterministic: the very
        # first node ever created is "section-0-paper_a-a1".
        node_id = "section-0-paper_a-a1"
        group_question = "What does the introduction cover?"

        judge = ScriptedJudge(
            questions={
                "Intro text A": group_question,
                "Intro text B": "What does the introduction cover, from paper B?",
            },
            matches={
                ("section", "Intro text B"): node_id,   # paper_b's section picks paper_a's group
                ("section", group_question): "b1",       # paper_a's group picks paper_b's section back
            },
        )

        graph = run([paper_a, paper_b], judge)

        self.assertEqual(len(graph.nodes), 1)
        node = graph.nodes[node_id]
        self.assertEqual({member.paper_id for member in node.members}, {"paper_a", "paper_b"})
        self.assertEqual(node.classification, "common_structure")
        self.assertEqual(len(graph.edges), 0)

    def test_one_directional_match_becomes_alignable_difference_with_an_edge(self) -> None:
        paper_a = make_paper("paper_a", [("a1", "Intro text A")])
        paper_b = make_paper("paper_b", [("b1", "Intro text B")])

        node_id = "section-0-paper_a-a1"
        group_question = "What does the introduction cover?"

        judge = ScriptedJudge(
            questions={"Intro text A": group_question, "Intro text B": "Unrelated question"},
            matches={
                ("section", "Intro text B"): node_id,  # paper_b picks paper_a's group
                ("section", group_question): None,      # but paper_a's group does not pick paper_b back
            },
        )

        graph = run([paper_a, paper_b], judge)

        self.assertEqual(len(graph.nodes), 2)
        b_node_id = next(nid for nid, n in graph.nodes.items() if n.members[0].paper_id == "paper_b")
        self.assertEqual(len(graph.edges), 1)
        edge = graph.edges[0]
        self.assertEqual((edge.source, edge.target), (b_node_id, node_id))
        self.assertEqual(graph.nodes[node_id].classification, "alignable_difference")
        self.assertEqual(graph.nodes[b_node_id].classification, "alignable_difference")

    def test_no_match_either_direction_becomes_two_isolated_singletons(self) -> None:
        paper_a = make_paper("paper_a", [("a1", "Intro text A")])
        paper_b = make_paper("paper_b", [("b1", "Unrelated text B")])

        node_id = "section-0-paper_a-a1"

        judge = ScriptedJudge(
            questions={"Intro text A": "What does the introduction cover?", "Unrelated text B": "What is X?"},
            matches={
                ("section", "Unrelated text B"): None,
                ("section", "What does the introduction cover?"): None,
            },
        )

        graph = run([paper_a, paper_b], judge)

        self.assertEqual(len(graph.nodes), 2)
        self.assertEqual(len(graph.edges), 0)
        for node in graph.nodes.values():
            self.assertEqual(node.classification, "non_alignable_difference")

    def test_paragraphs_are_only_compared_within_their_own_matched_section_group(self) -> None:
        paper_a = Paper(paper_id="paper_a", title="PAPER_A", sections=[
            Section(id="s1", label="Intro", text="Intro A", paragraphs=[]),
        ])
        paper_a.sections[0].paragraphs = []
        # give the section real paragraph text so a paragraph round actually runs
        from lean_graph.models import Paragraph
        paper_a.sections[0].paragraphs = [Paragraph(id="s1-1", label="1", text="Para A1")]

        paper_b = Paper(paper_id="paper_b", title="PAPER_B", sections=[
            Section(id="s1", label="Intro", text="Intro B", paragraphs=[Paragraph(id="s1-1", label="1", text="Para B1")]),
        ])

        section_node_id = "section-0-paper_a-s1"
        section_question = "What does the introduction cover?"

        judge = ScriptedJudge(
            questions={
                "Intro A": section_question,
                "Intro B": "What does the introduction cover, in B?",
                "Para A1": "What does paragraph 1 say?",
                "Para B1": "What does paragraph 1 say, in B?",
            },
            matches={
                ("section", "Intro B"): section_node_id,
                ("section", section_question): "s1",
                # paragraph-level matches keyed the same way, scoped inside the section group
                ("paragraph", "Para B1"): "paragraph-1-paper_a-s1-1",
                ("paragraph", "What does paragraph 1 say?"): "s1-1",
            },
        )

        graph = run([paper_a, paper_b], judge)

        paragraph_nodes = [n for n in graph.nodes.values() if n.level == "paragraph"]
        self.assertEqual(len(paragraph_nodes), 1)
        self.assertEqual({m.paper_id for m in paragraph_nodes[0].members}, {"paper_a", "paper_b"})
        self.assertEqual(paragraph_nodes[0].parent_id, section_node_id)


if __name__ == "__main__":
    unittest.main()
