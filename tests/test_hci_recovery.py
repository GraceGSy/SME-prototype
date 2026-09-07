"""The dated helper can repair only the explicitly authorized HCI selection."""

import unittest
from types import SimpleNamespace

from test_incremental_graph import CONFIG_PATH

from helpers.recover_hci_20260907 import FAILED_KEY, RecoveryProvider, ReplayComplete
from pipeline.incremental_graph.configuration import PromptRepository, load_pipeline_config
from pipeline.incremental_graph.llm import AnthropicJudgmentProvider
from pipeline.incremental_graph.models import JudgmentRequest


class HciRecoveryTest(unittest.TestCase):
    def setUp(self):
        config = load_pipeline_config(CONFIG_PATH)
        self.live = SimpleNamespace(
            prompts=PromptRepository(config.prompt_root, config.context_root),
            _validate=AnthropicJudgmentProvider._validate,
        )
        self.failure = {
            "type": "JudgmentError",
            "message": f"{FAILED_KEY} selected 'corpusstudio-s0003'; allowed values are ['s0003'] or null",
        }
        self.request = JudgmentRequest(
            key=FAILED_KEY,
            paper_index=2,
            stage_id="section_matching",
            output_kind="match",
            prompt_ref="group-to-section-match/v1",
            context_ref="matching",
            skill_ref="match-role",
            allowed_match_ids=["s0003"],
            context={
                "scope": {"level": "section"},
                "focus": {},
                "candidates": [{"paper_id": "corpusstudio", "section_id": "s0003"}],
            },
        )

    def test_exact_recovery_discloses_missing_rationale_without_a_paid_call(self):
        provider = RecoveryProvider(self.live, [], self.failure)
        result = provider.judge(self.request)
        self.assertEqual(result.normalized["target_id"], "s0003")
        self.assertFalse(result.raw_response["original_basis_available"])
        self.assertNotIn("usage", result.raw_response)
        self.assertEqual(result.model["provider"], "manual_recovery")

    def test_recovery_rejects_ambiguous_or_foreign_candidates(self):
        provider = RecoveryProvider(self.live, [], self.failure)
        candidate = self.request.context["candidates"][0]
        self.request.context["candidates"].append(dict(candidate))
        with self.assertRaises(ValueError):
            provider.judge(self.request)
        self.request.context["candidates"] = [{"paper_id": "other", "section_id": "s0003"}]
        with self.assertRaises(ValueError):
            provider.judge(self.request)

    def test_no_general_prefix_normalization(self):
        provider = RecoveryProvider(self.live, [], self.failure)
        self.request.key = "another-request"
        with self.assertRaises(ReplayComplete):
            provider.judge(self.request)
