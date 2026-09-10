import unittest
from pathlib import Path

from pipeline.incremental_graph.input_data import load_manifest


class LegalManifestTest(unittest.TestCase):
    def test_uses_printed_subsections_without_losing_paragraphs(self):
        root = Path(__file__).resolve().parents[1] / "datasets/legal"
        for corpus, paragraphs, subsections in [("opinions", 149, 7), ("dissents", 124, 14)]:
            with self.subTest(corpus=corpus):
                manifest, papers = load_manifest(root / f"{corpus}.manifest.yaml")
                self.assertEqual(manifest.max_granularity, "subsection")
                self.assertEqual(len(papers), 5)
                units = [unit for paper in papers for unit in paper.sections]
                self.assertEqual(sum(len(unit.paragraphs) for unit in units), paragraphs)
                children = [unit for unit in units if unit.kind == "subsection"]
                self.assertEqual(len(children), subsections)
                self.assertTrue(all(unit.parent_id for unit in children))
