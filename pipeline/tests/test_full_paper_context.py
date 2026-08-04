from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

from relabel_full_paper import format_complete_paper, relabel_paper
from section_schema import Section, SectionedPaper


class FullPaperContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.paper = SectionedPaper(
            paper_id="paper-a",
            title="A Study",
            sections=[
                Section(id="s1", title="Introduction", tag="Why is this needed?"),
                Section(id="s2", title="Results", tag="What did the study find?"),
            ],
            paragraphs=[
                Section(
                    id="pa1",
                    tag="What is the problem?",
                    text="The first complete paragraph describes the problem.",
                    parent_section_id="s1",
                    next_relation="evidence",
                ),
                Section(
                    id="pa2",
                    tag="What was found?",
                    text="The second complete paragraph reports the result.",
                    parent_section_id="s2",
                    prev_relation="result",
                ),
            ],
        )

    def test_complete_paper_format_contains_every_fixed_paragraph_once(self) -> None:
        formatted = format_complete_paper(self.paper)
        for paragraph in self.paper.paragraphs:
            self.assertEqual(formatted.count(f'<paragraph id="{paragraph.id}">'), 1)
            self.assertIn(paragraph.text, formatted)

    def test_relabeling_changes_only_questions_and_preserves_fixed_units(self) -> None:
        requests = []

        def create(**kwargs):
            requests.append(kwargs)
            block = SimpleNamespace(
                type="tool_use",
                name="record_full_paper_paragraph_questions",
                input={
                    "paragraphs": [
                        {
                            "paragraph_id": "pa1",
                            "question": "Why does this problem matter?",
                        },
                        {
                            "paragraph_id": "pa2",
                            "question": "What evidence resolves the problem?",
                        },
                    ]
                },
            )
            usage = SimpleNamespace(
                cache_creation_input_tokens=0, cache_read_input_tokens=0
            )
            return SimpleNamespace(content=[block], usage=usage)

        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("relabel_full_paper.CACHE_DIR", Path(directory)),
        ):
            complete_paper_text = "Front matter plus the complete source paper."
            updated, provenance = relabel_paper(
                self.paper,
                complete_paper_text=complete_paper_text,
                client=client,
            )

        self.assertEqual(
            [paragraph.id for paragraph in updated.paragraphs], ["pa1", "pa2"]
        )
        self.assertEqual(
            [paragraph.text for paragraph in updated.paragraphs],
            [paragraph.text for paragraph in self.paper.paragraphs],
        )
        self.assertEqual(
            [paragraph.parent_section_id for paragraph in updated.paragraphs],
            [paragraph.parent_section_id for paragraph in self.paper.paragraphs],
        )
        self.assertEqual(updated.paragraphs[0].next_relation, "evidence")
        self.assertEqual(updated.paragraphs[1].prev_relation, "result")
        self.assertEqual(provenance["input_paragraph_ids"], ["pa1", "pa2"])
        prompt = requests[0]["messages"][0]["content"]
        self.assertIn(complete_paper_text, prompt)
        self.assertIn(self.paper.paragraphs[0].text, prompt)
        self.assertIn(self.paper.paragraphs[1].text, prompt)


if __name__ == "__main__":
    unittest.main()
