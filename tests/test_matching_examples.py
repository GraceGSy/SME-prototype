"""Few-shot instructions are shared, cache-keyed, and never live candidates."""

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import test_judgment_cache
from jsonschema import Draft202012Validator
from test_incremental_graph import CONFIG_PATH

from pipeline.incremental_graph.configuration import (
    ConfigurationError,
    PromptRepository,
    load_pipeline_config,
)
from pipeline.incremental_graph.judgments import CachedJudgments


class MatchingExamplesTest(unittest.TestCase):
    def setUp(self):
        self.config = load_pipeline_config(CONFIG_PATH)
        self.repository = PromptRepository(self.config.prompt_root, self.config.context_root)
        self.example_path = self.config.prompt_root / "shared/role-matching-examples.md"
        self.context = {"scope": {"level": "section"}, "focus": {}, "candidates": []}

    def test_every_matching_direction_includes_examples_once(self):
        examples = self.example_path.read_text(encoding="utf-8").strip()
        for stage in self.config.stages:
            for direction, reference in stage.prompts.items():
                with self.subTest(stage=stage.id, direction=direction):
                    rendered = self.repository.render(
                        reference, stage.contexts[direction], self.context
                    )
                    self.assertEqual(rendered.system.count(examples), 1)
                    self.assertNotIn("{{role_matching_examples}}", rendered.system)
                    self.assertNotIn(examples, rendered.user)
                    self.assertNotIn(examples, rendered.cacheable_context)
                    self.assertIn("Each paper's accepted contribution", rendered.system)

    def test_question_generation_does_not_receive_matching_examples(self):
        for stage in self.config.stages:
            if stage.prompt:
                spec = self.repository._load_context(stage.context)
                rendered = self.repository.render(
                    stage.prompt, stage.context, {k: None for k in spec.include}
                )
                self.assertNotIn("Constructed matching examples", rendered.system)
                if stage.context == "group-question":
                    self.assertIn("Each paper's accepted contribution", rendered.system)
                    self.assertEqual(
                        rendered.system.count("Constructed group-question examples"), 1
                    )

    def test_live_sanity_cases_are_held_out_of_the_prompt(self):
        cases = json.loads(
            (Path(__file__).parent / "fixtures/role_matching_holdout.json").read_text()
        )
        examples = self.example_path.read_text(encoding="utf-8")
        self.assertEqual(len(cases), 4)
        self.assertEqual(sum(case["expected_match"] for case in cases), 2)
        for case in cases:
            for side in ("left", "right"):
                self.assertNotIn(case[side], examples)

    def test_example_outputs_balance_matches_and_abstentions(self):
        examples = self.example_path.read_text(encoding="utf-8")
        outputs = [
            json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", examples, re.S)
        ]
        self.assertEqual(len(outputs), 6)
        schema = self.repository.render(
            "section-to-group-match/v1", "matching", self.context
        ).schema
        for output in outputs:
            Draft202012Validator(schema).validate(output)
            for quotes in output["evidence"].values():
                for quote in quotes:
                    self.assertNotIn(
                        quote.casefold(),
                        output["basis"].casefold(),
                        "Examples must not teach the model to repeat evidence quotes in basis",
                    )
        self.assertEqual(sum(output["target_id"] is None for output in outputs), 3)

    def test_example_changes_invalidate_prompt_hash_and_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "prompts"
            shutil.copytree(self.config.prompt_root, root)
            repository = PromptRepository(root, self.config.context_root)
            first = repository.render("section-to-group-match/v1", "matching", self.context)
            path = root / "shared/role-matching-examples.md"
            path.write_text(
                path.read_text(encoding="utf-8") + "\nChanged example evidence.\n", encoding="utf-8"
            )
            second = repository.render("section-to-group-match/v1", "matching", self.context)
            self.assertNotEqual(first.prompt_hash, second.prompt_hash)
            self.assertEqual(first.context_hash, second.context_hash)
            self.assertEqual(first.schema_hash, second.schema_hash)
            path.unlink()
            with self.assertRaises(ConfigurationError):
                repository.render("section-to-group-match/v1", "matching", self.context)

    def test_demonstration_handles_are_not_valid_live_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = CachedJudgments(
                self.repository,
                self.config.model,
                Path(directory),
                self.config.skill_root,
            )
            request = test_judgment_cache.JudgmentCacheTest().request()
            rendered = provider.render_request(request)
            self.assertIn("Constructed matching examples", rendered.system)
            validator = Draft202012Validator(rendered.schema)
            self.assertTrue(
                validator.is_valid(
                    {
                        "target_id": "group",
                        "basis": "Supported role",
                        "evidence": {"focus": ["focus"], "target": ["Repeated corpus"]},
                    }
                )
            )
            for handle in ("demo-analysis", "demo-mechanism"):
                self.assertFalse(
                    validator.is_valid({"target_id": handle, "basis": "Copied example"})
                )
