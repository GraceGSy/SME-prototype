"""Canonical source contract, evidence projections, and positional identity."""

import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pipeline.document import (
    ROLE_FIELD,
    iter_structural_units,
    relabel_extraction,
    strip_annotations,
    validate_document,
)
from pipeline.files import write_json
from pipeline.incremental_graph.input_data import load_paper


def _document() -> list[dict]:
    return [
        {
            "section_name": "Results",
            "section_number": "4",
            ROLE_FIELD: "Reports the evaluation findings.",
            "paragraphs": [{"paragraph_number": 0, "text": "Lead-in."}],
            "subsections": [
                {
                    "section_name": "Qualitative Findings",
                    "section_number": "4.1",
                    ROLE_FIELD: "Identifies recurring themes in the findings.",
                    "paragraphs": [{"paragraph_number": 0, "text": "Theme evidence."}],
                }
            ],
        }
    ]


class CanonicalDocumentTest(unittest.TestCase):
    def test_archived_questions_remain_readable_but_never_supply_roles(self):
        doc = strip_annotations(_document())
        doc[0]["question_this_text_answers"] = "How was the evaluation conducted?"
        doc[0]["paragraphs"][0]["question_this_text_answers"] = "Who participated?"
        authored = strip_annotations(doc)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            write_json(path, doc)
            saved = path.read_bytes()
            section = load_paper(path, "paper", "Paper").sections[0]
            self.assertEqual(
                (section.role_statement, section.paragraphs[0].role_statement), ("", "")
            )
            self.assertEqual(path.read_bytes(), saved)
        doc[0][ROLE_FIELD] = "Describes the evaluation procedure."
        self.assertEqual(strip_annotations(doc), authored)
        validate_document(doc)
        for invalid in ("Who participated?", "First role.\nSecond role.", " "):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_document([{**doc[0], ROLE_FIELD: invalid}])

    def test_relabel_extraction_preserves_hierarchy_and_authored_numbers(self):
        original = _document()
        original[0]["section_name"] = "4 Results"
        original[0]["paragraphs"][0].update(paragraph_number=8, text="See Section 4.1 and [8].")
        original.insert(
            0,
            {
                "section_name": "Abstract",
                "section_number": None,
                "paragraphs": [],
                "subsections": [],
            },
        )
        result = relabel_extraction(original)
        self.assertEqual(
            [u.source["section_number"] for u in iter_structural_units(result)], ["1", "2", "2.1"]
        )
        self.assertEqual(result[1]["section_name"], "Results")
        self.assertEqual(
            result[1]["paragraphs"], [{"paragraph_number": 0, "text": "See Section 4.1 and [8]."}]
        )
        self.assertEqual(result, relabel_extraction(result))
        self.assertEqual(original[1]["paragraphs"][0]["paragraph_number"], 8)

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
        changed[0][ROLE_FIELD] = "Contrasts two approaches."

        original_ids = [unit.unit_id for unit in iter_structural_units(_document())]
        changed_ids = [unit.unit_id for unit in iter_structural_units(changed)]

        self.assertEqual(original_ids, changed_ids)

    def test_strip_annotations_preserves_the_canonical_content(self) -> None:
        content = strip_annotations(_document())

        validate_document(content)
        self.assertNotIn(ROLE_FIELD, content[0])
        self.assertNotIn(ROLE_FIELD, content[0]["subsections"][0])

    def test_strict_validation_rejects_alternate_fields(self) -> None:
        document = _document()
        document[0]["question_this_section_answers"] = "Alternate field"

        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            validate_document(document)
