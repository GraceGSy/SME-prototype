"""Break/fix regressions for external inputs, not permissive repair paths."""

import unittest

from pydantic import ValidationError

from pipeline.document import validate_document
from pipeline.incremental_graph.llm import AnthropicJudgmentProvider, JudgmentError
from pipeline.incremental_graph.models import JudgmentRequest, PaperManifest


class BoundaryTest(unittest.TestCase):
    def test_manifest_rejects_misspelled_fields_and_versions(self):
        base = {"papers": [{"paper_id": "p", "title": "P", "file": "p.json"}]}
        for invalid in (
            {"max_granularty": "paragraph"},
            {"schema_version": 999},
            {"schema_version": True},
            {"schema_version": "1"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                PaperManifest.model_validate({**base, **invalid})

    def test_paragraph_number_is_an_integer_not_a_coercible_value(self):
        for number in (False, 0.0, "0"):
            with self.subTest(number=number), self.assertRaises(ValueError):
                validate_document(
                    [
                        {
                            "section_name": "S",
                            "subsections": [],
                            "paragraphs": [{"paragraph_number": number, "text": "Evidence."}],
                        }
                    ]
                )

    def test_single_match_requires_exact_fields_and_explicit_abstention(self):
        request = JudgmentRequest(
            key="test",
            paper_index=1,
            stage_id="match",
            output_kind="match",
            prompt_ref="test",
            context_ref="test",
            context={},
            allowed_match_ids=["p"],
        )
        for invalid in (
            {},
            {"target_id": None},
            {"target_id": None, "basis": " "},
            {"target_id": None, "basis": "No match.", "extra": True},
            {"target_id": [], "basis": "No match."},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(JudgmentError):
                AnthropicJudgmentProvider._validate(request, invalid)
        AnthropicJudgmentProvider._validate(request, {"target_id": None, "basis": "No match."})


if __name__ == "__main__":
    unittest.main()
