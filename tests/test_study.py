from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from pipeline import study
from pipeline.document import write_json


class StudyBuildTest(unittest.TestCase):
    def test_one_command_writes_manifest_runs_graph_and_packages_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            class FakeHarness:
                config = {
                    "output_dir": "document-results",
                    "study": {
                        "run_root": "runs/studies",
                        "site_dir": "site/user-study",
                        "datasets": {
                            "sample": {"participant_prefix": "SH", "label": "Sample"},
                        },
                    },
                    "datasets": {
                        "sample": {
                            "documents": [
                                {"id": "first", "title": "First"},
                                {"id": "second", "title": "Second"},
                            ],
                        },
                    },
                }

                def questions(self, dataset_name: str) -> None:
                    output = root / "document-results" / dataset_name
                    output.mkdir(parents=True)
                    for document in self.config["datasets"][dataset_name]["documents"]:
                        (output / f"{document['id']}.questions.json").write_text("[]")

            observed: dict[str, object] = {}

            def fake_graph(manifest: Path, run_dir: Path, config: Path) -> dict[str, object]:
                observed["manifest"] = yaml.safe_load(manifest.read_text(encoding="utf-8"))
                observed["run_dir"] = run_dir
                return {"dataset_dir": str(root / "graph-dataset")}

            with (
                patch.object(study, "ROOT", root),
                patch.object(study, "Harness", return_value=FakeHarness()),
                patch.object(study, "run_revision", side_effect=fake_graph),
                patch.object(study, "package_dataset", return_value={"dataset_id": "sample"}),
            ):
                result = study.run_study(Path("pipeline.yaml"), "sample", Path("graph.yaml"))

            papers = observed["manifest"]["papers"]
            self.assertEqual([paper["paper_id"] for paper in papers], ["first", "second"])
            self.assertEqual(result["package"]["dataset"]["dataset_id"], "sample")
            self.assertEqual(observed["run_dir"], root / "runs/studies/sample/graph")

    def test_paragraph_mode_prepares_content_and_skips_section_questions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []

            class FakeHarness:
                config = {
                    "output_dir": "document-results",
                    "study": {
                        "run_root": "runs/studies",
                        "site_dir": "site/user-study",
                        "datasets": {
                            "sample": {"participant_prefix": "SH", "label": "Sample"},
                        },
                    },
                    "datasets": {
                        "sample": {
                            "content_dir": "content",
                            "max_granularity": "paragraph",
                            "question_documents": ["first"],
                            "documents": [
                                {"id": "first", "title": "First"},
                                {"id": "second", "title": "Second"},
                            ],
                        },
                    },
                }

                def prepare(self, dataset_name: str) -> None:
                    calls.append(("prepare", dataset_name))
                    write_json(root / "content" / "first.content.json", [{
                        "section_name": "Scene container",
                        "section_number": None,
                        "paragraphs": [],
                        "subsections": [{
                            "section_name": "Scene 1",
                            "section_number": None,
                            "paragraphs": [
                                {"paragraph_number": 0, "text": "Opening."},
                                {"paragraph_number": 1, "text": "Resolution."},
                            ],
                        }],
                    }])

                def questions(self, dataset_name: str) -> None:
                    raise AssertionError("paragraph mode must skip structural questions")

            observed = {}

            def fake_graph(manifest: Path, run_dir: Path, config: Path) -> dict[str, object]:
                observed["manifest"] = yaml.safe_load(manifest.read_text(encoding="utf-8"))
                observed["document"] = study.read_json(manifest.parent / "first.json")
                return {"dataset_dir": str(root / "graph-dataset")}

            with (
                patch.object(study, "ROOT", root),
                patch.object(study, "Harness", return_value=FakeHarness()),
                patch.object(study, "run_revision", side_effect=fake_graph),
                patch.object(study, "package_dataset", return_value={"dataset_id": "sample"}),
            ):
                study.run_study(Path("pipeline.yaml"), "sample", Path("graph.yaml"))

            self.assertEqual(calls, [("prepare", "sample")])
            self.assertEqual(observed["manifest"]["max_granularity"], "paragraph")
            self.assertEqual(
                [paper["paper_id"] for paper in observed["manifest"]["papers"]],
                ["first"],
            )
            self.assertEqual(len(observed["document"]), 1)
            self.assertEqual(observed["document"][0]["subsections"], [])
            self.assertEqual(len(observed["document"][0]["paragraphs"]), 2)


if __name__ == "__main__":
    unittest.main()
