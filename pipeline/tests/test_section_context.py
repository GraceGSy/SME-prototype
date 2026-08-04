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

from relabel_section_context import relabel_paper
from section_schema import Section, SectionedPaper


class FixedSectionContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.paper = SectionedPaper(
            paper_id="paper-a",
            title="A Study",
            sections=[
                Section(
                    id="s1",
                    title="Introduction",
                    tag="Why is this needed?",
                    text="Complete introduction text seen only for section one.",
                ),
                Section(
                    id="s2",
                    title="Results",
                    tag="What did the study find?",
                    text="Complete results text seen only for section two.",
                ),
            ],
            paragraphs=[
                Section(
                    id="pa1",
                    tag="What is the problem?",
                    text="The fixed introduction paragraph.",
                    parent_section_id="s1",
                    next_relation="evidence",
                ),
                Section(
                    id="pa2",
                    tag="What was found?",
                    text="The fixed results paragraph.",
                    parent_section_id="s2",
                    prev_relation="result",
                ),
            ],
        )

    def test_relabeling_is_one_section_per_call_and_preserves_fixed_units(self) -> None:
        requests = []

        def create(**kwargs):
            requests.append(kwargs)
            paragraph_ids = kwargs["tools"][0]["input_schema"]["properties"][
                "paragraphs"
            ]["items"]["properties"]["paragraph_id"]["enum"]
            block = SimpleNamespace(
                type="tool_use",
                name="record_section_paragraph_questions",
                input={
                    "paragraphs": [
                        {
                            "paragraph_id": paragraph_id,
                            "question": f"What role does {paragraph_id} play?",
                        }
                        for paragraph_id in paragraph_ids
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
            patch("relabel_section_context.CACHE_DIR", Path(directory)),
        ):
            updated, provenance = relabel_paper(self.paper, client=client)

        self.assertEqual(len(requests), 2)
        first_prompt = requests[0]["messages"][0]["content"]
        second_prompt = requests[1]["messages"][0]["content"]
        self.assertIn(self.paper.sections[0].text, first_prompt)
        self.assertNotIn(self.paper.sections[1].text, first_prompt)
        self.assertIn(self.paper.sections[1].text, second_prompt)
        self.assertNotIn(self.paper.sections[0].text, second_prompt)
        self.assertEqual(
            [paragraph.id for paragraph in updated.paragraphs], ["pa1", "pa2"]
        )
        self.assertEqual(
            [paragraph.text for paragraph in updated.paragraphs],
            [paragraph.text for paragraph in self.paper.paragraphs],
        )
        self.assertEqual(updated.paragraphs[0].next_relation, "evidence")
        self.assertEqual(updated.paragraphs[1].prev_relation, "result")
        self.assertEqual(
            provenance["input_paragraph_ids"], ["pa1", "pa2"]
        )
        self.assertEqual(
            [section["input_paragraph_ids"] for section in provenance["sections"]],
            [["pa1"], ["pa2"]],
        )


if __name__ == "__main__":
    unittest.main()
