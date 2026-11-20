"""Offline checks for the user-supplied, paragraph-only Reuters replacement."""

import hashlib
import json
import unittest
from datetime import date
from pathlib import Path

from pipeline.incremental_graph.input_data import load_manifest

ROOT = Path(__file__).resolve().parents[1] / "datasets/reuters-technology"


# The corpus stays out of the public repository; the checks run where it is present.
@unittest.skipUnless(ROOT.is_dir(), "Reuters corpus is not in this checkout")
class ReutersTechnologyCorpusTest(unittest.TestCase):
    def test_manifest_and_reviewed_inputs(self):
        manifest, papers = load_manifest(ROOT / "manifest.yaml")
        sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["articles"]
        self.assertEqual(manifest.max_granularity, "paragraph")
        self.assertEqual(len(papers), 5)
        self.assertEqual([p.paper_id for p in papers], [a["paper_id"] for a in sources])
        self.assertEqual(len({p.paper_id for p in papers}), 5)
        self.assertEqual(sum(len(p.sections[0].paragraphs) for p in papers), 109)
        for article, paper, expected_count in zip(sources, papers, [27, 17, 11, 37, 17]):
            with self.subTest(article=article["paper_id"]):
                self.assertTrue(
                    date(2021, 10, 30) <= date.fromisoformat(article["date"]) <= date(2026, 10, 30)
                )
                content = ROOT / article["file"]
                document = json.loads(content.read_text(encoding="utf-8"))
                paragraphs = document[0]["paragraphs"]
                text = "\n\n".join(p["text"] for p in paragraphs)
                self.assertEqual(len(paper.sections), 1)
                self.assertEqual(len(paragraphs), expected_count)
                self.assertEqual(len(article["paragraph_pages"]), expected_count)
                self.assertEqual(
                    [p["paragraph_number"] for p in paragraphs], list(range(expected_count))
                )
                self.assertTrue(all(p["text"].strip() for p in paragraphs))
                self.assertTrue(all(not p.role_statement for p in paper.sections[0].paragraphs))
                review = json.loads(content.with_suffix(".review.json").read_text(encoding="utf-8"))
                self.assertEqual(review["status"], "approved")
                self.assertEqual(
                    review["source_sha256"],
                    hashlib.sha256((ROOT / article["source_pdf"]).read_bytes()).hexdigest(),
                )
                for unwanted in ["Sign up", "Purchase Licensing", "Reporting by", "Read Next"]:
                    self.assertNotIn(unwanted, text)

    def test_cross_page_paragraph_remains_whole(self):
        article = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["articles"][4]
        document = json.loads((ROOT / article["file"]).read_text(encoding="utf-8"))
        paragraph = document[0]["paragraphs"][7]["text"]
        self.assertEqual(article["paragraph_pages"][7], [2, 3])
        self.assertTrue(paragraph.startswith('"It is running in the background'))
        self.assertTrue(paragraph.endswith("spreadsheet application."))


if __name__ == "__main__":
    unittest.main()
