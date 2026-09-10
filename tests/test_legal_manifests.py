import re
import unittest
from collections import Counter
from pathlib import Path

from pipeline.files import read_json
from pipeline.incremental_graph.input_data import load_manifest


class LegalManifestTest(unittest.TestCase):
    def test_porter_preserves_source_words_and_separate_paragraphs(self):
        root = Path(__file__).resolve().parents[1] / "datasets/legal"
        document = read_json(root / "content/porter_opinion.content.json")
        units = [unit for section in document for unit in [section, *section["subsections"]]]
        paragraphs = [p["text"] for unit in units for p in unit["paragraphs"]]
        self.assertEqual(len(paragraphs), 38)
        self.assertTrue(any(p.startswith("The first communication occurred") for p in paragraphs))
        self.assertTrue(any(p.startswith("The second communication relates") for p in paragraphs))
        focused = next(p for p in paragraphs if p.startswith("Appellant\u2019s Complaint alleges"))
        self.assertEqual(len(focused.split()), 149)
        self.assertEqual(max(len(p.split()) for p in paragraphs), 321)
        source = (root / "raw/porter_opinion.txt").read_text(encoding="utf-8")
        prose = " ".join(
            line
            for line in source.splitlines()
            if not re.fullmatch(r"\s*(?:[IVX]+\.?|[ABC]\.|THACKER, Circuit Judge:)\s*", line)
        )
        self.assertEqual(
            Counter(re.findall(r"\w+", prose.casefold())),
            Counter(re.findall(r"\w+", " ".join(paragraphs).casefold())),
        )

    def test_uses_printed_subsections_without_losing_paragraphs(self):
        root = Path(__file__).resolve().parents[1] / "datasets/legal"
        for corpus, paragraphs, subsections in [("opinions", 173, 7), ("dissents", 124, 14)]:
            with self.subTest(corpus=corpus):
                manifest, papers = load_manifest(root / f"{corpus}.manifest.yaml")
                self.assertEqual(manifest.max_granularity, "subsection")
                self.assertEqual(len(papers), 5)
                units = [unit for paper in papers for unit in paper.sections]
                self.assertEqual(sum(len(unit.paragraphs) for unit in units), paragraphs)
                children = [unit for unit in units if unit.kind == "subsection"]
                self.assertEqual(len(children), subsections)
                self.assertTrue(all(unit.parent_id for unit in children))
