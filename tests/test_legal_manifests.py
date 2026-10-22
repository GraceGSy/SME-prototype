import re
import unittest
from collections import Counter
from pathlib import Path

from pipeline.files import read_json
from pipeline.incremental_graph.input_data import load_manifest


class LegalManifestTest(unittest.TestCase):
    def test_dissent_repairs_preserve_confirmed_printed_boundaries(self):
        root = Path(__file__).resolve().parents[1] / "datasets/legal/content"
        expected = {
            "banuelos_jimenez": [
                "In United States v. Mitchell",
                "United States v. Fuller-Ragland",
                "Indeed, the elements",
            ],
            "porter": [
                "First, we must make",
                "Instead, the",
                "I tend to agree with Judge Motz",
                "Let's review the timeline.",
                "More critically, the majority focuses",
            ],
            "westmoreland": ["Tyree admits", "Westmoreland also says", "Westmoreland filed"],
        }
        for case, starts in expected.items():
            document = read_json(root / f"{case}_dissent.content.json")
            paragraphs = [
                p["text"] for s in document for u in [s, *s["subsections"]] for p in u["paragraphs"]
            ]
            for start in starts:
                with self.subTest(case=case, start=start):
                    self.assertTrue(any(p.startswith(start) for p in paragraphs))

    def test_dissent_repairs_preserve_all_source_words(self):
        root = Path(__file__).resolve().parents[1] / "datasets/legal"
        for case, author, count in [
            ("banuelos_jimenez", "GILMAN, Circuit Judge, dissenting.", 23),
            ("porter", "RICHARDSON, Circuit Judge, dissenting:", 71),
            ("westmoreland", "JOHN K. BUSH, Circuit Judge, dissenting.", 61),
        ]:
            with self.subTest(case=case):
                document = read_json(root / f"content/{case}_dissent.content.json")
                units = [u for s in document for u in [s, *s["subsections"]]]
                paragraphs = [p["text"] for u in units for p in u["paragraphs"]]
                self.assertEqual(len(paragraphs), count)
                source = (root / f"raw/{case}_dissent.txt").read_text(encoding="utf-8")
                source = source.replace(author, "", 1)
                source = re.sub(r"(?m)^\s*\(Continued\)\s*$", "", source)
                headings = " ".join(
                    u["section_number"]
                    + " "
                    + ("" if u["section_name"].startswith("Part ") else u["section_name"])
                    for u in units
                    if u["section_number"]
                )
                self.assertEqual(
                    Counter(re.findall(r"\w+", source.casefold())),
                    Counter(re.findall(r"\w+", (" ".join(paragraphs) + " " + headings).casefold())),
                )

    def test_westmoreland_footnotes_do_not_interrupt_body_sentences(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "datasets/legal/content/westmoreland_dissent.content.json"
        )
        document = read_json(path)
        paragraphs = [
            p["text"] for s in document for u in [s, *s["subsections"]] for p in u["paragraphs"]
        ]
        body = next(p for p in paragraphs if p.startswith("Westmoreland filed"))
        self.assertIn("summary judgment to Tyree and Butler County", body)
        self.assertNotIn("1Westmoreland does concede", body)
        for start in [
            "1Westmoreland does concede",
            "2Brawner's modification",
            "3Perhaps because",
            "4This is true",
            "5I am inclined",
            "6The majority does not",
            "7Compare this",
            "8The majority does not",
        ]:
            self.assertEqual(sum(p.startswith(start) for p in paragraphs), 1)
        section_five = next(s for s in document if s["section_number"] == "V")
        self.assertIn(
            'such a right was "clearly established at the time"',
            section_five["paragraphs"][0]["text"],
        )

    def test_porter_preserves_source_words_and_separate_paragraphs(self):
        root = Path(__file__).resolve().parents[1] / "datasets/legal"
        document = read_json(root / "content/porter_opinion.content.json")
        units = [unit for section in document for unit in [section, *section["subsections"]]]
        paragraphs = [p["text"] for unit in units for p in unit["paragraphs"]]
        self.assertEqual(len(paragraphs), 38)
        self.assertTrue(any(p.startswith("The first communication occurred") for p in paragraphs))
        self.assertTrue(any(p.startswith("The second communication relates") for p in paragraphs))
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
        for corpus, paragraphs, subsections in [("opinions", 173, 7), ("dissents", 180, 14)]:
            with self.subTest(corpus=corpus):
                manifest, papers = load_manifest(root / f"{corpus}.manifest.yaml")
                self.assertEqual(manifest.max_granularity, "subsection")
                self.assertEqual(len(papers), 5)
                units = [unit for paper in papers for unit in paper.sections]
                self.assertEqual(sum(len(unit.paragraphs) for unit in units), paragraphs)
                children = [unit for unit in units if unit.kind == "subsection"]
                self.assertEqual(len(children), subsections)
                self.assertTrue(all(unit.parent_id for unit in children))
