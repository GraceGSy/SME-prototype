from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from viewer_dataset import DatasetValidationError, package_dataset, validate_dataset


PIPELINE_DIR = Path(__file__).resolve().parents[1]
VIEWER_PATH = PIPELINE_DIR / "viz" / "tag_matches_viewer.html"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def make_dataset(root: Path) -> None:
    member = {"paper": "paper_a", "unit_id": "pa1", "tag": "What happened?"}
    group = {
        "group_id": "group_1",
        "overarching_question": "What happened?",
        "members": [member],
        "representative_members": [member],
    }
    write_json(root / "manifest.json", [{"paper_id": "paper_a", "title": "Paper A", "file": "paper_a.json"}])
    write_json(root / "paper_a.json", {
        "paper_id": "paper_a",
        "title": "Paper A",
        "sections": [{"id": "s1", "text": "Section text", "tag": "What is this section?"}],
        "paragraphs": [
            {
                "id": "pa1",
                "section_id": "s1",
                "text": "Paragraph text",
                "tag": "What happened?",
            }
        ],
    })
    write_json(root / "bidirectional_matches.json", {"sections": [], "paragraphs": []})
    write_json(root / "quote_groups.json", {"sections": [], "paragraphs": [group]})
    epoch_root = root / "epoch_matrix1_reassign_refinement"
    write_json(epoch_root / "initial_groups.json", [group])
    write_json(
        epoch_root / "epoch1" / "estep.json",
        {"meta": {}, "groups": [{"group_id": "group_1", "members": [member]}]},
    )
    write_json(epoch_root / "epoch1" / "mstep.json", {"groups": [{
        "group_id": "group_1",
        "overarching_question": "What happened?",
        "representative_members": [member],
    }]})
    write_json(epoch_root / "epoch1" / "group_balance.json", [{"group_id": "group_1", "group_balance": 100.0}])
    write_json(epoch_root / "epoch1" / "matrix1.json", {"paper_a:pa1": ["group_1"]})
    write_json(epoch_root / "epoch1" / "matrix2.json", {"group_1": {"paper_a": ["pa1"]}})


class ViewerDatasetTest(unittest.TestCase):
    def test_validates_both_five_paper_outputs(self) -> None:
        datasets = {
            "sections_skills_hybrid_core": 456,
            "sections_skills_hybrid_papers3_core": 392,
        }
        for directory, paragraph_count in datasets.items():
            with self.subTest(directory=directory):
                descriptor = validate_dataset(
                    PIPELINE_DIR / "output" / directory, "test-set", "Test Set"
                )
                self.assertEqual(descriptor["paper_count"], 5)
                self.assertEqual(descriptor["paragraph_count"], paragraph_count)
                self.assertEqual(descriptor["epochs"], [1, 2, 3])
                self.assertEqual(descriptor["default_epoch"], 3)

    def test_packages_only_viewer_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "site"
            make_dataset(source)

            descriptor = package_dataset(source, output, VIEWER_PATH, "sample", "Sample")

            self.assertEqual(descriptor["default_epoch"], 1)
            self.assertTrue((output / "public" / "index.html").is_file())
            self.assertTrue((output / "public" / "data" / "paper_a.json").is_file())
            matrix_path = (
                output
                / "public"
                / "data"
                / "epoch_matrix1_reassign_refinement"
                / "epoch1"
                / "matrix1.json"
            )
            self.assertFalse(matrix_path.exists())

    def test_rejects_unknown_paragraph_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            make_dataset(source)
            estep_path = source / "epoch_matrix1_reassign_refinement" / "epoch1" / "estep.json"
            estep = json.loads(estep_path.read_text(encoding="utf-8"))
            estep["groups"][0]["members"][0]["unit_id"] = "missing"
            write_json(estep_path, estep)

            with self.assertRaisesRegex(DatasetValidationError, "unknown paragraph"):
                validate_dataset(source, "sample", "Sample")


if __name__ == "__main__":
    unittest.main()
