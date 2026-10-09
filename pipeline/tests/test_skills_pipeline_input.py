from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incremental_graph.input_data import InputError
from incremental_graph.input_data import load_paper as load_paper_permissive
from incremental_graph.skills_pipeline_input import load_paper as load_paper_strict


EXTRACTED_SECTIONS_PAYLOAD = [
    {
        "section_name": "Introduction",
        "section_number": None,
        "paragraphs": [
            {"paragraph_number": 1, "text": "First paragraph."},
            {"paragraph_number": 2, "text": "Second paragraph."},
        ],
    },
    {
        "section_name": "Discussion",
        "section_number": None,
        "paragraphs": [{"paragraph_number": 1, "text": "Discussion paragraph."}],
    },
]

CANONICAL_PAYLOAD = {
    "paper_id": "paper-a",
    "title": "Paper A",
    "sections": [
        {"id": "s1", "title": "Introduction", "text": "First paragraph.\n\nSecond paragraph."},
    ],
}


class SkillsPipelineInputTest(unittest.TestCase):
    def test_accepts_extracted_sections_format_identically_to_the_permissive_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.json"
            path.write_text(json.dumps(EXTRACTED_SECTIONS_PAYLOAD), encoding="utf-8")

            strict = load_paper_strict(path, "paper-a", "Paper A")
            permissive = load_paper_permissive(path, "paper-a", "Paper A")

            self.assertEqual(strict, permissive)
            self.assertEqual([section.id for section in strict.sections], ["s1", "s2"])
            self.assertEqual(
                [paragraph.id for section in strict.sections for paragraph in section.paragraphs],
                ["s1-1", "s1-2", "s2-1"],
            )

    def test_rejects_canonical_format_loudly_instead_of_silently_normalizing_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.json"
            path.write_text(json.dumps(CANONICAL_PAYLOAD), encoding="utf-8")

            with self.assertRaises(InputError) as context:
                load_paper_strict(path, "paper-a", "Paper A")

            message = str(context.exception)
            self.assertIn("extracted-sections format", message)
            self.assertIn("dict", message)

            # The permissive loader accepts the same file without complaint -- this test
            # exists specifically to confirm the strict loader's behavior actually differs.
            permissive = load_paper_permissive(path, "paper-a", "Paper A")
            self.assertEqual(len(permissive.sections), 1)


if __name__ == "__main__":
    unittest.main()
