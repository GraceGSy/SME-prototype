import hashlib
import json
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from helpers.prepare_sherlock_five import extract


class SherlockPreparationTest(unittest.TestCase):
    def source(self, body):
        return f'<html xmlns="http://www.w3.org/1999/xhtml"><body><article>{body}</article></body></html>'.encode()

    def test_preserves_inline_text_and_letter_signatures_in_order(self):
        result = extract(
            self.source(
                "<h2>Title</h2><p>Mr. <em>Holmes</em> spoke.</p><hr/><blockquote><p>Dear sir,</p><footer><p>Adler</p></footer></blockquote>"
            ),
            "Title",
        )
        self.assertEqual(
            [p["text"] for p in result[0]["paragraphs"]],
            ["Mr. Holmes spoke.", "Dear sir,", "Adler"],
        )
        self.assertEqual([p["paragraph_number"] for p in result[0]["paragraphs"]], [0, 1, 2])

    def test_rejects_unhandled_blocks_and_stray_text(self):
        for body in ["<ul><li>Lost clue</li></ul>", "Lost clue<p>Known text</p>"]:
            with self.assertRaises(ValueError):
                extract(self.source(body), "Title")

    def test_all_five_inputs_preserve_every_source_paragraph_without_questions(self):
        root = Path(__file__).resolve().parents[1] / "datasets/sherlock/famous-five"
        sources = json.loads((root / "provenance.json").read_text(encoding="utf-8"))["stories"]
        self.assertEqual(len(sources), 5)
        total = 0
        for source in sources:
            raw_path = root / "raw" / (source["paper_id"] + ".xhtml")
            content_path = root / (source["paper_id"] + ".content.json")
            self.assertEqual(
                hashlib.sha256(raw_path.read_bytes()).hexdigest(), source["source_sha256"]
            )
            self.assertEqual(
                hashlib.sha256(content_path.read_bytes()).hexdigest(), source["content_sha256"]
            )
            raw = ET.parse(raw_path)
            expected = [
                "".join(p.itertext()).strip()
                for p in raw.findall(
                    ".//{http://www.w3.org/1999/xhtml}body//{http://www.w3.org/1999/xhtml}p"
                )
            ]
            document = json.loads(content_path.read_text(encoding="utf-8"))
            self.assertEqual(len(document), 1)
            self.assertEqual(
                set(document[0]), {"section_name", "section_number", "paragraphs", "subsections"}
            )
            self.assertEqual(document[0]["subsections"], [])
            self.assertEqual([p["text"] for p in document[0]["paragraphs"]], expected)
            self.assertTrue(
                all(set(p) == {"paragraph_number", "text"} for p in document[0]["paragraphs"])
            )
            total += len(expected)
        self.assertEqual(total, 1161)
