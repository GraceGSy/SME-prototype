from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline.incremental_graph.configuration import load_pipeline_config
from pipeline.incremental_graph.graph import QuestionGraph, graph_from_events, stable_id
from pipeline.incremental_graph.input_data import load_manifest, load_paper
from pipeline.incremental_graph.journal import RevisionJournal
from pipeline.incremental_graph.models import JudgmentResult, Paper, Paragraph, Section
from pipeline.incremental_graph.runner import IncrementalGraphRunner
from pipeline.viewer.package import validate_dataset


CONFIG_PATH = Path(__file__).resolve().parents[1] / "pipeline" / "incremental_graph" / "configs" / "incremental-v1.yaml"
CANONICAL_MANIFEST = Path(__file__).resolve().parents[1] / "datasets" / "hci-five-paper" / "manifest.yaml"


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
        self.requests = []

    def judge(self, request):
        self.requests.append(request)
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
    def test_reuses_questions_already_present_in_canonical_input(self) -> None:
        decorated = Paper(
            paper_id="p1",
            title="P1",
            sections=[Section(
                id="s1",
                text="Section text",
                question="What does the section establish?",
                paragraphs=[Paragraph(
                    id="p1",
                    text="Paragraph text",
                    question="What does the paragraph establish?",
                )],
            )],
        )
        judge = ScriptedJudge({})
        with tempfile.TemporaryDirectory() as directory:
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                judge,
                Path(directory) / "revision",
            )
            runner.run([decorated])

        called_stages = {request.stage_id for request in judge.requests}
        self.assertNotIn("section_questions", called_stages)
        self.assertNotIn("paragraph_questions", called_stages)
        self.assertIn("section_group_questions", called_stages)
        self.assertIn("paragraph_group_questions", called_stages)

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
                ["s1-p1", "s1-p2", "s2-p1"],
            )
            self.assertEqual(normalized.sections[0].text, "First paragraph.\n\nSecond paragraph.")

    def test_normalizes_nested_paragraphs_and_existing_questions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.json"
            path.write_text(json.dumps([{
                "section_name": "Method",
                "section_number": "3",
                "question_this_text_answers": "How does the method work?",
                "paragraphs": [{
                    "paragraph_number": 0,
                    "text": "Method overview.",
                    "question_this_text_answers": "What is the method overview?",
                }],
                "subsections": [{
                    "section_name": "Implementation",
                    "paragraphs": [{
                        "paragraph_number": 0,
                        "text": "Implementation details.",
                        "question_this_text_answers": "How was it implemented?",
                    }],
                }],
            }]), encoding="utf-8")

            normalized = load_paper(path, "paper-a", "Paper A")

            section = normalized.sections[0]
            subsection = normalized.sections[1]
            self.assertEqual(section.question, "How does the method work?")
            self.assertEqual(section.ordinal, 1)
            self.assertEqual(section.text, "Method overview.\n\nImplementation details.")
            self.assertEqual([paragraph.id for paragraph in section.paragraphs], ["3-p1"])
            self.assertEqual(subsection.kind, "subsection")
            self.assertEqual(subsection.parent_id, "3")
            self.assertEqual(subsection.family_id, "3")
            self.assertEqual(subsection.ordinal, 2)
            self.assertEqual(subsection.paragraphs[0].question, "How was it implemented?")

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
            self.assertEqual(graph.number_of_edges(), 0)
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
            self.assertIn("paragraph", replay["layouts"])
            paragraph_nodes = [
                node for node in runner.question_graph.serialize()["nodes"]
                if node["level"] == "paragraph"
            ]
            self.assertEqual(len(replay["layouts"]["paragraph"]), len(paragraph_nodes))
            self.assertIn("section", replay["hierarchy_layouts"])
            descriptor = validate_dataset(revision / "dataset", "incremental", "Incremental")
            self.assertEqual(descriptor["graph_replay_file"], "graph-replay.json")

    def test_common_structure_uses_inclusive_half_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = RevisionJournal(Path(directory) / "revision")
            graph = QuestionGraph(journal)
            graph.add_paper("p1", "P1", 1)
            node_id = graph.create_group(
                level="section",
                parent_id=None,
                member_id="s1",
                paper_id="p1",
                paper_index=1,
                ordinal=1,
            )
            self.assertEqual(graph.classify("section", 1)[node_id], "common_structure")

            graph.add_paper("p2", "P2", 2)
            graph.add_member(node_id, "s2", "p2", 2, 1)
            self.assertEqual(graph.classify("section", 2)[node_id], "common_structure")
            graph.add_paper("p3", "P3", 3)
            self.assertEqual(graph.classify("section", 3)[node_id], "common_structure")
            graph.add_paper("p4", "P4", 4)
            self.assertEqual(graph.classify("section", 4)[node_id], "common_structure")
            graph.add_paper("p5", "P5", 5)
            self.assertEqual(graph.classify("section", 5)[node_id], "alignable_difference")

    def test_paragraph_classification_uses_only_direct_node_membership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            graph = QuestionGraph(RevisionJournal(Path(directory) / "revision"))
            for index in range(1, 6):
                graph.add_paper(f"p{index}", f"P{index}", index)

            structural_group = graph.create_group(
                level="section",
                parent_id=None,
                member_id="s1",
                paper_id="p1",
                paper_index=1,
                ordinal=1,
            )
            for index in range(2, 6):
                graph.add_member(structural_group, f"s{index}", f"p{index}", index, 1)

            paragraph_group = graph.create_group(
                level="paragraph",
                parent_id=structural_group,
                member_id="para1",
                paper_id="p1",
                paper_index=1,
                ordinal=1,
                owner_group_id=structural_group,
            )

            self.assertEqual(
                graph.classify("paragraph", 5)[paragraph_group],
                "non_alignable_difference",
            )

    def test_rejects_two_members_from_one_paper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            graph = QuestionGraph(RevisionJournal(Path(directory) / "revision"))
            graph.add_paper("p1", "P1", 1)
            node_id = graph.create_group(
                level="section",
                parent_id=None,
                member_id="s1",
                paper_id="p1",
                paper_index=1,
                ordinal=1,
            )

            with self.assertRaisesRegex(ValueError, "already contains a member from p1"):
                graph.add_member(node_id, "s2", "p1", 1, 2)

    def test_canonical_five_paper_dataset_has_only_hierarchy_edges(self) -> None:
        _, papers = load_manifest(CANONICAL_MANIFEST)
        with tempfile.TemporaryDirectory() as directory:
            revision = Path(directory) / "revision"
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                ScriptedJudge({}),
                revision,
            )
            summary = runner.run(papers)

            self.assertEqual(summary["paper_count"], 5)
            edges = list(runner.question_graph.graph.edges(data=True))
            self.assertEqual(len(edges), 87)
            self.assertTrue(all(data["kind"] == "contains" for _, _, data in edges))
            self.assertTrue(
                all(len(data["members"]) == 1 for _, data in runner.question_graph.nodes())
            )
            descriptor = validate_dataset(revision / "dataset", "hci-five", "HCI Five")
            self.assertEqual(descriptor["paper_count"], 5)
            self.assertEqual(descriptor["paragraph_count"], 459)

    def test_cross_level_structure_and_family_paragraph_scope(self) -> None:
        first = Paper(
            paper_id="p1",
            title="P1",
            sections=[
                Section(
                    id="s1",
                    text="Whole section evidence. Subsection evidence.",
                    family_id="s1",
                    paragraphs=[Paragraph(id="lead1", text="Lead paragraph")],
                ),
                Section(
                    id="sub1",
                    text="Subsection evidence.",
                    kind="subsection",
                    parent_id="s1",
                    family_id="s1",
                    ordinal=2,
                    paragraphs=[Paragraph(id="detail1", text="Detail paragraph", ordinal=2)],
                ),
            ],
        )
        second = Paper(
            paper_id="p2",
            title="P2",
            sections=[
                Section(
                    id="s2",
                    text="Second whole section.",
                    family_id="s2",
                    paragraphs=[Paragraph(id="lead2", text="Second lead")],
                ),
                Section(
                    id="sub2",
                    text="Second subsection.",
                    kind="subsection",
                    parent_id="s2",
                    family_id="s2",
                    ordinal=2,
                    paragraphs=[Paragraph(id="detail2", text="Second detail", ordinal=2)],
                ),
            ],
        )
        section_group = stable_id("section-group", "root", "p1", "s1")
        subsection_group = stable_id("section-group", "root", "p1", "sub1")
        judge = ScriptedJudge({
            "p2:section_matching:new_to_group:s2": section_group,
            "p2:section_matching:new_to_group:sub2": subsection_group,
            f"p2:section_matching:group_to_new:{section_group}": "s2",
            f"p2:section_matching:group_to_new:{subsection_group}": "sub2",
        })
        with tempfile.TemporaryDirectory() as directory:
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                judge,
                Path(directory) / "revision",
            )
            runner.run([first, second])

        section_matches = [
            request for request in judge.requests
            if request.stage_id == "section_matching" and request.paper_index == 2
        ]
        self.assertTrue(section_matches)
        self.assertTrue(all(request.skill_ref for request in section_matches))
        paragraph_forward = next(
            request for request in judge.requests
            if request.key == "p2:paragraph_matching:new_to_group:lead2"
        )
        candidate_units = {
            member["paragraph_id"]
            for candidate in paragraph_forward.context["candidates"]
            for member in candidate["members"]
        }
        self.assertEqual(candidate_units, {"lead1", "detail1"})
        contains = [
            event for event in runner.journal.events
            if event["action"] == "edge_created" and event["kind"] == "contains"
        ]
        self.assertEqual(len(contains), 2)


if __name__ == "__main__":
    unittest.main()
