from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline.viewer.package import package_dataset, package_study, validate_dataset, DatasetValidationError
from pipeline.incremental_graph.models import Paper, Section, Paragraph
from pipeline.incremental_graph.graph import QuestionGraph
from pipeline.incremental_graph.journal import RevisionJournal
from pipeline.incremental_graph.export import export_revision


REPO_ROOT = Path(__file__).resolve().parents[1]
VIEWER_PATH = REPO_ROOT / "pipeline" / "viewer" / "index.html"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def make_snapshot_dataset(root: Path) -> None:
    papers = [
        Paper(paper_id="paper_a", title="Paper A", sections=[Section(
            id="sa1", label="Section A", text="Section A", paragraphs=[
                Paragraph(id="pa1", text="Shared A", question="What is shared?"),
                Paragraph(id="pa2", text="Unique A", question="What is unique?", ordinal=2),
            ])]),
        Paper(paper_id="paper_b", title="Paper B", sections=[Section(
            id="sb1", label="Section B", text="Section B", paragraphs=[
                Paragraph(id="pb1", text="Shared B", question="What is shared?"),
            ])]),
    ]
    graph = QuestionGraph(RevisionJournal(root.parent / "fixture-provenance"))
    graph.add_paper("paper_a", "Paper A", 1)
    section = graph.create_group(level="section", parent_id=None, member_id="sa1",
                                 paper_id="paper_a", paper_index=1, ordinal=1)
    shared = graph.create_group(level="paragraph", parent_id=section, member_id="pa1",
                                paper_id="paper_a", paper_index=1, ordinal=1, unit_kind="paragraph")
    single = graph.create_group(level="paragraph", parent_id=section, member_id="pa2",
                                paper_id="paper_a", paper_index=1, ordinal=2, unit_kind="paragraph")
    graph.add_paper("paper_b", "Paper B", 2)
    graph.add_member(section, "sb1", "paper_b", 2, 1)
    graph.add_member(shared, "pb1", "paper_b", 2, 1, unit_kind="paragraph")
    graph.set_question(shared, "What is shared?", 2, None)
    graph.set_question(single, "What is unique?", 2, None)
    export_revision(root, graph, papers)


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
            self.assertFalse((output / "public" / "viz").exists())
            self.assertFalse((output / "public" / "data" / "bidirectional_matches.json").exists())

    def test_packages_optional_incremental_graph_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "site"
            make_snapshot_dataset(source)

            descriptor = package_dataset(source, output, VIEWER_PATH, "snapshot", "Snapshot")

            self.assertEqual(descriptor["graph_replay_file"], "graph-replay.json")
            self.assertTrue((output / "public" / "data" / "graph-replay.json").is_file())
            self.assertTrue((output / "public" / "app.js").is_file())

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

    def test_rejects_malformed_export_without_publishing_site(self) -> None:
        for corruption in ("extra", "text_type", "duplicate", "missing"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source"
                make_snapshot_dataset(source)
                paper = json.loads((source / "paper_a.json").read_text())
                snapshot = json.loads((source / "final_snapshot.json").read_text())
                if corruption == "extra":
                    paper["legacy_field"] = True
                elif corruption == "text_type":
                    paper["paragraphs"][0]["text"] = 5
                elif corruption == "duplicate":
                    snapshot["groups"].append(snapshot["groups"][0])
                else:
                    snapshot["singletons"] = []
                write_json(source / "paper_a.json", paper)
                write_json(source / "final_snapshot.json", snapshot)
                with self.assertRaises(DatasetValidationError):
                    package_dataset(source, root / "site", VIEWER_PATH, "test", "Test")
                self.assertFalse((root / "site").exists())

    def test_optional_replay_can_be_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            make_snapshot_dataset(source)
            (source / "graph-replay.json").unlink()
            self.assertNotIn("graph_replay_file", validate_dataset(source))


if __name__ == "__main__":
    unittest.main()
