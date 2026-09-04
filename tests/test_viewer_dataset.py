from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline.viewer.package import package_dataset, package_study


REPO_ROOT = Path(__file__).resolve().parents[1]
VIEWER_PATH = REPO_ROOT / "pipeline" / "viewer" / "index.html"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


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
        "stats": {"section_nodes": 1, "paragraph_nodes": 2},
    })


class ViewerDatasetTest(unittest.TestCase):
    def test_packages_only_the_canonical_snapshot_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "site"
            make_snapshot_dataset(source)

            descriptor = package_dataset(source, output, VIEWER_PATH, "snapshot", "Snapshot")

            self.assertEqual(descriptor["schema_version"], 1)
            self.assertEqual(descriptor["mode"], "final_snapshot")
            self.assertEqual(descriptor["paper_count"], 2)
            self.assertEqual(descriptor["paragraph_count"], 3)
            self.assertTrue((output / "public" / "data" / "final_snapshot.json").is_file())
            self.assertFalse((output / "public" / "data" / "quote_groups.json").exists())

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
                "layouts": {"section": {"node-1": {"x": 0.5, "y": 0.5}}},
                "hierarchy_layouts": {"section": {"node-1": {"x": 0.5, "y": 0.25}}},
                "events": [{
                    "sequence": 1,
                    "event_id": "event-000001",
                    "paper_index": 1,
                    "action": "node_created",
                    "node_id": "node-1",
                    "level": "section",
                    "parent_id": None,
                    "member": {"paper_id": "paper_a", "unit_id": "sa1"},
                }],
            })

            descriptor = package_dataset(source, output, VIEWER_PATH, "snapshot", "Snapshot")

            self.assertEqual(descriptor["graph_replay_file"], "graph-replay.json")
            self.assertTrue((output / "public" / "data" / "graph-replay.json").is_file())
            self.assertTrue((output / "public" / "graph_replay.js").is_file())

    def test_packages_participant_routed_study_datasets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "site"
            make_snapshot_dataset(source)

            result = package_study({
                "sherlock": {
                    "dataset_dir": source,
                    "participant_prefix": "SH",
                    "label": "Sherlock Holmes Stories",
                },
                "hci": {
                    "dataset_dir": source,
                    "participant_prefix": "HC",
                    "label": "HCI Academic Papers",
                },
            }, output, VIEWER_PATH)

            study = result["study"]
            self.assertEqual(study["datasets"]["SH"]["dataset_id"], "sherlock")
            self.assertEqual(study["participant_number_digits"], 3)
            self.assertTrue((output / "public" / "data" / "study.json").is_file())
            self.assertTrue((output / "public" / "data" / "hci" / "dataset.json").is_file())
            viewer = (output / "public" / "index.html").read_text(encoding="utf-8")
            self.assertIn("participantGateForm", viewer)


if __name__ == "__main__":
    unittest.main()
