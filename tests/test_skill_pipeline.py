from __future__ import annotations

import unittest

from pipeline.skill_pipeline.runner import (
    DEFAULT_CONFIG,
    Harness,
    NESTED_QUESTION,
    batch_candidates,
    flatten_document,
    matching_candidates,
    strip_questions,
    validate_match_candidates,
)


def _document() -> list[dict]:
    return [
        {
            "section_name": "Results",
            "section_number": "4",
            NESTED_QUESTION: "What did the study find?",
            "paragraphs": [{"paragraph_number": 0, "text": "Lead-in."}],
            "subsections": [
                {
                    "section_name": "Qualitative Findings",
                    "section_number": "4.1",
                    NESTED_QUESTION: "What themes emerged?",
                    "paragraphs": [{"paragraph_number": 0, "text": "Theme evidence."}],
                }
            ],
        }
    ]


class SkillPipelineTest(unittest.TestCase):
    def test_config_keeps_matching_implementations_swappable(self) -> None:
        harness = Harness(DEFAULT_CONFIG)

        stages = {stage["id"]: stage for stage in harness.config["stages"]}
        self.assertEqual(stages["section_matching"]["view"], "sections")
        self.assertEqual(
            stages["section_and_subsection_matching"]["view"],
            "sections_and_subsections",
        )
        self.assertIn("sherlock", harness.config["datasets"])
        self.assertIn("hci", harness.config["datasets"])

    def test_nested_candidates_preserve_whole_and_subsection_evidence(self) -> None:
        candidates = matching_candidates(_document(), "sections_and_subsections")

        self.assertEqual(len(candidates), 2)
        self.assertIsNone(candidates[0]["subsection_name"])
        self.assertEqual(
            [paragraph["text"] for paragraph in candidates[0]["paragraphs"]],
            ["Lead-in.", "Theme evidence."],
        )
        self.assertEqual(candidates[1]["subsection_name"], "Qualitative Findings")
        self.assertEqual(candidates[1]["paragraphs"][0]["text"], "Theme evidence.")

    def test_flatten_and_strip_questions_do_not_change_content(self) -> None:
        document = _document()
        flat = flatten_document(document, with_questions=True)

        self.assertEqual(flat[0]["question_this_section_answers"], "What did the study find?")
        self.assertNotIn(NESTED_QUESTION, strip_questions(document)[0])
        self.assertEqual(len(flat[0]["paragraphs"]), 2)

    def test_candidate_batches_are_stable_and_complete(self) -> None:
        candidates = matching_candidates(_document(), "sections_and_subsections")
        self.assertEqual(batch_candidates(candidates, 1), [[candidates[0]], [candidates[1]]])

    def test_validation_allows_multiple_targets_but_requires_source_coverage(self) -> None:
        source = {("Results", "4")}
        target = {("Findings", "5"), ("Discussion", "6")}
        matches = [
            {
                "paper1_section_name": "Results",
                "paper1_section_number": "4",
                "paper2_section_name": "Findings",
                "paper2_section_number": "5",
                "basis": "Both report findings.",
                "question_the_sections_both_answer": "What was found?",
            },
            {
                "paper1_section_name": "Results",
                "paper1_section_number": "4",
                "paper2_section_name": "Discussion",
                "paper2_section_number": "6",
                "basis": "The source also interprets findings.",
                "question_the_sections_both_answer": "What do the findings mean?",
            },
        ]

        validate_match_candidates(matches, source, target, "sections")

if __name__ == "__main__":
    unittest.main()
