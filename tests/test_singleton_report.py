"""Singleton diagnostics distinguish exposure, decisions, and recovery eligibility."""

import json
import tempfile
import unittest
from pathlib import Path

from test_incremental_graph import CONFIG_PATH, ScriptedJudge, paper

from pipeline.incremental_graph.configuration import load_pipeline_config
from pipeline.incremental_graph.runner import IncrementalGraphRunner
from pipeline.incremental_graph.singleton_report import (
    build_singleton_report,
    write_singleton_report,
)


def node(node_id, paper, unit, *, level="paragraph", parent="scope"):
    return {
        "action": "node_created",
        "node_id": node_id,
        "level": level,
        "parent_id": parent,
        "member": {"paper_id": paper, "unit_id": unit, "ordinal": 1},
    }


def match(source, target, candidates, direction, attempt):
    return {
        "action": "match_recorded",
        "level": "paragraph",
        "paper_index": 2,
        "source_id": source,
        "target_id": target,
        "candidate_ids": candidates,
        "direction": direction,
        "attempt_id": attempt,
    }


def events():
    return [
        {"action": "paper_added", "paper_index": 1, "paper_id": "a"},
        node("scope", "a", "s1", level="section", parent=None),
        node("a1", "a", "p1"),
        node("a2", "a", "p2"),
        node("a3", "a", "p3"),
        {"action": "paper_added", "paper_index": 2, "paper_id": "b"},
        {
            "action": "member_added",
            "node_id": "scope",
            "member": {"paper_id": "b", "unit_id": "s1"},
        },
        match("p1", "a1", ["a1", "a2"], "new_to_group", "forward"),
        match("a1", None, ["p1"], "group_to_new", "reverse"),
        node("b1", "b", "p1"),
    ]


class SingletonReportTest(unittest.TestCase):
    def test_runner_emits_report_without_additional_judgments(self):
        with tempfile.TemporaryDirectory() as directory:
            revision = Path(directory) / "revision"
            judge = ScriptedJudge({})
            runner = IncrementalGraphRunner(load_pipeline_config(CONFIG_PATH), judge, revision)
            runner.run([paper("a", [("s1", "p1", "Source text")])])
            report = json.loads((revision / "reports/singletons.json").read_text(encoding="utf-8"))
            self.assertEqual(report["reason_counts"], {"never_compared": 1})
            self.assertEqual(len(judge.requests), 2)

    def test_exposure_and_one_way_selection_are_not_called_semantic_uniqueness(self):
        report = build_singleton_report(events())
        rows = {(row["paper_id"], row["paragraph_id"]): row for row in report["paragraphs"]}
        self.assertEqual(report["singleton_paragraph_count"], 4)
        self.assertEqual(rows["a", "p1"]["reason"], "selected_without_acceptance")
        self.assertEqual(rows["b", "p1"]["reason"], "selected_without_acceptance")
        self.assertEqual(rows["a", "p2"]["reason"], "candidate_only")
        self.assertEqual(rows["a", "p3"]["reason"], "never_compared")
        self.assertEqual(rows["a", "p1"]["selected_by_attempt_ids"], ["forward"])
        self.assertEqual(rows["a", "p3"]["recovery"]["status"], "no_established_group_in_scope")
        self.assertEqual(rows["a", "p3"]["recovery"]["other_paper_singleton_peers"], 1)

    def test_abstention_is_distinct_from_no_exposure(self):
        history = events()
        history[7]["target_id"] = None
        report = build_singleton_report(history)
        rows = {(r["paper_id"], r["paragraph_id"]): r for r in report["paragraphs"]}
        self.assertEqual(rows["a", "p1"]["reason"], "model_abstained")
        self.assertEqual(rows["b", "p1"]["reason"], "model_abstained")

    def test_recovery_evidence_uses_members_at_judgment_time_not_future_members(self):
        history = events()
        history.extend(
            [
                node("group", "c", "p1"),
                {
                    "action": "member_added",
                    "node_id": "group",
                    "member": {"paper_id": "d", "unit_id": "p1"},
                },
                match("a3", None, ["group"], "singleton_to_group", "recovery-forward"),
                match("group", None, ["a3"], "group_to_singleton", "recovery-reverse"),
                {
                    "action": "node_merged",
                    "source_node_id": "a2",
                    "target_node_id": "group",
                    "members": [{"paper_id": "a", "unit_id": "p2"}],
                },
            ]
        )
        report = build_singleton_report(history)
        rows = {(r["paper_id"], r["paragraph_id"]): r for r in report["paragraphs"]}
        self.assertNotIn(("a", "p2"), rows)
        self.assertEqual(rows["a", "p3"]["reason"], "model_abstained")
        self.assertEqual(rows["a", "p3"]["recovery"]["status"], "source_paper_already_in_groups")
        self.assertEqual(rows["b", "p1"]["recovery"]["status"], "eligible_established_group")
        self.assertEqual(report["paragraph_count"], 6)

    def test_writes_only_json_diagnostics_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reports"
            write_singleton_report(events(), output)
            saved = json.loads((output / "singletons.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, build_singleton_report(events()))
            self.assertEqual([path.name for path in output.iterdir()], ["singletons.json"])
            with self.assertRaises(FileExistsError):
                write_singleton_report(events(), output)
