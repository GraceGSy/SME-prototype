"""Canonical source contract, evidence projections, and positional identity."""

import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from pipeline.files import write_json
from pipeline.incremental_graph.input_data import load_paper

from pipeline.document import (QUESTION_FIELD,
    iter_structural_units, strip_questions, validate_document)


def _document() -> list[dict]:
    return [
        {
            "section_name": "Results",
            "section_number": "4",
            QUESTION_FIELD: "What did the study find?",
            "paragraphs": [{"paragraph_number": 0, "text": "Lead-in."}],
            "subsections": [
                {
                    "section_name": "Qualitative Findings",
                    "section_number": "4.1",
                    QUESTION_FIELD: "What themes emerged?",
                    "paragraphs": [{"paragraph_number": 0, "text": "Theme evidence."}],
                }
            ],
        }
    ]


class CanonicalDocumentTest(unittest.TestCase):
    def test_graph_loading_preserves_source_whitespace(self):
        document = _document()
        text = "  Evidence\n    with original spacing.  "
        document[0]["paragraphs"][0]["text"] = text
        with TemporaryDirectory() as directory:
            path = Path(directory) / "document.json"
            write_json(path, document)
            for granularity in ("section", "subsection"):
                paper = load_paper(path, "paper", "Paper", granularity)
                self.assertEqual(paper.sections[0].paragraphs[0].text, text)

    def test_structural_evidence_retains_descendants_and_exact_ownership(self):
        units = list(iter_structural_units(_document()))
        self.assertEqual([unit.unit_id for unit in units], ["s0001", "s0001.ss0001"])
        self.assertEqual([p["text"] for p in units[0].evidence], ["Lead-in.", "Theme evidence."])
        self.assertEqual([p["text"] for p in units[0].own_paragraphs], ["Lead-in."])
        self.assertEqual(units[1].parent_unit_id, "s0001")

    def test_ids_depend_on_position_not_question_or_label(self) -> None:
        changed = copy.deepcopy(_document())
        changed[0]["section_name"] = "Renamed"
        changed[0][QUESTION_FIELD] = "A different generated question?"

        original_ids = [unit.unit_id for unit in iter_structural_units(_document())]
        changed_ids = [unit.unit_id for unit in iter_structural_units(changed)]

        self.assertEqual(original_ids, changed_ids)

    def test_strip_questions_preserves_the_canonical_content(self) -> None:
        content = strip_questions(_document())

        validate_document(content)
        self.assertNotIn(QUESTION_FIELD, content[0])
        self.assertNotIn(QUESTION_FIELD, content[0]["subsections"][0])

    def test_strict_validation_rejects_alternate_fields(self) -> None:
        document = _document()
        document[0]["question_this_section_answers"] = "Alternate field"

        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            validate_document(document)
