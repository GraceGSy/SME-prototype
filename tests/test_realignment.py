"""Realignment is reciprocal, per insertion, and identical within paragraph scopes."""

import json
import tempfile
import unittest
from pathlib import Path

from test_incremental_graph import CONFIG_PATH, ScriptedJudge, paper

from pipeline.incremental_graph.configuration import load_pipeline_config
from pipeline.incremental_graph.graph import graph_from_events, stable_id
from pipeline.incremental_graph.models import Paragraph
from pipeline.incremental_graph.runner import IncrementalGraphRunner
from pipeline.viewer.package import validate_dataset


class RealignmentTest(unittest.TestCase):
    def test_paragraph_realignment_excludes_other_sections_and_same_paper_groups(self):
        left = stable_id("section-group", "root", "p1", "left1")
        right = stable_id("section-group", "root", "p1", "right1")
        left_paragraph = stable_id("paragraph-group", left, "p1", "a")
        right_paragraph = stable_id("paragraph-group", right, "p1", "x")
        source = stable_id("paragraph-group", left, "p3", "c")
        first = paper("p1", [("left1", "a", "Left"), ("right1", "x", "Right")])
        first.sections[0].paragraphs.append(Paragraph(id="unused", text="Another role", ordinal=2))
        judge = ScriptedJudge(
            {
                "p2:section_matching:new_to_group:left2": left,
                f"p2:section_matching:group_to_new:{left}": "left2",
                "p2:section_matching:new_to_group:right2": right,
                f"p2:section_matching:group_to_new:{right}": "right2",
                "p2:paragraph_matching:new_to_group:b": left_paragraph,
                f"p2:paragraph_matching:group_to_new:{left_paragraph}": "b",
                "p2:paragraph_matching:new_to_group:y": right_paragraph,
                f"p2:paragraph_matching:group_to_new:{right_paragraph}": "y",
                "p3:section_matching:new_to_group:left3": left,
                f"p3:section_matching:group_to_new:{left}": "left3",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH), judge, Path(directory) / "revision"
            )
            runner.run(
                [
                    first,
                    paper("p2", [("left2", "b", "Left"), ("right2", "y", "Right")]),
                    paper("p3", [("left3", "c", "Left")]),
                ]
            )
            requests = [r for r in judge.requests if r.stage_id == "paragraph_rerepresentation"]
            self.assertEqual(len(requests), 2)
            forward = next(r for r in requests if ":singleton_to_group:" in r.key)
            reverse = next(r for r in requests if ":group_to_singleton:" in r.key)
            self.assertEqual(forward.allowed_match_ids, [left_paragraph])
            self.assertEqual(reverse.allowed_match_ids, [source])
            self.assertTrue(
                all(
                    r.paper_index == 3 and r.context["scope"]["parent_group_id"] == left
                    for r in requests
                )
            )
            with self.assertRaisesRegex(ValueError, "same exact parent"):
                runner.question_graph.merge_singleton(
                    source, right_paragraph, paper_index=3, attempt_id="a", reverse_attempt_id="b"
                )
            self.assert_replay_matches(runner)

    def test_structural_forward_match_without_reverse_is_provenance_only(self):
        target = stable_id("section-group", "root", "p1", "a")
        source = stable_id("section-group", "root", "p2", "b")
        judge = ScriptedJudge(
            {
                "p3:section_matching:new_to_group:c": target,
                f"p3:section_matching:group_to_new:{target}": "c",
                f"p3:section_rerepresentation:singleton_to_group:{source}": target,
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH), judge, Path(directory) / "revision"
            )
            runner.run(
                [
                    paper(f"p{i}", [(s, p, "Role")])
                    for i, s, p in ((1, "a", "pa"), (2, "b", "pb"), (3, "c", "pc"))
                ]
            )
            requests = [r for r in judge.requests if r.stage_id == "section_rerepresentation"]
            self.assertEqual(len(requests), 2)
            self.assertIn(source, dict(runner.question_graph.nodes()))
            self.assertEqual(len(runner.question_graph.members(target)), 2)
            self.assertFalse(any(e["action"] == "node_merged" for e in runner.journal.events))

    def assert_replay_matches(self, runner):
        before = json.dumps(runner.journal.events, sort_keys=True)
        replay = graph_from_events(runner.journal.events)
        graph = runner.question_graph.graph
        self.assertEqual(set(replay.nodes), set(graph.nodes))
        self.assertEqual(set(replay.edges(keys=True)), set(graph.edges(keys=True)))
        for node_id, data in graph.nodes(data=True):
            self.assertEqual(replay.nodes[node_id]["parent_id"], data["parent_id"])
            self.assertEqual(
                sorted(
                    replay.nodes[node_id]["members"], key=lambda m: (m["paper_id"], m["unit_id"])
                ),
                sorted(data["members"], key=lambda m: (m["paper_id"], m["unit_id"])),
            )
        self.assertEqual(json.dumps(runner.journal.events, sort_keys=True), before)

    def test_structural_bridge_is_reciprocal_and_visible_to_the_next_paper(self):
        target = stable_id("section-group", "root", "p1", "a")
        source = stable_id("section-group", "root", "p2", "b")
        first_paragraph = stable_id("paragraph-group", target, "p1", "pa")
        moved_paragraph = stable_id("paragraph-group", source, "p2", "pb")
        judge = ScriptedJudge(
            {
                "p3:section_matching:new_to_group:c": target,
                f"p3:section_matching:group_to_new:{target}": "c",
                f"p3:section_rerepresentation:singleton_to_group:{source}": target,
                f"p3:section_rerepresentation:group_to_singleton:{target}": source,
                "p3:paragraph_matching:new_to_group:pc": first_paragraph,
                f"p3:paragraph_matching:group_to_new:{first_paragraph}": "pc",
                f"p3:paragraph_rerepresentation:singleton_to_group:{moved_paragraph}": first_paragraph,
                f"p3:paragraph_rerepresentation:group_to_singleton:{first_paragraph}": moved_paragraph,
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH), judge, Path(directory) / "revision"
            )
            runner.run(
                [
                    paper(f"p{i}", [(s, p, "shared role")])
                    for i, s, p in ((1, "a", "pa"), (2, "b", "pb"), (3, "c", "pc"), (4, "d", "pd"))
                ]
            )
            forward = next(
                r for r in judge.requests if r.key == "p4:section_matching:new_to_group:d"
            )
            candidate = next(c for c in forward.context["candidates"] if c["group_id"] == target)
            self.assertEqual({m["paper_id"] for m in candidate["members"]}, {"p1", "p2", "p3"})
            self.assertEqual(runner.insertions_by_paper["p2"].section_assignments["b"], target)
            self.assertEqual(
                runner.insertions_by_paper["p2"].paragraph_assignments["pb"], first_paragraph
            )
            self.assertEqual(
                {m["paper_id"] for m in runner.question_graph.members(first_paragraph)},
                {"p1", "p2", "p3"},
            )
            self.assertTrue(
                all(
                    m["owner_group_id"] == target
                    for m in runner.question_graph.members(first_paragraph)
                )
            )
            moves = [e for e in runner.journal.events if e["action"] == "node_reparented"]
            self.assertEqual(
                [(e["node_id"], e["parent_id"]) for e in moves], [(moved_paragraph, target)]
            )
            merges = [
                e
                for e in runner.journal.events
                if e["action"] == "node_merged" and e["reason"].endswith("rerepresentation")
            ]
            self.assertEqual(len(merges), 2)
            self.assertTrue(
                all(
                    e["paper_index"] == 3 and e["attempt_id"] != e["reverse_attempt_id"]
                    for e in merges
                )
            )
            for i in range(1, 5):
                self.assertTrue(
                    (
                        runner.revision_dir / "stages" / f"{i:04d}-section_rerepresentation.json"
                    ).is_file()
                )
                self.assertTrue(
                    (
                        runner.revision_dir / "stages" / f"{i:04d}-paragraph_rerepresentation.json"
                    ).is_file()
                )
            creation = next(
                e
                for e in runner.journal.events
                if e["action"] == "node_created" and e["node_id"] == moved_paragraph
            )
            self.assertEqual(creation["member"]["owner_group_id"], source)
            self.assert_replay_matches(runner)
            validate_dataset(runner.revision_dir / "dataset", "bridge", "Bridge")

    def test_paragraph_only_realignment_requires_both_directions(self):
        root = stable_id("section-group", "root", "p1", "a")
        target = stable_id("paragraph-group", root, "p1", "pa")
        source = stable_id("paragraph-group", root, "p2", "pb")
        for forward, reverse in ((target, source), (target, None), (None, source)):
            with (
                self.subTest(forward=forward, reverse=reverse),
                tempfile.TemporaryDirectory() as directory,
            ):
                judge = ScriptedJudge(
                    {
                        "p3:paragraph_matching:new_to_group:pc": target,
                        f"p3:paragraph_matching:group_to_new:{target}": "pc",
                        f"p3:paragraph_rerepresentation:singleton_to_group:{source}": forward,
                        f"p3:paragraph_rerepresentation:group_to_singleton:{target}": reverse,
                    }
                )
                runner = IncrementalGraphRunner(
                    load_pipeline_config(CONFIG_PATH),
                    judge,
                    Path(directory) / "revision",
                    max_granularity="paragraph",
                )
                runner.run(
                    [
                        paper(f"p{i}", [(s, p, "shared role")])
                        for i, s, p in ((1, "a", "pa"), (2, "b", "pb"), (3, "c", "pc"))
                    ]
                )
                requests = [r for r in judge.requests if r.stage_id == "paragraph_rerepresentation"]
                self.assertEqual(len(requests), 2)
                self.assertTrue(
                    all(r.context["scope"]["parent_group_id"] == root for r in requests)
                )
                self.assertFalse(any(r.stage_id.startswith("section_") for r in judge.requests))
                members = runner.question_graph.members(target)
                self.assertEqual(len(members), 3 if forward and reverse else 2)
                self.assertEqual(
                    source in {n for n, _ in runner.question_graph.nodes()},
                    not (forward and reverse),
                )
                self.assert_replay_matches(runner)
