"""Dataset rescue only repairs unambiguous identifiers, never semantic judgments."""

import unittest
import tempfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from helpers.recover_hci_20260907 import RecoveryProvider, normalize_hci_target
from pipeline.incremental_graph.llm import AnthropicJudgmentProvider
from pipeline.incremental_graph.models import JudgmentRequest, JudgmentResult


class HciRecoveryTest(unittest.TestCase):
    def test_recovery_preserves_original_response_and_reasoning(self):
        request = JudgmentRequest(
            key="corpusstudio:match",
            paper_index=2,
            stage_id="section_matching",
            output_kind="match",
            prompt_ref="prompt",
            context_ref="matching",
            allowed_match_ids=["s0003"],
            context={"candidates": [{"paper_id": "corpusstudio", "section_id": "s0003"}]},
        )
        original = {"target_id": "corpusstudio.s0003", "basis": "Original model reasoning"}
        result = JudgmentResult(
            fingerprint="old",
            normalized=original,
            raw_response={"id": "response", "value": original},
            rendered_system="system",
            rendered_user="user",
            prompt_hash="prompt",
            context_hash="context",
            schema_hash="old-schema",
            model={"name": "model"},
        )
        rejected = {
            request.key: {
                "request": request.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
            }
        }
        before = deepcopy(rejected)
        live = SimpleNamespace(
            render_request=lambda _: SimpleNamespace(schema_hash="new-schema"),
            prompts=SimpleNamespace(render=lambda *args: SimpleNamespace(schema_hash="old-schema")),
            _validate=AnthropicJudgmentProvider._validate,
        )
        with tempfile.TemporaryDirectory() as directory:
            recovered = RecoveryProvider(live, {}, rejected, Path(directory)).judge(request)
        self.assertEqual(recovered.normalized, {**original, "target_id": "s0003"})
        self.assertEqual(recovered.raw_response, result.raw_response)
        self.assertEqual(rejected, before)
        self.assertIn("id_correction", recovered.model)

    def setUp(self):
        self.request = SimpleNamespace(
            allowed_match_ids=["s0003"],
            context={"candidates": [{"paper_id": "corpusstudio", "section_id": "s0003"}]},
        )

    def test_known_qualifiers_and_whitespace_are_rescued(self):
        for target in (
            "s0003",
            " s0003 ",
            "corpusstudio.s0003",
            "corpusstudio-s0003",
            "corpusstudio:s0003",
            "corpusstudio/s0003",
        ):
            with self.subTest(target=target):
                self.assertEqual(normalize_hci_target(target, self.request), "s0003")
        self.assertIsNone(normalize_hci_target(None, self.request))

    def test_unknown_foreign_or_semantic_selections_are_not_guessed(self):
        for target in (
            "abstractexplorer.s0003",
            "other.s0003",
            "corpusstudio.s0004",
            "Introduction",
            3,
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                normalize_hci_target(target, self.request)

    def test_duplicate_candidate_identity_fails_closed(self):
        self.request.context["candidates"] *= 2
        with self.assertRaises(ValueError):
            normalize_hci_target("corpusstudio.s0003", self.request)
