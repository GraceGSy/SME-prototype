"""Break-fix checks for lost text, changed boundaries, and paid extraction reuse."""

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pipeline.extraction import extract_document
from pipeline.files import write_json
from pipeline.incremental_graph.input_data import InputError, load_paper
from pipeline.source_review import inspect_document, review_document, review_path

SOURCE = "First finding.\n\nMiddle evidence.\n\nFinal conclusion."


def document(texts=None):
    return [
        {
            "section_name": "Document",
            "section_number": None,
            "subsections": [],
            "paragraphs": [
                {"paragraph_number": index, "text": text}
                for index, text in enumerate(texts or SOURCE.split("\n\n"))
            ],
        }
    ]


class SourceReviewTest(unittest.TestCase):
    def test_missing_middle_invention_duplication_and_reordering_are_detected(self):
        cases = [
            (["First finding.", "Final conclusion."], "coverage_ok"),
            (["First finding.", "Invented evidence.", "Final conclusion."], "coverage_ok"),
            (
                ["First finding.", "Middle evidence.", "Middle evidence.", "Final conclusion."],
                "coverage_ok",
            ),
            (["Middle evidence.", "First finding.", "Final conclusion."], "order_ok"),
        ]
        for texts, failed_check in cases:
            with self.subTest(texts=texts):
                result = inspect_document(SOURCE, document(texts))
                self.assertFalse(result[failed_check])
                self.assertTrue(result["issues"])

    def test_boundary_check_catches_merges_and_splits_without_changing_text(self):
        for texts in [
            ["First finding. Middle evidence.", "Final conclusion."],
            ["First", "finding.", "Middle evidence.", "Final conclusion."],
        ]:
            with self.subTest(texts=texts):
                content = document(texts)
                before = copy.deepcopy(content)
                result = inspect_document(SOURCE, content)
                self.assertTrue(result["coverage_ok"])
                self.assertTrue(result["order_ok"])
                self.assertFalse(result["boundary_ok"])
                self.assertEqual(content, before)

    def test_printed_headings_are_accounted_for_and_ownership_is_checked(self):
        content = document(["First finding."])
        content[0]["section_name"] = "Findings"
        content.append(
            {**document(["Middle evidence.", "Final conclusion."])[0], "section_name": "Conclusion"}
        )
        source = "Findings\n\nFirst finding.\n\nConclusion\n\nMiddle evidence.\n\nFinal conclusion."
        self.assertFalse(inspect_document(source, content)["issues"])
        content[0]["paragraphs"].append({"paragraph_number": 1, "text": "Middle evidence."})
        content[1]["paragraphs"] = [{"paragraph_number": 0, "text": "Final conclusion."}]
        self.assertFalse(inspect_document(source, content)["order_ok"])

    def test_review_blocks_graph_use_until_approved_and_detects_later_edits(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.txt", root / "content.json"
            source.write_text(SOURCE, encoding="utf-8")
            write_json(output, document())
            with patch("pipeline.source_review.SOURCE_CACHE", root / "cache"):
                review_document(source, output)
                with self.assertRaisesRegex(InputError, "review"):
                    load_paper(output, "paper", "Paper")
                review_document(
                    source,
                    output,
                    approve=True,
                    reviewer="Test reviewer",
                    notes="Checked source and boundaries.",
                )
                self.assertEqual(
                    len(load_paper(output, "paper", "Paper").sections[0].paragraphs), 3
                )
                with_questions = document()
                with_questions[0]["question_this_text_answers"] = (
                    "What findings support the conclusion?"
                )
                write_json(output, with_questions)
                load_paper(output, "paper", "Paper")
                changed = document()
                changed[0]["paragraphs"][1]["text"] = "Changed evidence."
                write_json(output, changed)
                with self.assertRaisesRegex(InputError, "changed"):
                    load_paper(output, "paper", "Paper")
                with self.assertRaisesRegex(ValueError, "issues"):
                    review_document(
                        source,
                        output,
                        approve=True,
                        reviewer="Test reviewer",
                        notes="Cannot waive missing evidence.",
                    )

    def test_approved_source_is_reused_across_paths_without_a_second_model_call(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.txt", root / "content.json"
            source.write_text(SOURCE, encoding="utf-8")
            client = Mock()
            client.run_json_file.return_value = SimpleNamespace(
                value=document(), response_id="r1", usage={"input_tokens": 10}
            )
            with patch("pipeline.source_review.SOURCE_CACHE", root / "cache"):
                extract_document(source, output, domain="academic", title="Source", client=client)
                snapshot = client.run_json_file.call_args.args[2]
                self.assertEqual(snapshot.read_bytes(), source.read_bytes())
                self.assertNotEqual(snapshot, source)
                review_document(
                    source,
                    output,
                    approve=True,
                    reviewer="Test reviewer",
                    notes="Checked all three paragraphs.",
                )
                other_source, other_output = root / "copy.txt", root / "copy.json"
                other_source.write_bytes(source.read_bytes())
                with patch("pipeline.extraction.create_skill_client") as adapter:
                    extract_document(
                        other_source,
                        other_output,
                        domain="academic",
                        title="Copy",
                        provider="openai",
                    )
                    extract_document(source, output, domain="academic", title="Source")
                    adapter.assert_not_called()
                self.assertEqual(client.run_json_file.call_count, 1)
                self.assertEqual(
                    json.loads(output.read_text()), json.loads(other_output.read_text())
                )
                self.assertEqual(
                    json.loads(review_path(other_output).read_text())["status"], "approved"
                )
                load_paper(other_output, "copy", "Copy")

    def test_xhtml_review_preserves_paragraphs_and_escapes_source_markup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.xhtml", root / "content.json"
            source.write_text(
                "<html><head><title>Metadata</title></head><body><p>First finding.</p><p>&lt;script&gt;Middle evidence.&lt;/script&gt;</p><p>Final conclusion.</p></body></html>",
                encoding="utf-8",
            )
            write_json(
                output,
                document(
                    ["First finding.", "<script>Middle evidence.</script>", "Final conclusion."]
                ),
            )
            with patch("pipeline.source_review.SOURCE_CACHE", root / "cache"):
                result = review_document(source, output)
            self.assertFalse(result["issues"])
            html = output.with_suffix(".review.html").read_text(encoding="utf-8")
            self.assertIn("&lt;script&gt;Middle evidence.&lt;/script&gt;", html)
            self.assertNotIn("<script>", html)


if __name__ == "__main__":
    unittest.main()
