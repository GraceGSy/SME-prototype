from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incremental_graph.configuration import load_pipeline_config
from incremental_graph.graph import QuestionGraph, graph_from_events, stable_id
from incremental_graph.input_data import load_paper
from incremental_graph.journal import RevisionJournal
from incremental_graph.models import JudgmentResult, Paper, Paragraph, Section
from incremental_graph.runner import IncrementalGraphRunner
from viewer_dataset import validate_dataset


CONFIG_PATH = Path(__file__).resolve().parents[1] / "incremental_graph" / "configs" / "incremental-v1.yaml"


def paper(paper_id: str, sections: list[tuple[str, str, str]]) -> Paper:
    return Paper(
        paper_id=paper_id,
        title=paper_id.upper(),
        sections=[
            Section(
                id=section_id,
                label=section_id,
                text=text,
                paragraphs=[Paragraph(id=paragraph_id, text=f"Paragraph for {text}")],
            )
            for section_id, paragraph_id, text in sections
        ],
    )


class ScriptedJudge:
    def __init__(self, matches: dict[str, str | None]):
        self.matches = matches

    def judge(self, request):
        if request.output_kind == "question":
            focus = request.key.rsplit(":", 1)[-1]
            normalized = {"question": f"What does {focus} address?"}
        else:
            normalized = {
                "best_match_id": self.matches.get(request.key),
                "reason": "scripted test decision",
            }
        return JudgmentResult(
            fingerprint=f"fingerprint-{request.key}",
            normalized=normalized,
            raw_response={"source": "scripted"},
            rendered_system="system",
            rendered_user="user",
            prompt_hash="prompt",
            context_hash="context",
            schema_hash="schema",
            model={"provider": "test", "name": "scripted"},
        )


class IncrementalGraphTest(unittest.TestCase):
    def test_normalizes_pseudo_sections_with_stable_unique_unit_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.json"
            path.write_text(json.dumps([
                {
                    "section_name": "Introduction",
                    "section_number": None,
                    "paragraphs": [
                        {"paragraph_number": 1, "text": "First paragraph."},
                        {"paragraph_number": 2, "text": "Second paragraph."},
                    ],
                },
                {
                    "section_name": "Discussion",
                    "section_number": None,
                    "paragraphs": [{"paragraph_number": 1, "text": "Discussion paragraph."}],
                },
            ]), encoding="utf-8")

            normalized = load_paper(path, "paper-a", "Paper A")

            self.assertEqual([section.id for section in normalized.sections], ["s1", "s2"])
            self.assertEqual(
                [paragraph.id for section in normalized.sections for paragraph in section.paragraphs],
                ["s1-1", "s1-2", "s2-1"],
            )
            self.assertEqual(normalized.sections[0].text, "First paragraph.\n\nSecond paragraph.")

    def test_incremental_reconciliation_preserves_ignored_projection_as_provenance(self) -> None:
        group_a = stable_id("section-group", "root", "p1", "a")
        group_b = stable_id("section-group", "root", "p1", "b")
        paragraph_group_a = stable_id("paragraph-group", group_a, "p1", "pa")
        matches = {
            "p2:section_matching:new_to_group:a2": group_a,
            "p2:section_matching:new_to_group:b2": group_b,
            f"p2:section_matching:group_to_new:{group_a}": "a2",
            f"p2:section_matching:group_to_new:{group_b}": None,
            "p2:paragraph_matching:new_to_group:pa2": paragraph_group_a,
            f"p2:paragraph_matching:group_to_new:{paragraph_group_a}": "pa2",
            "p3:section_matching:new_to_group:a3": group_a,
            f"p3:section_matching:group_to_new:{group_a}": "a3",
            f"p3:section_matching:group_to_new:{group_b}": "a3",
            "p3:paragraph_matching:new_to_group:pa3": paragraph_group_a,
            f"p3:paragraph_matching:group_to_new:{paragraph_group_a}": "pa3",
        }
        papers = [
            paper("p1", [("a", "pa", "shared method"), ("b", "pb", "secondary concern")]),
            paper("p2", [("a2", "pa2", "shared method"), ("b2", "pb2", "secondary variant")]),
            paper("p3", [("a3", "pa3", "shared method")]),
        ]

        with tempfile.TemporaryDirectory() as directory:
            revision = Path(directory) / "revision"
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                ScriptedJudge(matches),
                revision,
            )
            summary = runner.run(papers)

            graph = runner.question_graph.graph
            self.assertEqual(len(graph.nodes[group_a]["members"]), 3)
            self.assertEqual(graph.nodes[group_a]["classification"], "common_structure")
            self.assertEqual(len(graph.nodes[paragraph_group_a]["members"]), 3)
            self.assertEqual(graph.nodes[paragraph_group_a]["classification"], "common_structure")
            self.assertFalse(graph.has_edge(group_b, group_a))
            ignored = [event for event in runner.journal.events if event["action"] == "projected_edge_ignored"]
            self.assertEqual(len(ignored), 1)
            self.assertEqual(ignored[0]["source_group_id"], group_b)
            self.assertEqual(ignored[0]["absorbed_group_id"], group_a)

            replayed = graph_from_events(runner.journal.events)
            self.assertEqual(set(replayed.nodes), set(graph.nodes))
            self.assertEqual(set(replayed.edges(keys=True)), set(graph.edges(keys=True)))
            self.assertEqual(summary["graph_hash"], runner.question_graph.graph_hash())
            replay = json.loads((revision / "dataset" / "graph-replay.json").read_text(encoding="utf-8"))
            self.assertEqual(replay["final_graph_hash"], summary["graph_hash"])
            self.assertIn("section", replay["layouts"])
            self.assertIn(f"paragraph:{group_a}", replay["layouts"])
            descriptor = validate_dataset(revision / "dataset", "incremental", "Incremental")
            self.assertEqual(descriptor["graph_replay_file"], "graph-replay.json")

    def test_common_structure_can_be_demoted_as_denominator_grows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = RevisionJournal(Path(directory) / "revision")
            graph = QuestionGraph(journal)
            graph.add_paper("p1", "P1", 1)
            node_id = graph.create_group(
                level="section", parent_id=None, member_id="s1", paper_id="p1", paper_index=1
            )
            self.assertEqual(graph.classify("section", 1)[node_id], "non_alignable_difference")

            graph.add_paper("p2", "P2", 2)
            graph.add_member(node_id, "s2", "p2", 2)
            self.assertEqual(graph.classify("section", 2)[node_id], "common_structure")
            graph.add_paper("p3", "P3", 3)
            self.assertEqual(graph.classify("section", 3)[node_id], "common_structure")
            graph.add_paper("p4", "P4", 4)
            self.assertEqual(graph.classify("section", 4)[node_id], "alignable_difference")


if __name__ == "__main__":
    unittest.main()
