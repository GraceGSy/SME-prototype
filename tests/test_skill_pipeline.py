from __future__ import annotations

import copy
import json
import tempfile
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
    _match_schema,
    batch_candidates,
    combine_duplicate_match_records,
    validate_match_records,
    validate_text_completion,
)
from pipeline.prepare_content_corpus import prepare_content_corpus


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
        self.assertEqual(stages["extraction"]["max_tokens"], 32768)
        self.assertEqual(stages["questions"]["max_tokens"], 256)
        extraction_policy = harness._call_policy(stages["extraction"])
        self.assertEqual(extraction_policy.effort, "low")
        self.assertEqual(extraction_policy.thinking, "disabled")
        self.assertEqual(extraction_policy.max_input_tokens, 250000)
        self.assertNotIn("task_budget_tokens", harness.config["execution"])
        self.assertNotIn("max_continuations", harness.config["execution"])
        self.assertEqual(harness.config["session_budget"]["max_api_responses"], 100)
        self.assertNotIn("validation_attempts", stages["section_matching"])
        self.assertNotIn("validation_attempts", stages["section_and_subsection_matching"])
        self.assertEqual(
            stages["section_and_subsection_matching"]["source_batch_size"],
            10,
        )
        self.assertEqual(stages["section_matching"]["view"], SECTIONS_VIEW)
        self.assertEqual(
            stages["section_and_subsection_matching"]["view"],
            NESTED_VIEW,
        )
        self.assertIn("sherlock", harness.config["datasets"])
        self.assertIn("hci", harness.config["datasets"])
        self.assertIn("legal_opinions", harness.config["datasets"])
        self.assertIn("legal_dissents", harness.config["datasets"])
        for dataset_name in ("legal_opinions", "legal_dissents"):
            self.assertTrue(all(
                "text" in document and "pdf" not in document
                for document in harness.config["datasets"][dataset_name]["documents"]
            ))
        self.assertEqual(
            {
                name: settings["participant_prefix"]
                for name, settings in harness.config["study"]["datasets"].items()
            },
            {
                "sherlock": "SH",
                "hci": "HC",
                "legal_opinions": "LO",
                "legal_dissents": "LD",
            },
        )
        root = Path(__file__).resolve().parents[1]
        self.assertTrue(all(
            (root / harness.config["skills"][stage["skill"]]).is_dir()
            for stage in harness.config["stages"]
        ))

    def test_config_rejects_retrying_one_judgment(self) -> None:
        harness = Harness(DEFAULT_CONFIG)
        harness.config["stages"][0]["validation_attempts"] = 2

        with self.assertRaisesRegex(ValueError, "one judgment always makes one request"):
            harness._validate_config()

    def test_prepares_content_only_corpus_with_canonical_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text(json.dumps(_document()), encoding="utf-8")
            manifest = root / "manifest.yaml"
            manifest.write_text(
                "schema_version: 1\npapers:\n"
                "  - paper_id: sample\n"
                "    title: Sample\n"
                "    file: source.json\n",
                encoding="utf-8",
            )
            output = root / "content"

            self.assertEqual(prepare_content_corpus(manifest, output), 1)

            content = json.loads((output / "source.content.json").read_text(encoding="utf-8"))
            self.assertNotIn(QUESTION_FIELD, content[0])
            self.assertIn("file: source.content.json", (output / "manifest.yaml").read_text())

    def test_prepares_one_section_paragraph_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "story.content.json"
            source.write_text(json.dumps(_document()), encoding="utf-8")
            manifest = root / "manifest.yaml"
            manifest.write_text(
                "schema_version: 1\npapers:\n"
                "  - paper_id: story\n"
                "    title: Whole Story\n"
                "    file: story.content.json\n",
                encoding="utf-8",
            )
            output = root / "whole-story"

            self.assertEqual(
                prepare_content_corpus(manifest, output, whole_section=True),
                1,
            )

            content = json.loads((output / "story.content.json").read_text(encoding="utf-8"))
            self.assertEqual(len(content), 1)
            self.assertEqual(content[0]["section_name"], "Whole Story")
            self.assertEqual(content[0]["subsections"], [])
            self.assertEqual(
                [paragraph["paragraph_number"] for paragraph in content[0]["paragraphs"]],
                list(range(len(content[0]["paragraphs"]))),
            )
            prepared_manifest = (output / "manifest.yaml").read_text(encoding="utf-8")
            self.assertIn("max_granularity: paragraph", prepared_manifest)

    def test_extraction_skill_has_only_directly_bundled_domain_guides(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / "skills" / "extract-section-and-subsection-paragraphs"
        entrypoint = (skill_dir / "SKILL.md").read_text(encoding="utf-8")

        for guide in ("NARRATIVE.md", "LEGAL.md", "ACADEMIC.md"):
            self.assertIn(guide, entrypoint)
            self.assertTrue((skill_dir / guide).is_file())
        self.assertNotIn("extract-section-paragraphs", entrypoint)

    def test_candidate_batches_are_stable_and_complete(self) -> None:
        candidates = matching_candidates(_document(), NESTED_VIEW)
        self.assertEqual(batch_candidates(candidates, 1), [[candidates[0]], [candidates[1]]])

    def test_text_extraction_must_preserve_the_final_source_passage(self) -> None:
        document = _document()
        ending = "one two three four five six seven eight nine ten eleven twelve"
        document[0]["subsections"][0]["paragraphs"][0]["text"] = ending

        validate_text_completion(document, f"Front matter.\n{ending}")
        with self.assertRaisesRegex(ValueError, "final source passage"):
            validate_text_completion(document, f"Front matter.\n{ending} thirteen")

    def test_one_match_contract_allows_multiple_targets(self) -> None:
        matches = [
            {"source_id": "s0001", "target_id": "s0002", "basis": "Shared role."},
            {"source_id": "s0001", "target_id": "s0003", "basis": "Split role."},
        ]

        validate_match_records(matches, {"s0001"}, {"s0002", "s0003"})

    def test_match_schema_stays_constant_across_candidate_pools(self) -> None:
        schema = _match_schema()

        entry = schema["properties"]["matches"]["items"]
        self.assertEqual(entry["properties"]["source_id"]["type"], "string")
        self.assertEqual(entry["properties"]["target_id"]["type"], ["string", "null"])

    def test_match_validation_rejects_ids_outside_the_candidate_pool(self) -> None:
        matches = [
            {"source_id": "unknown", "target_id": "s0002", "basis": "Shared role."},
        ]

        with self.assertRaisesRegex(ValueError, "Unknown source candidate"):
            validate_match_records(matches, {"s0001"}, {"s0002"})

    def test_duplicate_match_evidence_is_combined_without_loss(self) -> None:
        matches, duplicate_count = combine_duplicate_match_records([
            {"source_id": "s0001", "target_id": "s0002", "basis": "First basis."},
            {"source_id": "s0001", "target_id": "s0002", "basis": "Second basis."},
            {"source_id": "s0001", "target_id": "s0002", "basis": "Second basis."},
        ])

        self.assertEqual(duplicate_count, 2)
        self.assertEqual(matches, [{
            "source_id": "s0001",
            "target_id": "s0002",
            "basis": "First basis.\n\nSecond basis.",
        }])

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
