from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline.incremental_graph.configuration import RenderedPrompt, load_pipeline_config
from pipeline.document import QUESTION_FIELD
from pipeline.incremental_graph.graph import QuestionGraph, graph_from_events, stable_id
from pipeline.incremental_graph.input_data import load_manifest, load_paper
from pipeline.incremental_graph.journal import RevisionJournal
from pipeline.incremental_graph.llm import (
    _alias_batch_request,
    _constrain_batch_schema,
    _restore_batch_ids,
    _specialize_rendered_prompt,
)
from pipeline.incremental_graph.models import (
    JudgmentRequest,
    JudgmentResult,
    Paper,
    Paragraph,
    Section,
)
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
            normalized = {QUESTION_FIELD: f"What does {focus} address?"}
        elif request.output_kind == "match_batch":
            prefix = ":".join(request.key.split(":")[:3])
            normalized = {
                "matches": [
                    {
                        "source_id": source_id,
                        "target_id": self.matches.get(f"{prefix}:{source_id}"),
                        "basis": "scripted test decision",
                    }
                    for source_id in request.expected_match_source_ids
                ]
            }
        else:
            normalized = {
                "target_id": self.matches.get(request.key),
                "basis": "scripted test decision",
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
    def test_batch_aliases_preserve_stable_graph_ids(self) -> None:
        request = JudgmentRequest(
            key="p2:paragraph_matching:new_to_group:root:batch",
            paper_index=2,
            stage_id="paragraph_matching",
            output_kind="match_batch",
            prompt_ref="paragraph-to-group-match/v1",
            context_ref="matching",
            context={
                "scope": {"level": "paragraph"},
                "focus": [{"paragraph_id": "paragraph-stable"}],
                "candidates": [{"group_id": "group-stable"}],
            },
            expected_match_source_ids=["paragraph-stable"],
            allowed_match_ids=["group-stable"],
        )

        aliased, aliases = _alias_batch_request(request)

        self.assertEqual(aliased.expected_match_source_ids, ["S0001"])
        self.assertEqual(aliased.allowed_match_ids, ["T0001"])
        self.assertEqual(aliased.context["focus"][0]["selection_id"], "S0001")
        self.assertEqual(aliased.context["focus"][0]["paragraph_id"], "paragraph-stable")
        self.assertEqual(aliased.context["candidates"][0]["selection_id"], "T0001")
        constrained_schema = _constrain_batch_schema(
            {
                "properties": {
                    "matches": {
                        "items": {
                            "properties": {
                                "source_id": {"type": "string"},
                                "target_id": {"type": ["string", "null"]},
                            }
                        }
                    }
                }
            },
            aliased,
        )
        properties = constrained_schema["properties"]["matches"]["items"]["properties"]
        self.assertEqual(properties["source_id"]["enum"], ["S0001"])
        self.assertEqual(
            properties["target_id"]["anyOf"],
            [
                {"type": "string", "enum": ["T0001"]},
                {"type": "null"},
            ],
        )
        rendered = RenderedPrompt(
            system="system",
            user="user",
            schema={"type": "object"},
            prompt_hash="prompt-hash",
            context_hash="context-hash",
            schema_hash="original-schema-hash",
        )
        question_request = request.model_copy(update={
            "output_kind": "question",
            "expected_match_source_ids": [],
            "allowed_match_ids": [],
        })
        self.assertIs(_specialize_rendered_prompt(rendered, question_request), rendered)
        self.assertEqual(
            _restore_batch_ids({
                "matches": [{
                    "source_id": "S0001",
                    "target_id": "T0001",
                    "basis": "same role",
                }]
            }, aliases),
            {
                "matches": [{
                    "source_id": "paragraph-stable",
                    "target_id": "group-stable",
                    "basis": "same role",
                }]
            },
        )

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
        self.assertNotIn("section_group_questions", called_stages)
        self.assertNotIn("paragraph_group_questions", called_stages)
        generated_questions = {
            data["level"]: data["generated_question"]
            for _, data in runner.question_graph.nodes()
        }
        self.assertEqual(generated_questions["section"], "What does the section establish?")
        self.assertEqual(generated_questions["paragraph"], "What does the paragraph establish?")
        deterministic_events = [
            event for event in runner.journal.events
            if event["action"] == "question_generated"
        ]
        self.assertTrue(deterministic_events)
        self.assertTrue(all(event["source"] == "member_question" for event in deterministic_events))

    def test_rejects_noncanonical_pseudo_sections(self) -> None:
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

            with self.assertRaisesRegex(ValueError, "canonical document"):
                load_paper(path, "paper-a", "Paper A")

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

            normalized = load_paper(
                path,
                "paper-a",
                "Paper A",
                max_granularity="subsection",
            )

            section = normalized.sections[0]
            subsection = normalized.sections[1]
            self.assertEqual(section.question, "How does the method work?")
            self.assertEqual(section.ordinal, 1)
            self.assertEqual(section.text, "Method overview.\n\nImplementation details.")
            self.assertEqual([paragraph.id for paragraph in section.paragraphs], ["s0001.p0001"])
            self.assertEqual(subsection.kind, "subsection")
            self.assertEqual(subsection.id, "s0001.ss0001")
            self.assertEqual(subsection.parent_id, "s0001")
            self.assertEqual(subsection.family_id, "s0001")
            self.assertEqual(subsection.ordinal, 2)
            self.assertEqual(subsection.paragraphs[0].question, "How was it implemented?")

    def test_section_granularity_collapses_subsection_paragraphs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.json"
            path.write_text(json.dumps([{
                "section_name": "Method",
                "section_number": "3",
                "paragraphs": [{"paragraph_number": 0, "text": "Overview."}],
                "subsections": [{
                    "section_name": "Implementation",
                    "section_number": "3.1",
                    "paragraphs": [{"paragraph_number": 0, "text": "Details."}],
                }],
            }]), encoding="utf-8")

            normalized = load_paper(path, "paper-a", "Paper A")

        self.assertEqual(len(normalized.sections), 1)
        self.assertEqual(
            [paragraph.id for paragraph in normalized.sections[0].paragraphs],
            ["s0001.p0001", "s0001.ss0001.p0001"],
        )
        self.assertEqual(normalized.sections[0].text, "Overview.\n\nDetails.")

    def test_paragraph_granularity_skips_structural_judgments(self) -> None:
        papers = [
            paper("p1", [("s1", "a1", "first story")]),
            paper("p2", [("s2", "b1", "second story")]),
        ]
        shared_root = stable_id("section-group", "root", "p1", "s1")
        paragraph_group = stable_id("paragraph-group", shared_root, "p1", "a1")
        judge = ScriptedJudge({
            "p2:paragraph_matching:new_to_group:b1": paragraph_group,
            f"p2:paragraph_matching:group_to_new:{paragraph_group}": "b1",
        })

        with tempfile.TemporaryDirectory() as directory:
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                judge,
                Path(directory) / "revision",
                max_granularity="paragraph",
            )
            summary = runner.run(papers)

        section_nodes = list(runner.question_graph.nodes("section"))
        self.assertEqual(len(section_nodes), 1)
        self.assertEqual(
            {member["paper_id"] for member in section_nodes[0][1]["members"]},
            {"p1", "p2"},
        )
        self.assertFalse(any(request.stage_id.startswith("section_") for request in judge.requests))
        paragraph_questions = [
            request for request in judge.requests if request.stage_id == "paragraph_questions"
        ]
        self.assertEqual(len(paragraph_questions), 2)
        self.assertTrue(all(request.output_kind == "question" for request in paragraph_questions))
        self.assertTrue(all(request.max_tokens == 256 for request in paragraph_questions))
        expected_context = {
            "paper",
            "previous_paragraph",
            "paragraph",
            "next_paragraph",
        }
        self.assertTrue(
            all(set(request.context) == expected_context for request in paragraph_questions)
        )
        paragraph_matches = [
            request
            for request in judge.requests
            if request.stage_id == "paragraph_matching" and request.paper_index == 2
        ]
        self.assertEqual(len(paragraph_matches), 2)
        self.assertTrue(all(request.output_kind == "match_batch" for request in paragraph_matches))
        paragraph_group_questions = [
            request
            for request in judge.requests
            if request.stage_id == "paragraph_group_questions"
        ]
        self.assertEqual(len(paragraph_group_questions), 1)
        self.assertEqual(paragraph_group_questions[0].output_kind, "question")
        self.assertEqual(paragraph_group_questions[0].max_tokens, 256)
        self.assertEqual(summary["max_granularity"], "paragraph")

    def test_paragraph_questions_use_one_bounded_request_per_paragraph(self) -> None:
        document = Paper(
            paper_id="p1",
            title="P1",
            sections=[Section(
                id="s1",
                label="Whole document",
                text="First paragraph.\n\nSecond paragraph.",
                paragraphs=[
                    Paragraph(id="a1", text="First paragraph."),
                    Paragraph(id="a2", text="Second paragraph."),
                ],
            )],
        )
        judge = ScriptedJudge({})

        with tempfile.TemporaryDirectory() as directory:
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                judge,
                Path(directory) / "revision",
                max_granularity="paragraph",
            )
            runner.run([document])

        requests = [
            request
            for request in judge.requests
            if request.stage_id == "paragraph_questions"
        ]
        self.assertEqual(
            [request.key for request in requests],
            [
                "p1:paragraph_questions:a1",
                "p1:paragraph_questions:a2",
            ],
        )
        self.assertTrue(all(request.output_kind == "question" for request in requests))
        self.assertTrue(all(request.max_tokens == 256 for request in requests))
        self.assertTrue(all("section" not in request.context for request in requests))
        self.assertIsNone(requests[0].context["previous_paragraph"])
        self.assertEqual(
            requests[0].context["next_paragraph"]["full_text"],
            "Second paragraph.",
        )
        self.assertEqual(
            requests[1].context["previous_paragraph"]["full_text"],
            "First paragraph.",
        )
        self.assertIsNone(requests[1].context["next_paragraph"])

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
            self.assertEqual(len(graph.nodes[paragraph_group_a]["members"]), 3)
            self.assertNotIn("classification", graph.nodes[group_a])
            self.assertNotIn("classification", graph.nodes[paragraph_group_a])
            p3_paragraph_match = next(
                request
                for request in runner.judge.requests
                if request.stage_id == "paragraph_matching"
                and request.key.startswith("p3:paragraph_matching:new_to_group:")
                and any(item["paragraph_id"] == "pa3" for item in request.context["focus"])
            )
            candidate = next(
                item
                for item in p3_paragraph_match.context["candidates"]
                if item["group_id"] == paragraph_group_a
            )
            self.assertEqual(
                {member["paragraph_id"] for member in candidate["members"]},
                {"pa", "pa2"},
            )
            first_paragraph_request = next(
                index
                for index, request in enumerate(runner.judge.requests)
                if request.stage_id.startswith("paragraph_")
            )
            last_section_request = max(
                index
                for index, request in enumerate(runner.judge.requests)
                if request.stage_id.startswith("section_")
            )
            self.assertLess(last_section_request, first_paragraph_request)
            model_group_question_stages = {
                request.stage_id for request in runner.judge.requests
                if request.stage_id.endswith("group_questions")
            }
            self.assertEqual(
                model_group_question_stages,
                {"section_group_questions", "paragraph_group_questions"},
            )
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
            correspondences = json.loads(
                (revision / "dataset" / "correspondences.json").read_text(encoding="utf-8")
            )
            section_fan_in = [
                item
                for row in correspondences["levels"]["section"]
                for item in row["fan_in"]
            ]
            self.assertEqual(section_fan_in, [])
            self.assertEqual(correspondences["stats"]["section_fan_in_groups"], 0)
            self.assertEqual(correspondences["stats"]["paragraph_fan_in_groups"], 0)
            self.assertTrue(
                any(
                    event["action"] == "match_recorded"
                    and event["source_id"] == group_b
                    and event["target_id"] == "a3"
                    for event in runner.journal.events
                )
            )
            descriptor = validate_dataset(revision / "dataset", "incremental", "Incremental")
            self.assertEqual(descriptor["graph_replay_file"], "graph-replay.json")

    def test_section_correspondence_table_ignores_unrequited_claims(self) -> None:
        first = Paper(
            paper_id="p1",
            title="P1",
            sections=[
                Section(id="s1", label="Method", text="Method", family_id="s1"),
                Section(
                    id="sub1",
                    label="Detail",
                    text="Detail",
                    kind="subsection",
                    parent_id="s1",
                    family_id="s1",
                    ordinal=2,
                ),
            ],
        )
        second = Paper(
            paper_id="p2",
            title="P2",
            sections=[Section(id="s2", label="System", text="System")],
        )
        section_group = stable_id("section-group", "root", "p1", "s1")
        subsection_group = stable_id("section-group", "root", "p1", "sub1")
        matches = {
            "p2:section_matching:new_to_group:s2": section_group,
            f"p2:section_matching:group_to_new:{section_group}": "s2",
            f"p2:section_matching:group_to_new:{subsection_group}": "s2",
        }

        with tempfile.TemporaryDirectory() as directory:
            revision = Path(directory) / "revision"
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                ScriptedJudge(matches),
                revision,
            )
            runner.run([first, second])
            report = json.loads(
                (revision / "dataset" / "correspondences.json").read_text(encoding="utf-8")
            )
            markdown = (revision / "dataset" / "correspondences.md").read_text(encoding="utf-8")

        self.assertEqual(report["stats"]["section_fan_in_groups"], 0)
        self.assertTrue(all(not row["fan_in"] for row in report["levels"]["section"]))
        self.assertIn("**Method (whole)**", markdown)
        self.assertNotIn("Method > Detail", markdown)

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
            self.assertFalse((revision / "dataset" / "graph_categories.json").exists())
            snapshot = json.loads(
                (revision / "dataset" / "final_snapshot.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                set(snapshot["stats"]),
                {"section_nodes", "paragraph_nodes"},
            )

    def test_cross_level_structure_and_exact_node_paragraph_scope(self) -> None:
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
            if request.stage_id == "paragraph_matching"
            and request.key.startswith("p2:paragraph_matching:new_to_group:")
            and any(item["paragraph_id"] == "lead2" for item in request.context["focus"])
        )
        candidate_units = {
            member["paragraph_id"]
            for candidate in paragraph_forward.context["candidates"]
            for member in candidate["members"]
        }
        self.assertEqual(candidate_units, {"lead1"})
        detail_forward = next(
            request for request in judge.requests
            if request.stage_id == "paragraph_matching"
            and request.key.startswith("p2:paragraph_matching:new_to_group:")
            and any(item["paragraph_id"] == "detail2" for item in request.context["focus"])
        )
        detail_candidates = {
            member["paragraph_id"]
            for candidate in detail_forward.context["candidates"]
            for member in candidate["members"]
        }
        self.assertEqual(detail_candidates, {"detail1"})
        contains = [
            event for event in runner.journal.events
            if event["action"] == "edge_created" and event["kind"] == "contains"
        ]
        self.assertEqual(len(contains), 2)

    def test_structural_rerepresentation_merges_singleton_before_paragraph_pass(self) -> None:
        first = Paper(
            paper_id="p1",
            title="P1",
            sections=[
                Section(
                    id="shared1",
                    label="Shared",
                    text="Shared structural role.",
                    paragraphs=[Paragraph(id="a1", text="Shared paragraph.")],
                ),
                Section(id="unique1", label="Unique", text="Unique structural role."),
            ],
        )
        second = Paper(
            paper_id="p2",
            title="P2",
            sections=[Section(
                id="shared2",
                label="Shared",
                text="Second shared structural role.",
                paragraphs=[Paragraph(id="b1", text="Second shared paragraph.")],
            )],
        )
        third = Paper(
            paper_id="p3",
            title="P3",
            sections=[
                Section(
                    id="root3",
                    label="Root",
                    text="Third root.",
                    paragraphs=[Paragraph(id="c1", text="Third root paragraph.")],
                ),
                Section(
                    id="sub3",
                    label="Detail",
                    text="Third detail with the shared structural role.",
                    kind="subsection",
                    parent_id="root3",
                    family_id="root3",
                    ordinal=2,
                    paragraphs=[Paragraph(id="c2", text="Third detail paragraph.")],
                ),
            ],
        )
        target_id = stable_id("section-group", "root", "p1", "shared1")
        unique_id = stable_id("section-group", "root", "p1", "unique1")
        root_id = stable_id("section-group", "root", "p3", "root3")
        subsection_id = stable_id("section-group", "root", "p3", "sub3")
        matches = {
            "p2:section_matching:new_to_group:shared2": target_id,
            f"p2:section_matching:group_to_new:{target_id}": "shared2",
            f"corpus:section_rerepresentation:singleton_to_group:{subsection_id}": target_id,
        }
        judge = ScriptedJudge(matches)

        with tempfile.TemporaryDirectory() as directory:
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                judge,
                Path(directory) / "revision",
            )
            runner.run([first, second, third])

        self.assertNotIn(subsection_id, runner.question_graph.graph)
        self.assertEqual(
            {member["unit_id"] for member in runner.question_graph.members(target_id)},
            {"shared1", "shared2", "sub3"},
        )
        self.assertEqual(
            runner.insertions_by_paper["p3"].section_assignments["sub3"],
            target_id,
        )
        self.assertNotIn(
            f"corpus:section_rerepresentation:singleton_to_group:{unique_id}",
            {request.key for request in judge.requests},
        )
        rerepresentation_request = next(
            request
            for request in judge.requests
            if request.key == f"corpus:section_rerepresentation:singleton_to_group:{subsection_id}"
        )
        self.assertEqual(rerepresentation_request.allowed_match_ids, [target_id])
        self.assertEqual(len(rerepresentation_request.context["focus"]["members"]), 1)
        self.assertTrue(
            all(len(candidate["members"]) > 1 for candidate in rerepresentation_request.context["candidates"])
        )
        regenerated = [
            request
            for request in judge.requests
            if request.stage_id == "section_rerepresentation_questions"
        ]
        self.assertEqual(len(regenerated), 1)
        self.assertEqual(
            regenerated[0].key,
            f"p3:section_rerepresentation_questions:{target_id}",
        )
        self.assertEqual(
            {
                member["section_id"]
                for member in regenerated[0].context["group"]["members"]
            },
            {"shared1", "shared2", "sub3"},
        )
        paragraph_request = next(
            request for request in judge.requests
            if request.stage_id == "paragraph_matching"
            and request.key.startswith("p3:paragraph_matching:new_to_group:")
            and any(item["paragraph_id"] == "c2" for item in request.context["focus"])
        )
        self.assertEqual(paragraph_request.context["scope"]["parent_group_id"], target_id)
        self.assertLess(
            judge.requests.index(regenerated[0]),
            judge.requests.index(paragraph_request),
        )
        self.assertIn(root_id, runner.question_graph.graph)
        self.assertEqual(
            {(source, target) for source, target in runner.question_graph.graph.edges()},
            {(root_id, target_id)},
        )
        merge_event = next(
            event
            for event in runner.journal.events
            if event["action"] == "node_merged"
            and event.get("reason") == "structural_rerepresentation"
        )
        self.assertEqual(merge_event["source_node_id"], subsection_id)
        replayed = graph_from_events(runner.journal.events)
        self.assertEqual(set(replayed.nodes), set(runner.question_graph.graph.nodes))
        self.assertEqual(
            set(replayed.edges(keys=True)),
            set(runner.question_graph.graph.edges(keys=True)),
        )

    def test_structural_rerepresentation_resolves_same_paper_target_conflicts_stably(self) -> None:
        papers = [
            Paper(paper_id="p1", title="P1", sections=[Section(id="s1", text="Shared")]),
            Paper(paper_id="p2", title="P2", sections=[Section(id="s2", text="Shared")]),
            Paper(
                paper_id="p3",
                title="P3",
                sections=[Section(id="x", text="First"), Section(id="y", text="Second")],
            ),
        ]
        target_id = stable_id("section-group", "root", "p1", "s1")
        source_ids = sorted([
            stable_id("section-group", "root", "p3", "x"),
            stable_id("section-group", "root", "p3", "y"),
        ])
        matches = {
            "p2:section_matching:new_to_group:s2": target_id,
            f"p2:section_matching:group_to_new:{target_id}": "s2",
            **{
                f"corpus:section_rerepresentation:singleton_to_group:{source_id}": target_id
                for source_id in source_ids
            },
        }
        judge = ScriptedJudge(matches)

        with tempfile.TemporaryDirectory() as directory:
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                judge,
                Path(directory) / "revision",
            )
            runner.run(papers)

        self.assertNotIn(source_ids[0], runner.question_graph.graph)
        self.assertIn(source_ids[1], runner.question_graph.graph)
        self.assertEqual(len(runner.question_graph.members(target_id)), 3)
        ignored = [
            event
            for event in runner.journal.events
            if event["action"] == "rerepresentation_merge_ignored"
        ]
        self.assertEqual(len(ignored), 1)
        self.assertEqual(ignored[0]["source_group_id"], source_ids[1])
        rerepresentation_requests = [
            request for request in judge.requests
            if request.stage_id == "section_rerepresentation"
        ]
        self.assertEqual(len(rerepresentation_requests), 2)
        self.assertTrue(
            all(request.allowed_match_ids == [target_id] for request in rerepresentation_requests)
        )
        regenerated = [
            request for request in judge.requests
            if request.stage_id == "section_rerepresentation_questions"
        ]
        self.assertEqual(len(regenerated), 1)

    def test_paragraph_fan_in_accepts_only_immediate_neighbors_of_reciprocal_anchor(self) -> None:
        first = Paper(
            paper_id="p1",
            title="P1",
            sections=[Section(
                id="s1",
                label="Section 1",
                text="Anchor section",
                paragraphs=[
                    Paragraph(id="a2", label="2", text="Distant before", ordinal=2),
                    Paragraph(id="a3", label="3", text="Before", ordinal=3),
                    Paragraph(id="a4", label="4", text="Anchor", ordinal=4),
                    Paragraph(id="a5", label="5", text="After", ordinal=5),
                    Paragraph(id="a7", label="7", text="Distant after", ordinal=7),
                ],
            )],
        )
        second = Paper(
            paper_id="p2",
            title="P2",
            sections=[Section(
                id="s2",
                label="Section 2",
                text="Expanded section",
                paragraphs=[
                    Paragraph(id="b3", label="3", text="Before", ordinal=3),
                    Paragraph(id="b4", label="4", text="Reciprocal", ordinal=4),
                    Paragraph(id="b5", label="5", text="After", ordinal=5),
                    Paragraph(id="b7", label="7", text="Distant", ordinal=7),
                ],
            )],
        )
        section_group = stable_id("section-group", "root", "p1", "s1")
        paragraph_group = stable_id("paragraph-group", section_group, "p1", "a4")
        a2_group = stable_id("paragraph-group", section_group, "p1", "a2")
        a3_group = stable_id("paragraph-group", section_group, "p1", "a3")
        a5_group = stable_id("paragraph-group", section_group, "p1", "a5")
        a7_group = stable_id("paragraph-group", section_group, "p1", "a7")
        matches = {
            "p2:section_matching:new_to_group:s2": section_group,
            f"p2:section_matching:group_to_new:{section_group}": "s2",
            "p2:paragraph_matching:new_to_group:b3": paragraph_group,
            "p2:paragraph_matching:new_to_group:b4": paragraph_group,
            "p2:paragraph_matching:new_to_group:b5": paragraph_group,
            "p2:paragraph_matching:new_to_group:b7": paragraph_group,
            f"p2:paragraph_matching:group_to_new:{paragraph_group}": "b4",
            f"p2:paragraph_matching:group_to_new:{a2_group}": "b4",
            f"p2:paragraph_matching:group_to_new:{a3_group}": "b4",
            f"p2:paragraph_matching:group_to_new:{a5_group}": "b4",
            f"p2:paragraph_matching:group_to_new:{a7_group}": "b4",
        }

        with tempfile.TemporaryDirectory() as directory:
            revision = Path(directory) / "revision"
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                ScriptedJudge(matches),
                revision,
            )
            runner.run([first, second])
            report = json.loads(
                (revision / "dataset" / "correspondences.json").read_text(encoding="utf-8")
            )

        member_ids = {
            member["unit_id"] for member in runner.question_graph.members(paragraph_group)
        }
        self.assertEqual(member_ids, {"a3", "a4", "a5", "b3", "b4", "b5"})
        b7_group = next(
            data
            for _, data in runner.question_graph.nodes("paragraph")
            if any(member["unit_id"] == "b7" for member in data["members"])
        )
        self.assertEqual([member["unit_id"] for member in b7_group["members"]], ["b7"])
        fan_in_events = [
            event for event in runner.journal.events
            if event["action"] == "paragraph_fan_in_added"
        ]
        self.assertEqual(
            {event["unit_id"] for event in fan_in_events},
            {"a3", "a5", "b3", "b5"},
        )
        merged_sources = [
            event["source_node_id"]
            for event in runner.journal.events
            if event["action"] == "node_merged"
        ]
        self.assertEqual(merged_sources, sorted([a3_group, a5_group]))
        ignored_sources = {
            event["source_group_id"]
            for event in runner.journal.events
            if event["action"] == "projected_edge_ignored"
            and event["level"] == "paragraph"
        }
        self.assertEqual(ignored_sources, {a2_group, a7_group})
        self.assertTrue(
            any(
                event["action"] == "match_recorded"
                and event["source_id"] == "b7"
                and event["target_id"] == paragraph_group
                for event in runner.journal.events
            )
        )
        self.assertEqual(report["stats"]["section_fan_in_groups"], 0)
        self.assertEqual(report["stats"]["paragraph_fan_in_groups"], 1)
        self.assertEqual(report["stats"]["paragraph_fan_in_members"], 4)
        row = next(
            row for row in report["levels"]["paragraph"]
            if row["group_id"] == paragraph_group
        )
        self.assertEqual(
            row["cells"]["p1"],
            [["¶3", False], ["¶4", True], ["¶5", False]],
        )
        self.assertEqual(
            row["cells"]["p2"],
            [["¶3", False], ["¶4", True], ["¶5", False]],
        )
        group_question = next(
            request for request in runner.judge.requests
            if request.key == f"p2:paragraph_group_questions:{paragraph_group}"
        )
        question_member_ids = {
            member["paragraph_id"] for member in group_question.context["group"]["members"]
        }
        self.assertEqual(
            question_member_ids,
            {"a3", "a4", "a5", "b3", "b4", "b5"},
        )
        self.assertNotIn("provenance", group_question.context)

    def test_third_paper_matches_nodes_and_merges_adjacent_multi_paper_node(self) -> None:
        def make_paper(paper_id: str, section_id: str, paragraph_ids: list[str]) -> Paper:
            return Paper(
                paper_id=paper_id,
                title=paper_id.upper(),
                sections=[Section(
                    id=section_id,
                    text="Section text",
                    paragraphs=[
                        Paragraph(
                            id=paragraph_id,
                            text=f"Paragraph {paragraph_id}",
                            ordinal=int(paragraph_id[-1]),
                        )
                        for paragraph_id in paragraph_ids
                    ],
                )],
            )

        papers = [
            make_paper("p1", "s1", ["a3", "a4"]),
            make_paper("p2", "s2", ["b3", "b4"]),
            make_paper("p3", "s3", ["c4"]),
        ]
        section_group = stable_id("section-group", "root", "p1", "s1")
        adjacent_group = stable_id("paragraph-group", section_group, "p1", "a3")
        anchor_group = stable_id("paragraph-group", section_group, "p1", "a4")
        matches = {
            "p2:section_matching:new_to_group:s2": section_group,
            f"p2:section_matching:group_to_new:{section_group}": "s2",
            "p3:section_matching:new_to_group:s3": section_group,
            f"p3:section_matching:group_to_new:{section_group}": "s3",
            "p2:paragraph_matching:new_to_group:b3": adjacent_group,
            "p2:paragraph_matching:new_to_group:b4": anchor_group,
            f"p2:paragraph_matching:group_to_new:{adjacent_group}": "b3",
            f"p2:paragraph_matching:group_to_new:{anchor_group}": "b4",
            "p3:paragraph_matching:new_to_group:c4": anchor_group,
            f"p3:paragraph_matching:group_to_new:{anchor_group}": "c4",
            f"p3:paragraph_matching:group_to_new:{adjacent_group}": "c4",
        }

        with tempfile.TemporaryDirectory() as directory:
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                ScriptedJudge(matches),
                Path(directory) / "revision",
            )
            runner.run(papers)

        p3_node_match = next(
            request
            for request in runner.judge.requests
            if request.stage_id == "paragraph_matching"
            and request.key.startswith("p3:paragraph_matching:group_to_new:")
            and any(item["group_id"] == adjacent_group for item in request.context["focus"])
        )
        focus_group = next(
            item
            for item in p3_node_match.context["focus"]
            if item["group_id"] == adjacent_group
        )
        self.assertEqual(
            {member["paragraph_id"] for member in focus_group["members"]},
            {"a3", "b3"},
        )
        self.assertNotIn(adjacent_group, runner.question_graph.graph)
        self.assertEqual(
            {member["unit_id"] for member in runner.question_graph.members(anchor_group)},
            {"a3", "a4", "b3", "b4", "c4"},
        )
        fan_in_members = {
            member["unit_id"]
            for member in runner.question_graph.members(anchor_group)
            if member.get("membership_role") == "fan_in"
        }
        self.assertEqual(fan_in_members, {"a3", "b3"})


if __name__ == "__main__":
    unittest.main()
