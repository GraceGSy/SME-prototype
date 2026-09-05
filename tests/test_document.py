"""Canonical source contract, evidence projections, and positional identity."""

import copy
import unittest

from pipeline.document import (NESTED_VIEW, QUESTION_FIELD, SECTIONS_VIEW,
    iter_structural_units, matching_candidates, strip_questions, validate_document)


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
    def test_one_candidate_contract_supports_both_views(self) -> None:
        sections = matching_candidates(_document(), SECTIONS_VIEW)
        nested = matching_candidates(_document(), NESTED_VIEW)

        self.assertEqual(len(sections), 1)
        self.assertEqual(len(nested), 2)
        self.assertEqual(sections[0], nested[0])
        self.assertEqual(nested[0]["unit_id"], "s0001")
        self.assertEqual(nested[0]["unit_type"], "section")
        self.assertEqual(
            [paragraph["text"] for paragraph in nested[0]["paragraphs"]],
            ["Lead-in.", "Theme evidence."],
        )
        self.assertEqual(nested[1]["unit_id"], "s0001.ss0001")
        self.assertEqual(nested[1]["parent_unit_id"], "s0001")
        self.assertEqual(nested[1]["name"], "Qualitative Findings")

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
