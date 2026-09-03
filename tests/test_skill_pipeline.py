from __future__ import annotations

import copy
import unittest
from pathlib import Path

from pipeline.document import (
    NESTED_VIEW,
    QUESTION_FIELD,
    SECTIONS_VIEW,
    iter_structural_units,
    matching_candidates,
    strip_questions,
    validate_document,
)
from pipeline.skill_pipeline.runner import (
    DEFAULT_CONFIG,
    Harness,
    batch_candidates,
    validate_match_records,
)


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


class SkillPipelineTest(unittest.TestCase):
    def test_config_keeps_matching_implementations_swappable(self) -> None:
        harness = Harness(DEFAULT_CONFIG)

        stages = {stage["id"]: stage for stage in harness.config["stages"]}
        self.assertEqual(stages["section_matching"]["view"], SECTIONS_VIEW)
        self.assertEqual(
            stages["section_and_subsection_matching"]["view"],
            NESTED_VIEW,
        )
        self.assertIn("sherlock", harness.config["datasets"])
        self.assertIn("hci", harness.config["datasets"])
        root = Path(__file__).resolve().parents[1]
        self.assertTrue(all(
            (root / harness.config["skills"][stage["skill"]]).is_dir()
            for stage in harness.config["stages"]
        ))

    def test_candidate_batches_are_stable_and_complete(self) -> None:
        candidates = matching_candidates(_document(), NESTED_VIEW)
        self.assertEqual(batch_candidates(candidates, 1), [[candidates[0]], [candidates[1]]])

    def test_one_match_contract_allows_multiple_targets(self) -> None:
        matches = [
            {"source_id": "s0001", "target_id": "s0002", "basis": "Shared role."},
            {"source_id": "s0001", "target_id": "s0003", "basis": "Split role."},
        ]

        validate_match_records(matches, {"s0001"}, {"s0002", "s0003"})

    def test_match_contract_rejects_null_plus_target(self) -> None:
        matches = [
            {"source_id": "s0001", "target_id": None, "basis": "No match."},
            {"source_id": "s0001", "target_id": "s0002", "basis": "A match."},
        ]

        with self.assertRaisesRegex(ValueError, "both matched and null"):
            validate_match_records(matches, {"s0001"}, {"s0002"})

    def test_completed_output_has_one_envelope_with_both_directions(self) -> None:
        stage = {"id": "section_matching", "view": SECTIONS_VIEW}
        documents = {"paper_a": _document(), "paper_b": _document()}
        payload = {
            "schema_version": 1,
            "dataset_id": "sample",
            "stage_id": "section_matching",
            "candidate_view": SECTIONS_VIEW,
            "directions": [
                {
                    "source_document_id": source,
                    "target_document_id": target,
                    "matches": [{
                        "source_id": "s0001",
                        "target_id": "s0001",
                        "basis": "Same structural role.",
                    }],
                }
                for source, target in (("paper_a", "paper_b"), ("paper_b", "paper_a"))
            ],
        }

        Harness._validate_match_output(
            payload,
            "sample",
            stage,
            documents,
            require_complete=True,
        )


if __name__ == "__main__":
    unittest.main()
