"""Only generation-affecting inputs invalidate a cached judgment."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_incremental_graph import CONFIG_PATH

from pipeline.incremental_graph.configuration import PromptRepository, load_pipeline_config
from pipeline.incremental_graph.llm import AnthropicJudgmentProvider, JudgmentError
from pipeline.incremental_graph.models import JudgmentRequest
from pipeline.llm.client import SkillRef


class JudgmentCacheTest(unittest.TestCase):
    def test_rejected_id_keeps_raw_response_without_becoming_a_cache_hit(self):
        config = load_pipeline_config(CONFIG_PATH)
        raw = {"id": "rejected-response", "usage": {"output_tokens": 12}}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("pipeline.incremental_graph.llm.ClaudeSkills") as client,
        ):
            client.return_value.register.return_value = SkillRef(
                "match-role", "skill", "v1", "hash"
            )
            client.return_value.run_json.return_value = SimpleNamespace(
                value={"target_id": "paper-group", "basis": "Original explanation"},
                raw_response=raw,
            )
            provider = AnthropicJudgmentProvider(
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
                "focus": {"text": "First focus"},
                "candidates": [{"selection_id": "group", "text": "Repeated corpus"}],
            },
        )

    def test_matching_prefix_is_stable_when_only_the_focus_changes(self):
        config = load_pipeline_config(CONFIG_PATH)
        prompts = PromptRepository(config.prompt_root, config.context_root)
        request = self.request()
        first = prompts.render(request.prompt_ref, request.context_ref, request.context)
        request.context["focus"] = {"text": "Second focus"}
        second = prompts.render(request.prompt_ref, request.context_ref, request.context)
        self.assertEqual(first.cacheable_context, second.cacheable_context)
        self.assertIn("Repeated corpus", first.cacheable_context)
        self.assertNotIn("First focus", first.cacheable_context)
        self.assertIn("First focus", first.user)
        self.assertNotIn("Repeated corpus", first.user)
        self.assertNotEqual(first.context_hash, second.context_hash)
        request.context["candidates"][0]["text"] = "Changed corpus"
        third = prompts.render(request.prompt_ref, request.context_ref, request.context)
        self.assertNotEqual(second.cacheable_context, third.cacheable_context)
        self.assertNotEqual(second.context_hash, third.context_hash)

    def test_exact_results_survive_provider_restarts_but_not_changed_evidence_or_force(self):
        config = load_pipeline_config(CONFIG_PATH)
        response = SimpleNamespace(
            value={"target_id": "group", "basis": "The same role"},
            raw_response={"id": "response", "usage": {"input_tokens": 30, "output_tokens": 10}},
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("pipeline.incremental_graph.llm.ClaudeSkills") as client,
        ):
            client.return_value.run_json.return_value = response
            client.return_value.register.return_value = SkillRef(
                "skills/match-role", "skill", "v1", "hash"
            )

            def provider(model=config.model):
                return AnthropicJudgmentProvider(
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
                config.skill_root.parent / "_cache" / "skill-registry.json",
            )
            self.assertTrue(provider().judge(request).cache_hit)
            self.assertEqual(client.return_value.run_json.call_count, 1)
            call = client.return_value.run_json.call_args
            self.assertIn("Repeated corpus", call.kwargs["cacheable_context"])
            self.assertNotIn("Repeated corpus", call.args[1])
            self.assertIn("Repeated corpus", first.rendered_user)
            self.assertIn("First focus", first.rendered_user)
            request.context["focus"]["text"] = "Changed focus"
            self.assertFalse(provider().judge(request).cache_hit)
            request.force = True
            self.assertFalse(provider().judge(request).cache_hit)
            self.assertEqual(client.return_value.run_json.call_count, 3)
            model = config.model.model_copy(update={"name": "different-model"})
            request.force = False
            self.assertFalse(provider(model).judge(request).cache_hit)
