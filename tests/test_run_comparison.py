"""Cross-run comparison keeps source identity separate from generated graph IDs."""

import tempfile
import unittest
from pathlib import Path

from pipeline.files import read_json, write_json
from pipeline.incremental_graph.compare import compare_revisions, load_revision, write_comparison


class RunComparisonTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_fixture(
        self, name, partitions, *, prefix="node", text_suffix="", question="Shared role"
    ):
        root = self.root / name
        revision = root / "revisions/revision-0001"
        dataset = revision / "dataset"
        papers = sorted({paper for group in partitions for paper in group})
        write_json(
            root / "run.json",
            {
                "current_revision": "revision-0001",
                "latest_revision": "revision-0002",
                "policy_sha256": "historical-policy",
                "config": {"model": {"name": "test"}},
            },
        )
        write_json(
            revision / "summary.json",
            {
                "schema_version": 1,
                "max_granularity": "section",
                "paper_order": papers,
                "paper_count": len(papers),
            },
        )
        write_json(
            dataset / "manifest.json",
            [{"paper_id": paper, "title": paper, "file": f"{paper}.json"} for paper in papers],
        )
        for paper in papers:
            write_json(
                dataset / f"{paper}.json",
                {
                    "paper_id": paper,
                    "title": paper,
                    "sections": [
                        {
                            "id": "s0001",
                            "title": "Section",
                            "text": f"{paper} source{text_suffix}",
                            "parent_id": None,
                            "unit_type": "section",
                        }
                    ],
                    "paragraphs": [
                        {
                            "id": "p0001",
                            "title": "Paragraph",
                            "text": f"{paper} source{text_suffix}",
                            "section_id": "s0001",
                            "family_id": "s0001",
                        }
                    ],
                },
            )

        def group(index, members, level):
            return {
                "group_id": f"{prefix}-{level}-{index}",
                "overarching_question": question,
                "parent_group_id": f"{prefix}-section-{index}" if level == "paragraph" else None,
                "members": [
                    {"paper": paper, "unit_id": "s0001" if level == "section" else "p0001"}
                    for paper in members
                ],
            }

        write_json(
            dataset / "final_snapshot.json",
            {
                "schema_version": 1,
                "mode": "final_snapshot",
                "section_groups": [
                    group(i, members, "section") for i, members in enumerate(partitions)
                ],
                "groups": [
                    group(i, members, "paragraph")
                    for i, members in enumerate(partitions)
                    if len(members) > 1
                ],
                "singletons": [
                    group(i, members, "paragraph")
                    for i, members in enumerate(partitions)
                    if len(members) == 1
                ],
            },
        )
        return root

    def test_node_ids_and_member_order_are_not_correspondence_identity(self):
        a = self.run_fixture("a", [["a", "b"], ["c"]])
        b = self.run_fixture("b", [["c"], ["b", "a"]], prefix="different")
        result = compare_revisions(a, b)
        for data in result["levels"].values():
            self.assertEqual(data["changed_units"], 0)
            self.assertEqual(data["pair_jaccard"], 1)
            self.assertEqual(data["added_pairs"], [])
            self.assertEqual(data["removed_pairs"], [])

    def test_changed_memberships_and_singletons_are_reported(self):
        a = self.run_fixture("a", [["a", "b"], ["c"]])
        b = self.run_fixture("b", [["a"], ["b", "c"]])
        result = compare_revisions(a, b)
        for level, data in result["levels"].items():
            self.assertEqual(data["changed_units"], 3)
            self.assertEqual(data["pair_jaccard"], 0)
            suffix = "s0001" if level == "section" else "p0001"
            self.assertEqual(data["added_pairs"], [(f"b:{suffix}", f"c:{suffix}")])
            self.assertEqual(data["removed_pairs"], [(f"a:{suffix}", f"b:{suffix}")])

    def test_question_changes_are_separate_from_membership_changes(self):
        a = self.run_fixture("a", [["a", "b"]])
        b = self.run_fixture("b", [["a", "b"]], question="New question")
        result = compare_revisions(a, b)
        for data in result["levels"].values():
            self.assertEqual(data["changed_units"], 0)
            self.assertEqual(len(data["question_changes"]), 1)

    def test_extra_documents_do_not_inflate_shared_pair_changes(self):
        a = self.run_fixture("a", [["a", "b"]])
        b = self.run_fixture("b", [["a", "b", "c"]])
        result = compare_revisions(a, b)
        self.assertEqual(result["right_only_papers"], ["c"])
        self.assertEqual(result["levels"]["section"]["changed_units"], 0)
        self.assertEqual(result["levels"]["paragraph"]["changed_units"], 2)
        for data in result["levels"].values():
            self.assertEqual(data["added_pairs"], [])
            self.assertEqual(data["pair_jaccard"], 1)

    def test_changed_source_or_granularity_is_rejected(self):
        a = self.run_fixture("a", [["a", "b"]])
        b = self.run_fixture("b", [["a", "b"]], text_suffix=" changed")
        with self.assertRaisesRegex(ValueError, "source content"):
            compare_revisions(a, b)
        summary = b / "revisions/revision-0001/summary.json"
        write_json(summary, {**read_json(summary), "max_granularity": "paragraph"})
        with self.assertRaisesRegex(ValueError, "different granularities"):
            compare_revisions(a, b)

    def test_run_selects_last_completed_revision_not_latest_attempt(self):
        a = self.run_fixture("a", [["a", "b"]])
        write_json(a / "revisions/revision-0002/failure.json", {"message": "failure"})
        self.assertTrue(load_revision(a)["path"].endswith("revision-0001"))
        with self.assertRaisesRegex(ValueError, "Not a completed"):
            load_revision(a / "revisions/revision-0002")
        self.assertEqual(
            load_revision(a)["path"], load_revision(a / "revisions/revision-0001")["path"]
        )

    def test_html_escapes_sources_and_questions_and_never_overwrites(self):
        a = self.run_fixture("a", [["a", "b"], ["c"]], text_suffix="<script>alert(1)</script>")
        b = self.run_fixture(
            "b",
            [["a"], ["b", "c"]],
            text_suffix="<script>alert(1)</script>",
            question="<img src=x onerror=alert(1)>",
        )
        output = self.root / "report"
        paths = write_comparison(a, b, output)
        html = Path(paths["report"]).read_text(encoding="utf-8")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;img", html)
        self.assertEqual(read_json(Path(paths["data"]))["levels"]["section"]["changed_units"], 3)
        with self.assertRaises(FileExistsError):
            write_comparison(a, b, output)

    def test_no_pairs_is_not_reported_as_perfect_agreement(self):
        a = self.run_fixture("a", [["a"], ["b"]])
        result = compare_revisions(a, a)
        self.assertIsNone(result["levels"]["section"]["pair_jaccard"])


if __name__ == "__main__":
    unittest.main()
