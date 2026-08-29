from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from pipeline.questions.annotate import (
    FIELD,
    annotate_document,
    annotate_file,
    completeness_violations,
    paragraph_is_empty,
    section_is_empty,
    serialize_paragraph,
    serialize_section,
    serialize_subsection,
    subsection_is_empty,
)


def sample_document() -> list[dict[str, Any]]:
    return [
        {
            "section_name": "Introduction",
            "section_number": "99",
            "paragraphs": [
                {"paragraph_number": 42, "text": "Lead-in paragraph about the problem."},
            ],
            "subsections": [
                {
                    "section_name": "Motivation",
                    "section_number": "99.99",
                    "paragraphs": [
                        {"paragraph_number": 0, "text": "Why this work is needed."},
                        {"paragraph_number": 1, "text": "Who it is for."},
                    ],
                },
            ],
        },
        {
            "section_name": "References",
            "section_number": None,
            "paragraphs": [],
            "subsections": [],
        },
    ]


class RecordingAsk:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, serialized: str) -> str:
        self.calls.append(serialized)
        return f"Question for call {len(self.calls)}?"


class AnnotateTextQuestionsSerializationTest(unittest.TestCase):
    def test_section_serialization_is_paper_order_titles_and_paragraphs(self) -> None:
        section = sample_document()[0]
        text = serialize_section(section)
        self.assertEqual(
            text,
            "\n\n".join([
                "Introduction",
                "Lead-in paragraph about the problem.",
                "Motivation",
                "Why this work is needed.",
                "Who it is for.",
            ]),
        )

    def test_subsection_serialization_prepends_parent_section_title(self) -> None:
        section = sample_document()[0]
        text = serialize_subsection(section, section["subsections"][0])
        self.assertEqual(
            text,
            "Section: Introduction\n"
            "Subsection: Motivation\n\n"
            "Why this work is needed.\n\n"
            "Who it is for.",
        )

    def test_paragraph_serialization_prepends_section_and_subsection_titles(self) -> None:
        section = sample_document()[0]
        lead_in = serialize_paragraph(section, section["paragraphs"][0])
        nested = serialize_paragraph(
            section,
            section["subsections"][0]["paragraphs"][0],
            section["subsections"][0],
        )
        self.assertEqual(
            lead_in,
            "Section: Introduction\n\nLead-in paragraph about the problem.",
        )
        self.assertNotIn("Subsection:", lead_in)
        self.assertEqual(
            nested,
            "Section: Introduction\n"
            "Subsection: Motivation\n\n"
            "Why this work is needed.",
        )

    def test_serialization_omits_section_and_paragraph_numbers(self) -> None:
        section = sample_document()[0]
        payloads = [
            serialize_section(section),
            serialize_subsection(section, section["subsections"][0]),
            serialize_paragraph(section, section["paragraphs"][0]),
            serialize_paragraph(
                section,
                section["subsections"][0]["paragraphs"][0],
                section["subsections"][0],
            ),
        ]
        for text in payloads:
            self.assertNotIn("section_number", text)
            self.assertNotIn("paragraph_number", text)
            self.assertNotIn("99.99", text)
            self.assertNotIn("42", text)
            # Bare "99" is the top-level section_number; it must not appear as a
            # heading/number token. The digit pair can still theoretically show
            # up inside prose, but this fixture's prose has none.
            self.assertNotIn("99", text)


class AnnotateTextQuestionsEmptyAndResumeTest(unittest.TestCase):
    def test_empty_references_section_is_null_without_calling_the_client(self) -> None:
        sections = [sample_document()[1]]
        ask = RecordingAsk()

        stats = annotate_document(sections, ask_fn=ask)

        self.assertEqual(ask.calls, [])
        self.assertIsNone(sections[0][FIELD])
        self.assertEqual(stats["nulled"], 1)
        self.assertEqual(stats["called"], 0)
        self.assertTrue(section_is_empty(sections[0]))
        self.assertEqual(completeness_violations(sections), [])

    def test_whitespace_only_paragraph_is_empty(self) -> None:
        paragraph = {"paragraph_number": 0, "text": "   \n\t"}
        self.assertTrue(paragraph_is_empty(paragraph))
        subsection = {"section_name": "Empty", "paragraphs": [paragraph]}
        self.assertTrue(subsection_is_empty(subsection))
        section = {
            "section_name": "Empty",
            "paragraphs": [paragraph],
            "subsections": [],
        }
        self.assertTrue(section_is_empty(section))

    def test_resume_skips_objects_that_already_have_the_field(self) -> None:
        sections = sample_document()
        sections[0][FIELD] = "What job does the introduction do?"
        sections[0]["subsections"][0][FIELD] = "What job does the motivation subsection do?"
        sections[0]["paragraphs"][0][FIELD] = "What job does the lead-in paragraph do?"
        # Leave the two nested paragraphs and References unannotated.
        ask = RecordingAsk()
        saves: list[int] = []

        stats = annotate_document(sections, ask_fn=ask, save_fn=lambda: saves.append(1))

        self.assertEqual(stats["skipped"], 3)
        self.assertEqual(stats["nulled"], 1)  # References
        self.assertEqual(stats["called"], 2)  # two nested Motivation paragraphs
        self.assertEqual(len(ask.calls), 2)
        self.assertTrue(all("Why this work is needed." in c or "Who it is for." in c for c in ask.calls))
        self.assertEqual(sections[0][FIELD], "What job does the introduction do?")
        self.assertEqual(
            sections[0]["subsections"][0][FIELD],
            "What job does the motivation subsection do?",
        )
        self.assertEqual(completeness_violations(sections), [])
        self.assertEqual(len(saves), 3)  # two paragraph writes + one References null

    def test_force_recomputes_even_when_the_field_is_already_present(self) -> None:
        sections = sample_document()
        sections[0][FIELD] = "stale section question"
        ask = RecordingAsk()

        stats = annotate_document(sections, ask_fn=ask, force=True)

        self.assertEqual(stats["skipped"], 0)
        self.assertNotEqual(sections[0][FIELD], "stale section question")
        self.assertTrue(sections[0][FIELD].startswith("Question for call"))

    def test_annotate_file_resume_does_not_recall_filled_units(self) -> None:
        payload = sample_document()
        payload[0][FIELD] = "already done"
        ask = RecordingAsk()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            stats = annotate_file(path, ask_fn=ask)
            written = json.loads(path.read_text(encoding="utf-8"))

        self.assertGreater(stats["skipped"], 0)
        self.assertEqual(written[0][FIELD], "already done")
        self.assertIsNone(written[1][FIELD])
        # The filled section unit was not re-sent (section payload starts with the bare title).
        self.assertFalse(any(c.startswith("Introduction\n\nLead-in") for c in ask.calls))


if __name__ == "__main__":
    unittest.main()
