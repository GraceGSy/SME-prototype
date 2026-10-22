"""Offline integration of prepared documents, ordered runs, and immutable revisions."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml
from test_incremental_graph import CONFIG_PATH, ScriptedJudge

from pipeline.files import write_json
from pipeline.incremental_graph.graph import stable_id
from pipeline.incremental_graph.runs import add_papers, retry_graph, start_graph
from pipeline.source_review import review_document


def manifest(root: Path, ids: list[str], name: str) -> Path:
    for paper_id in ids:
        write_json(
            root / f"{paper_id}.json",
            [
                {
                    "section_name": paper_id,
                    "section_number": None,
                    "subsections": [],
                    "question_this_text_answers": "What happens?",
                    "paragraphs": [
                        {
                            "paragraph_number": 0,
                            "text": f"Evidence from {paper_id}.",
                            "question_this_text_answers": "What happens?",
                        }
                    ],
                }
            ],
        )
    path = root / f"{name}.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "max_granularity": "paragraph",
                "papers": [{"paper_id": i, "title": i, "file": f"{i}.json"} for i in ids],
            }
        ),
        encoding="utf8",
    )
    return path


class GraphRunTest(unittest.TestCase):
    def test_sequence_and_separate_additions_produce_the_same_realignments(self):
        structural = stable_id("section-group", "root", "a", "s0001")
        target = stable_id("paragraph-group", structural, "a", "s0001.p0001")
        singleton = stable_id("paragraph-group", structural, "b", "s0001.p0001")
        matches = {
            "c:paragraph_matching:new_to_group:s0001.p0001": target,
            f"c:paragraph_matching:group_to_new:{target}": "s0001.p0001",
            f"c:paragraph_rerepresentation:singleton_to_group:{singleton}": target,
            f"c:paragraph_rerepresentation:group_to_singleton:{target}": singleton,
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initial = manifest(root, ["a", "b"], "initial")
            third = manifest(root, ["c"], "third")
            fourth = manifest(root, ["d"], "fourth")
            additions = manifest(root, ["c", "d"], "additions")
            complete = manifest(root, ["a", "b", "c", "d"], "complete")
            with patch(
                "pipeline.incremental_graph.runs.CachedJudgments",
                side_effect=lambda *args, **kwargs: ScriptedJudge(matches),
            ):
                whole = start_graph(complete, root / "whole", CONFIG_PATH)
                start_graph(initial, root / "batch", CONFIG_PATH)
                batch = add_papers(additions, root / "batch")
                start_graph(initial, root / "single", CONFIG_PATH)
                add_papers(third, root / "single")
                single = add_papers(fourth, root / "single")
            self.assertEqual(whole["graph_hash"], batch["graph_hash"])
            self.assertEqual(whole["graph_hash"], single["graph_hash"])
            report = json.loads((Path(single["dataset_dir"]) / "correspondences.json").read_text())
            self.assertEqual(report["stats"]["paragraph_rerepresented_members"], 1)

    def test_start_add_and_retry_preserve_order_and_frozen_sources(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = manifest(root, ["a", "b"], "first")
            third = manifest(root, ["c"], "third")
            run = root / "run"
            source = root / "a.txt"
            source.write_text("Evidence from a.", encoding="utf-8")
            with patch("pipeline.source_review.SOURCE_CACHE", root / "source-cache"):
                review_document(
                    source,
                    root / "a.json",
                    approve=True,
                    reviewer="Test reviewer",
                    notes="Checked source paragraph.",
                )
            with patch(
                "pipeline.incremental_graph.runs.CachedJudgments",
                return_value=ScriptedJudge({}),
            ):
                initial = start_graph(first, run, CONFIG_PATH)
                original = (Path(initial["dataset_dir"]) / "a.json").read_bytes()
                (root / "a.json").write_text("malformed external source after initial run")
                added = add_papers(third, run)
                retried = retry_graph(run)
            self.assertEqual(added["paper_order"], ["a", "b", "c"])
            self.assertEqual(added["graph_hash"], retried["graph_hash"])
            self.assertEqual((Path(initial["dataset_dir"]) / "a.json").read_bytes(), original)
            self.assertEqual((Path(added["dataset_dir"]) / "a.json").read_bytes(), original)
            self.assertEqual(
                json.loads((run / "inputs/revision-0001/paper-0001.review.json").read_text()),
                json.loads((run / "inputs/revision-0003/paper-0001.review.json").read_text()),
            )

    def test_rejects_one_paper_start_and_duplicate_append_before_judgments(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            one = manifest(root, ["a"], "one")
            two = manifest(root, ["a", "b"], "two")
            with patch(
                "pipeline.incremental_graph.runs.CachedJudgments",
                return_value=ScriptedJudge({}),
            ) as provider:
                with self.assertRaisesRegex(ValueError, "at least two"):
                    start_graph(one, root / "invalid", CONFIG_PATH)
                provider.assert_not_called()
                self.assertFalse((root / "invalid").exists())
                start_graph(two, root / "run", CONFIG_PATH)
                provider.reset_mock()
                with self.assertRaisesRegex(ValueError, "already present"):
                    add_papers(one, root / "run")
                provider.assert_not_called()

    def test_failed_first_run_can_retry_without_overwriting_a_revision(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = manifest(root, ["a", "b"], "source")

            class BrokenJudge:
                def judge(self, request):
                    raise RuntimeError("intentional break")

            with patch(
                "pipeline.incremental_graph.runs.CachedJudgments",
                return_value=BrokenJudge(),
            ):
                with self.assertRaisesRegex(RuntimeError, "intentional break"):
                    start_graph(source, root / "run", CONFIG_PATH)
            state = json.loads((root / "run/run.json").read_text())
            self.assertIsNone(state["current_revision"])
            with patch(
                "pipeline.incremental_graph.runs.CachedJudgments",
                return_value=ScriptedJudge({}),
            ):
                result = retry_graph(root / "run")
            self.assertEqual(result["paper_order"], ["a", "b"])
            self.assertEqual(len(list((root / "run/revisions").iterdir())), 2)

    def test_saved_input_tampering_is_rejected_before_any_judgment(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = manifest(root, ["a", "b"], "source")
            with patch(
                "pipeline.incremental_graph.runs.CachedJudgments",
                return_value=ScriptedJudge({}),
            ) as provider:
                start_graph(source, root / "run", CONFIG_PATH)
                frozen = root / "run/inputs/revision-0001/paper-0001.json"
                document = json.loads(frozen.read_text())
                document[0]["paragraphs"][0]["text"] = "Changed but still valid."
                write_json(frozen, document)
                provider.reset_mock()
                with self.assertRaisesRegex(ValueError, "Saved inputs changed"):
                    retry_graph(root / "run")
                provider.assert_not_called()

    def test_policy_change_requires_a_new_run(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = manifest(root, ["a", "b"], "source")
            with patch(
                "pipeline.incremental_graph.runs.CachedJudgments",
                return_value=ScriptedJudge({}),
            ) as provider:
                start_graph(source, root / "run", CONFIG_PATH)
                provider.reset_mock()
                with patch("pipeline.incremental_graph.runs._policy_hash", return_value="changed"):
                    with self.assertRaisesRegex(ValueError, "start a new run"):
                        retry_graph(root / "run")
                provider.assert_not_called()
