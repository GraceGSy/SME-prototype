"""Only generation-affecting inputs invalidate a cached judgment."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_incremental_graph import CONFIG_PATH

from pipeline.incremental_graph.configuration import PromptRepository, load_pipeline_config
from pipeline.incremental_graph.judgments import CachedJudgments, JudgmentError
from pipeline.incremental_graph.models import JudgmentRequest
from pipeline.providers.contracts import SkillRef


class JudgmentCacheTest(unittest.TestCase):
    def test_rejected_id_keeps_raw_response_without_becoming_a_cache_hit(self):
        config = load_pipeline_config(CONFIG_PATH)
        raw = {"id": "rejected-response", "usage": {"output_tokens": 12}}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("pipeline.incremental_graph.judgments.create_skill_client") as client,
        ):
            client.return_value.register.return_value = SkillRef(
                "match-role", "skill", "v1", "hash"
            )
            client.return_value.run_json.return_value = SimpleNamespace(
                value={
                    "target_id": "paper-group",
                    "basis": "Original explanation",
                    "evidence": {"focus": [], "target": []},
                },
                raw_response=raw,
            )
            provider = CachedJudgments(
                PromptRepository(config.prompt_root, config.context_root),
                config.model,
                Path(directory),
                config.skill_root,
            )
            for _ in range(2):
                with self.assertRaises(JudgmentError):
                    provider.judge(self.request())
            self.assertEqual(client.return_value.run_json.call_count, 2)
            self.assertEqual(list(Path(directory).glob("*.json")), [])
            records = list((Path(directory) / "rejected").glob("*.json"))
            self.assertEqual(len(records), 2)
            record = json.loads(records[0].read_text())
            self.assertEqual(record["result"]["raw_response"], raw)
            self.assertEqual(record["result"]["normalized"]["target_id"], "paper-group")
            self.assertEqual(record["result"]["normalized"]["basis"], "Original explanation")
            self.assertEqual(record["request"]["allowed_match_ids"], ["group"])

    def test_every_matching_direction_preserves_all_evidence_in_split_blocks(self):
        config = load_pipeline_config(CONFIG_PATH)
        prompts = PromptRepository(config.prompt_root, config.context_root)
        context = self.request().context
        for stage in config.stages:
            for direction, prompt_ref in stage.prompts.items():
                with self.subTest(stage=stage.id, direction=direction):
                    rendered = prompts.render(prompt_ref, stage.contexts[direction], context)
                    prefix = json.loads(rendered.cacheable_context.split("\n\n", 1)[1])
                    dynamic = json.loads(rendered.user[rendered.user.index("{\n") :])
                    self.assertEqual(set(prefix), {"scope", "candidates"})
                    self.assertEqual(set(dynamic), {"focus"})
                    self.assertEqual({**prefix, **dynamic}, context)

    def test_question_prompts_do_not_cache_unique_evidence(self):
        config = load_pipeline_config(CONFIG_PATH)
        rendered = PromptRepository(config.prompt_root, config.context_root).render(
            "section-question/v1",
            "section-question",
            {"paper": {"title": "Title"}, "section": {"full_text": "Unique evidence"}},
        )
        self.assertIsNone(rendered.cacheable_context)
        self.assertIn("Unique evidence", rendered.user)

    def request(self):
        return JudgmentRequest(
            key="p2:paragraph_matching:new_to_group:p",
            paper_index=2,
            stage_id="paragraph_matching",
            output_kind="match",
            prompt_ref="paragraph-to-group-match/v1",
            context_ref="matching",
            skill_ref="match-role",
            allowed_match_ids=["group"],
            context={
                "scope": {"level": "paragraph"},
                "focus": {
                    "paper_key": "paper-2",
                    "paragraph_under_consideration": {"full_text": "First focus"},
                },
                "candidates": [
                    {
                        "selection_id": "group",
                        "paper_key": "paper-1",
                        "paragraph_under_consideration": {"full_text": "Repeated corpus"},
                    }
                ],
            },
        )

    def test_matching_prefix_is_stable_when_only_the_focus_changes(self):
        config = load_pipeline_config(CONFIG_PATH)
        prompts = PromptRepository(config.prompt_root, config.context_root)
        request = self.request()
        first = prompts.render(request.prompt_ref, request.context_ref, request.context)
        request.context["focus"]["paragraph_under_consideration"]["full_text"] = "Second focus"
        second = prompts.render(request.prompt_ref, request.context_ref, request.context)
        self.assertEqual(first.cacheable_context, second.cacheable_context)
        self.assertIn("Repeated corpus", first.cacheable_context)
        self.assertNotIn("First focus", first.cacheable_context)
        self.assertIn("First focus", first.user)
        self.assertNotIn("Repeated corpus", first.user)
        self.assertNotEqual(first.context_hash, second.context_hash)
        request.context["candidates"][0]["paragraph_under_consideration"]["full_text"] = (
            "Changed corpus"
        )
        third = prompts.render(request.prompt_ref, request.context_ref, request.context)
        self.assertNotEqual(second.cacheable_context, third.cacheable_context)
        self.assertNotEqual(second.context_hash, third.context_hash)

    def test_exact_results_survive_provider_restarts_but_not_changed_evidence_or_force(self):
        config = load_pipeline_config(CONFIG_PATH)
        response = SimpleNamespace(
            value={
                "target_id": "group",
                "basis": "The same role",
                "evidence": {"focus": ["focus"], "target": ["Repeated corpus"]},
            },
            raw_response={"id": "response", "usage": {"input_tokens": 30, "output_tokens": 10}},
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("pipeline.incremental_graph.judgments.create_skill_client") as client,
        ):
            client.return_value.run_json.return_value = response
            client.return_value.register.return_value = SkillRef(
                "skills/match-role", "skill", "v1", "hash"
            )

            def provider(model=config.model):
                return CachedJudgments(
                    PromptRepository(config.prompt_root, config.context_root),
                    model,
                    Path(directory),
                    config.skill_root,
                )

            request = self.request()
            first = provider().judge(request)
            self.assertFalse(first.cache_hit)
            self.assertEqual(
                client.call_args.args[1],
                Path(__file__).resolve().parents[1] / "_cache" / "skill-registry.json",
            )
            self.assertTrue(provider().judge(request).cache_hit)
            guards = config.model.model_copy(
                update={
                    "max_input_tokens": 400_000,
                    "max_prompt_characters": 1_000_000,
                    "max_api_responses_per_process": 6000,
                    "max_session_input_tokens": 60_000_000,
                    "max_session_output_tokens": 2_000_000,
                }
            )
            request.max_input_tokens = 400_000
            self.assertTrue(provider(guards).judge(request).cache_hit)
            self.assertEqual(client.return_value.run_json.call_count, 1)
            call = client.return_value.run_json.call_args
            self.assertEqual(
                call.args[2]["properties"]["target_id"],
                {"anyOf": [{"type": "string", "enum": ["group"]}, {"type": "null"}]},
            )
            self.assertIn("Repeated corpus", call.kwargs["cacheable_context"])
            self.assertNotIn("Repeated corpus", call.args[1])
            self.assertIn("Repeated corpus", first.rendered_user)
            self.assertIn("First focus", first.rendered_user)
            request.context["focus"]["paragraph_under_consideration"]["full_text"] = "Changed focus"
            self.assertFalse(provider().judge(request).cache_hit)
            request.force = True
            self.assertFalse(provider().judge(request).cache_hit)
            self.assertEqual(client.return_value.run_json.call_count, 3)
            model = config.model.model_copy(update={"name": "different-model"})
            request.force = False
            self.assertFalse(provider(model).judge(request).cache_hit)
            # Same text assigned to a different paper changes the collective-role judgment.
            previous_calls = client.return_value.run_json.call_count
            request.context["candidates"][0]["paper_key"] = "paper-2"
            self.assertFalse(provider().judge(request).cache_hit)
            self.assertTrue(provider().judge(request).cache_hit)
            self.assertEqual(client.return_value.run_json.call_count, previous_calls + 1)

    def test_match_schema_allows_only_current_candidates_or_null(self):
        from jsonschema import Draft202012Validator

        config = load_pipeline_config(CONFIG_PATH)
        with tempfile.TemporaryDirectory() as directory:
            provider = CachedJudgments(
                PromptRepository(config.prompt_root, config.context_root),
                config.model,
                Path(directory),
                config.skill_root,
            )
            request = self.request()
            first = provider.render_request(request)
            validator = Draft202012Validator(first.schema)
            self.assertTrue(
                validator.is_valid(
                    {
                        "target_id": "group",
                        "basis": "Role",
                        "evidence": {"focus": ["focus"], "target": ["Repeated corpus"]},
                    }
                )
            )
            self.assertTrue(
                validator.is_valid(
                    {
                        "target_id": None,
                        "basis": "No match",
                        "evidence": {"focus": [], "target": []},
                    }
                )
            )
            self.assertFalse(validator.is_valid({"target_id": "paper-group", "basis": "Role"}))
            request.allowed_match_ids = []
            second = provider.render_request(request)
            self.assertEqual(second.schema["properties"]["target_id"], {"type": "null"})
            self.assertNotEqual(first.schema_hash, second.schema_hash)
            self.assertEqual(first.schema["properties"]["target_id"]["anyOf"][0]["enum"], ["group"])
