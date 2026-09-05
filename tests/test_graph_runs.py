"""Offline integration of prepared documents, ordered runs, and immutable revisions."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from pipeline.document import write_json
from pipeline.incremental_graph.runs import start_graph, add_papers, retry_graph
from test_incremental_graph import CONFIG_PATH, ScriptedJudge


def manifest(root: Path, ids: list[str], name: str) -> Path:
    for paper_id in ids:
        write_json(root / f"{paper_id}.json", [{
            "section_name": paper_id, "section_number": None, "subsections": [],
            "question_this_text_answers": "What happens?",
            "paragraphs": [{"paragraph_number": 0, "text": f"Evidence from {paper_id}.",
                            "question_this_text_answers": "What happens?"}],
        }])
    path = root / f"{name}.yaml"
    path.write_text(yaml.safe_dump({
        "schema_version": 1, "max_granularity": "paragraph",
        "papers": [{"paper_id": i, "title": i, "file": f"{i}.json"} for i in ids],
    }), encoding="utf8")
    return path


class GraphRunTest(unittest.TestCase):
    def test_start_add_and_retry_preserve_order_and_frozen_sources(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = manifest(root, ["a", "b"], "first")
            third = manifest(root, ["c"], "third")
            run = root / "run"
            with patch("pipeline.incremental_graph.runs.AnthropicJudgmentProvider", return_value=ScriptedJudge({})):
                initial = start_graph(first, run, CONFIG_PATH)
                original = (Path(initial["dataset_dir"]) / "a.json").read_bytes()
                (root / "a.json").write_text("malformed external source after initial run")
                added = add_papers(third, run)
                retried = retry_graph(run)
            self.assertEqual(added["paper_order"], ["a", "b", "c"])
            self.assertEqual(added["graph_hash"], retried["graph_hash"])
            self.assertEqual((Path(initial["dataset_dir"]) / "a.json").read_bytes(), original)
            self.assertEqual((Path(added["dataset_dir"]) / "a.json").read_bytes(), original)

    def test_rejects_one_paper_start_and_duplicate_append_before_judgments(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            one = manifest(root, ["a"], "one")
            two = manifest(root, ["a", "b"], "two")
            with patch("pipeline.incremental_graph.runs.AnthropicJudgmentProvider", return_value=ScriptedJudge({})) as provider:
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
            with patch("pipeline.incremental_graph.runs.AnthropicJudgmentProvider", return_value=BrokenJudge()):
                with self.assertRaisesRegex(RuntimeError, "intentional break"):
                    start_graph(source, root / "run", CONFIG_PATH)
            state = json.loads((root / "run/run.json").read_text())
            self.assertIsNone(state["current_revision"])
            with patch("pipeline.incremental_graph.runs.AnthropicJudgmentProvider", return_value=ScriptedJudge({})):
                result = retry_graph(root / "run")
            self.assertEqual(result["paper_order"], ["a", "b"])
            self.assertEqual(len(list((root / "run/revisions").iterdir())), 2)
