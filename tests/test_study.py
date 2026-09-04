from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from pipeline import study


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


if __name__ == "__main__":
    unittest.main()
