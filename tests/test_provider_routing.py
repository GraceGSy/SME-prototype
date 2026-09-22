"""Changing providers must not change SMELTER's prompts, rules, or result reuse."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_graph_runs import manifest
from test_incremental_graph import CONFIG_PATH
from test_match_evidence import evidence_request, evidence_response

from pipeline.document import QUESTION_FIELD
from pipeline.files import read_json
from pipeline.incremental_graph.configuration import PromptRepository, load_pipeline_config
from pipeline.incremental_graph.judgments import CachedJudgments
from pipeline.incremental_graph.models import ModelSettings
from pipeline.incremental_graph.runs import add_papers, retry_graph, start_graph
from pipeline.providers.contracts import SkillRef
from pipeline.providers.factory import create_skill_client


class ProviderRoutingTest(unittest.TestCase):
    def test_selection_is_explicit_and_registration_files_do_not_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "skill-registry.json"
            with (
                patch("pipeline.providers.anthropic.ClaudeSkills") as claude,
                patch("pipeline.providers.openai.OpenAISkills") as openai,
            ):
                self.assertIs(
                    create_skill_client(root, registry, "claude-sonnet-5"), claude.return_value
                )
                self.assertIs(
                    create_skill_client(root, registry, "gpt-5.6-sol", provider="openai"),
                    openai.return_value,
                )
                self.assertEqual(claude.call_args.args[1], registry)
                self.assertEqual(openai.call_args.args[1], root / "skill-registry-openai.json")
                with self.assertRaises(ValueError):
                    create_skill_client(root, registry, "x", provider="typo")
                self.assertEqual(claude.call_count, 1)
                self.assertEqual(openai.call_count, 1)
        with self.assertRaises(ValueError):
            ModelSettings(provider="openai")
        self.assertEqual(ModelSettings(provider="openai", name="gpt-5.6-sol").name, "gpt-5.6-sol")

    def test_shared_prompts_and_evidence_retries_keep_provider_caches_separate(self):
        config = load_pipeline_config(CONFIG_PATH)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clients = {}
            for name in ("anthropic", "openai"):
                client = Mock()
                client.register.return_value = SkillRef("skills/match-role", name, "1", "a" * 64)
                bad = evidence_response()
                bad["evidence"]["focus"] = ["Costs are awarded"]
                client.run_json.side_effect = [
                    SimpleNamespace(value=bad, raw_response={"id": "bad"}),
                    SimpleNamespace(value=evidence_response(), raw_response={"id": "good"}),
                ]
                clients[name] = client
            with patch(
                "pipeline.incremental_graph.judgments.create_skill_client",
                side_effect=lambda *args, provider, **kwargs: clients[provider],
            ) as factory:

                def judge(provider):
                    model = ModelSettings.model_validate(
                        {
                            **config.model.model_dump(),
                            "provider": provider,
                            "name": "gpt-5.6-sol" if provider == "openai" else config.model.name,
                        }
                    )
                    return CachedJudgments(
                        PromptRepository(config.prompt_root, config.context_root),
                        model,
                        root,
                        config.skill_root,
                    )

                first = judge("anthropic").judge(evidence_request())
                second = judge("openai").judge(evidence_request())
                self.assertNotEqual(first.fingerprint, second.fingerprint)
                self.assertEqual(first.normalized, second.normalized)
                for index in range(2):
                    a = clients["anthropic"].run_json.call_args_list[index]
                    b = clients["openai"].run_json.call_args_list[index]
                    self.assertEqual(a.args[1:], b.args[1:])
                    self.assertEqual(a.kwargs, b.kwargs)
                self.assertIn(
                    "Evidence validation failed", clients["openai"].run_json.call_args.args[1]
                )
                self.assertTrue(judge("openai").judge(evidence_request()).cache_hit)
                self.assertEqual(factory.call_count, 2)

    def test_start_add_and_retry_use_the_same_pipeline_with_either_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = manifest(root, ["a", "b"], "first")
            third = manifest(root, ["c"], "third")
            final_hashes, calls = [], {}
            for provider, model in (("anthropic", "claude-sonnet-5"), ("openai", "gpt-5.6-sol")):
                calls[provider] = []

                def answer(skills, prompt, schema, **kwargs):
                    calls[provider].append((prompt, schema, kwargs))
                    value = (
                        {
                            "target_id": None,
                            "basis": "No common role",
                            "evidence": {"focus": [], "target": []},
                        }
                        if "target_id" in schema["properties"]
                        else {QUESTION_FIELD: "What happens?"}
                    )
                    return SimpleNamespace(value=value, raw_response={"id": "response"})

                client = Mock()
                client.register.return_value = SkillRef("skills/test", provider, "1", "a" * 64)
                client.run_json.side_effect = answer
                run_dir = root / provider
                with patch(
                    "pipeline.incremental_graph.judgments.create_skill_client", return_value=client
                ) as factory:
                    start_graph(first, run_dir, CONFIG_PATH, provider=provider, model=model)
                    added = add_papers(third, run_dir)
                    before = client.run_json.call_count
                    retried = retry_graph(run_dir)
                    self.assertEqual(client.run_json.call_count, before)
                    self.assertEqual(added["graph_hash"], retried["graph_hash"])
                    self.assertTrue(
                        all(call.kwargs["provider"] == provider for call in factory.call_args_list)
                    )
                saved = read_json(run_dir / "run.json")["config"]["model"]
                self.assertEqual((saved["provider"], saved["name"]), (provider, model))
                final_hashes.append(added["graph_hash"])
            self.assertEqual(final_hashes[0], final_hashes[1])
            self.assertEqual(calls["anthropic"], calls["openai"])
