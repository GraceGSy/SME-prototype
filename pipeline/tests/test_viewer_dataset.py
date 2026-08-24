from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_counterbalanced_study import build_study
from viewer_dataset import DatasetValidationError, package_dataset, validate_dataset


PIPELINE_DIR = Path(__file__).resolve().parents[1]
VIEWER_PATH = PIPELINE_DIR / "viz" / "tag_matches_viewer.html"
STUDY_SHELL_PATH = PIPELINE_DIR / "viz" / "counterbalanced_study.html"


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


def make_snapshot_dataset(root: Path) -> None:
    shared_members = [
        {"paper": "paper_a", "unit_id": "pa1", "tag": "What is shared?"},
        {"paper": "paper_b", "unit_id": "pb1", "tag": "What is shared?"},
    ]
    singleton_member = {"paper": "paper_a", "unit_id": "pa2", "tag": "What is unique?"}
    write_json(root / "manifest.json", [
        {"paper_id": "paper_a", "title": "Paper A", "file": "paper_a.json"},
        {"paper_id": "paper_b", "title": "Paper B", "file": "paper_b.json"},
    ])
    write_json(root / "paper_a.json", {
        "paper_id": "paper_a",
        "title": "Paper A",
        "sections": [{"id": "sa1", "text": "Section A", "tag": "What motivates A?"}],
        "paragraphs": [
            {"id": "pa1", "section_id": "sa1", "text": "Shared A", "tag": "What is shared?"},
            {"id": "pa2", "section_id": "sa1", "text": "Unique A", "tag": "What is unique?"},
        ],
    })
    write_json(root / "paper_b.json", {
        "paper_id": "paper_b",
        "title": "Paper B",
        "sections": [{"id": "sb1", "text": "Section B", "tag": "What motivates B?"}],
        "paragraphs": [
            {"id": "pb1", "section_id": "sb1", "text": "Shared B", "tag": "What is shared?"},
        ],
    })
    write_json(root / "bidirectional_matches.json", {"sections": [], "paragraphs": []})
    write_json(root / "final_snapshot.json", {
        "schema_version": 1,
        "mode": "final_snapshot",
        "groups": [{
            "group_id": "shared_1",
            "overarching_question": "What is shared?",
            "members": shared_members,
            "representative_members": shared_members,
        }],
        "singletons": [{
            "group_id": "singleton_1",
            "overarching_question": "What is unique?",
            "members": [singleton_member],
            "representative_members": [singleton_member],
        }],
        "section_groups": [{
            "group_id": "section_1",
            "overarching_question": "What motivates the papers?",
            "members": [
                {"paper": "paper_a", "unit_id": "sa1", "section_id": "sa1"},
                {"paper": "paper_b", "unit_id": "sb1", "section_id": "sb1"},
            ],
        }],
        "stats": {"shared_question_groups": 1, "singleton_questions": 1},
    })


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

    def test_packages_final_snapshot_without_epoch_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "site"
            make_snapshot_dataset(source)

            descriptor = package_dataset(source, output, VIEWER_PATH, "snapshot", "Snapshot")

            self.assertEqual(descriptor["schema_version"], 2)
            self.assertEqual(descriptor["mode"], "final_snapshot")
            self.assertEqual(descriptor["paper_count"], 2)
            self.assertEqual(descriptor["paragraph_count"], 3)
            self.assertTrue((output / "public" / "data" / "final_snapshot.json").is_file())
            self.assertFalse((output / "public" / "data" / "quote_groups.json").exists())
            self.assertFalse((output / "public" / "data" / "epoch_matrix1_reassign_refinement").exists())

    def test_packages_optional_incremental_graph_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "site"
            make_snapshot_dataset(source)
            write_json(source / "graph-replay.json", {
                "schema_version": 1,
                "mode": "incremental_graph_replay",
                "paper_order": ["paper_a", "paper_b"],
                "final_graph_hash": "0" * 64,
                "layouts": {"section": {"group-1": {"x": 0.5, "y": 0.5}}},
                "events": [
                    {
                        "sequence": 1,
                        "event_id": "event-000001",
                        "paper_index": 1,
                        "action": "node_created",
                        "node_id": "group-1",
                        "level": "section",
                        "parent_id": None,
                        "member": {"paper_id": "paper_a", "unit_id": "sa1"},
                    },
                ],
            })

            descriptor = package_dataset(source, output, VIEWER_PATH, "snapshot", "Snapshot")

            self.assertEqual(descriptor["graph_replay_file"], "graph-replay.json")
            self.assertTrue((output / "public" / "data" / "graph-replay.json").is_file())
            self.assertTrue((output / "public" / "graph_replay.js").is_file())
            self.assertTrue((output / "public" / "graph_replay.css").is_file())

    def test_packages_counterbalanced_study_with_both_orders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sme1 = root / "sme1-source"
            sme2 = root / "sme2-source"
            output = root / "site"
            make_dataset(sme1)
            make_snapshot_dataset(sme2)

            config = build_study(sme1, sme2, output, VIEWER_PATH, STUDY_SHELL_PATH)

            self.assertEqual(config["orders"]["1"], ["sme1", "sme2"])
            self.assertEqual(config["orders"]["2"], ["sme2", "sme1"])
            self.assertEqual(config["phases"]["sme1"]["dataset"]["schema_version"], 1)
            self.assertEqual(config["phases"]["sme2"]["dataset"]["schema_version"], 2)
            self.assertTrue((output / "public" / "index.html").is_file())
            self.assertTrue((output / "public" / "study-config.json").is_file())
            self.assertTrue((output / "public" / "sme1" / "data" / "dataset.json").is_file())
            self.assertTrue((output / "public" / "sme2" / "data" / "final_snapshot.json").is_file())

    def test_packages_viz_and_hci_counterbalanced_orders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            viz_sme1 = root / "viz-sme1"
            viz_sme2 = root / "viz-sme2"
            hci_sme1 = root / "hci-sme1"
            hci_sme2 = root / "hci-sme2"
            output = root / "site"
            make_dataset(viz_sme1)
            make_snapshot_dataset(viz_sme2)
            make_dataset(hci_sme1)
            make_snapshot_dataset(hci_sme2)

            config = build_study(
                viz_sme1,
                viz_sme2,
                output,
                VIEWER_PATH,
                STUDY_SHELL_PATH,
                "SME Study",
                hci_sme1,
                hci_sme2,
            )

            self.assertEqual(config["orders"]["3"], ["hci_sme1", "hci_sme2"])
            self.assertEqual(config["orders"]["4"], ["hci_sme2", "hci_sme1"])
            self.assertEqual(config["phases"]["hci_sme1"]["label"], "HCI SME 1 Viewer")
            self.assertEqual(config["phases"]["hci_sme2"]["label"], "HCI SME 2 Viewer")
            self.assertTrue((output / "public" / "hci_sme1" / "data" / "dataset.json").is_file())
            self.assertTrue((output / "public" / "hci_sme2" / "data" / "final_snapshot.json").is_file())


if __name__ == "__main__":
    unittest.main()
