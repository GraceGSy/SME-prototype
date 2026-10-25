"""Jev transport, selection, caching, and evidence tests without network access."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import test_judgment_cache
from test_graph_runs import manifest
from test_incremental_graph import CONFIG_PATH

from pipeline.incremental_graph.configuration import PromptRepository, load_pipeline_config
from pipeline.incremental_graph.evidence_encoding import encode_evidence
from pipeline.incremental_graph.jev_selection import JevSelector
from pipeline.incremental_graph.judgments import CachedJudgments, JudgmentError
from pipeline.incremental_graph.runs import start_graph
from pipeline.providers.contracts import SkillRef
from pipeline.providers.jev import (
    NO_MATCH,
    JevClient,
    JevRequestTooLarge,
    JevSettings,
    choice_from_probabilities,
    validate_response,
)


def answer(body, choice=None, noul=None):
    answers = {}
    if "match" in body["questions"]:
        options = body["questions"]["match"]["criteria"]
        selected = choice if choice in options else next(iter(options))
        answers["match"] = {
            "type": "choice",
            "choice": selected,
            "confidence": 1.0,
            "probabilities": {option: float(option == selected) for option in options},
        }
    if "has_match" in body["questions"]:
        answers["has_match"] = {
            "type": "noul",
            "noul": float(choice != NO_MATCH) if noul is None else noul,
        }
    return {
        "model": body["model"],
        "answers": answers,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


class JevTest(unittest.TestCase):
    def setUp(self):
        self.config = load_pipeline_config(CONFIG_PATH)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def selector(self, **settings):
        return JevSelector(
            JevSettings(**settings),
            self.root / "jev",
            self.config.skill_root,
            self.config.prompt_root,
        )

    def request(self, count=1):
        request = test_judgment_cache.JudgmentCacheTest().request()
        request.allowed_match_ids = [f"candidate-{i}" for i in range(count)]
        source = request.context["candidates"][0]
        request.context["candidates"] = [
            {**source, "selection_id": key} for key in request.allowed_match_ids
        ]
        return request

    def provider(self, **settings):
        return CachedJudgments(
            PromptRepository(self.config.prompt_root, self.config.context_root),
            self.config.model,
            self.root / "cache",
            self.config.skill_root,
            jev=JevSettings(**settings),
        )

    def test_prompt_keeps_sources_and_shared_lessons_without_generation_instructions(self):
        selector = self.selector()
        request = self.request(2)
        original = request.model_copy(deep=True)
        body = selector.build_request(request.context)
        expected = encode_evidence(
            {
                **request.context,
                "candidates": dict(zip(request.allowed_match_ids, request.context["candidates"])),
            }
        )
        self.assertNotIn(
            "Return only the candidate handle", body["state"]["text_reference_contract"]
        )
        self.assertTrue(
            expected.pop("text_reference_contract").startswith(
                body["state"]["text_reference_contract"]
            )
        )
        self.assertEqual(
            {
                key: value
                for key, value in body["state"].items()
                if key != "text_reference_contract"
            },
            expected,
        )
        self.assertEqual(request, original)
        self.assertEqual(len(selector.examples), 6)
        examples = json.dumps(selector.examples)
        self.assertNotIn("Expected output", examples)
        self.assertNotIn('"target_id"', examples)
        self.assertNotIn('"evidence"', examples)
        self.assertIn(
            "same source-grounded role",
            body["questions"]["match"]["criteria"]["candidate-0"]["meaning"],
        )
        self.assertIn("Generated questions are fallible summaries", selector.instructions)

    def test_noul_mode_uses_only_real_candidates_and_abstains_on_no_or_tie(self):
        selector = self.selector(selection_mode="choice_noul")
        for probability, expected in (
            (0.0, None),
            (0.5, None),
            (0.51, "candidate-1"),
            (1.0, "candidate-1"),
        ):
            with (
                self.subTest(probability=probability),
                patch.object(
                    selector.client,
                    "choose",
                    side_effect=lambda body: answer(body, "candidate-1", probability),
                ) as client,
            ):
                result = selector.select(self.request(2), force=True)
                body = client.call_args.args[0]
                self.assertEqual(set(body["questions"]), {"match", "has_match"})
                self.assertNotIn(NO_MATCH, body["questions"]["match"]["criteria"])
                self.assertEqual(result["target_id"], expected)
                self.assertEqual(result["has_match"]["noul"], probability)

    def test_single_candidate_uses_noul_only_and_caches_it(self):
        selector = self.selector(selection_mode="choice_noul")
        with (
            patch("pipeline.providers.jev.load_api_key", return_value="hidden-key"),
            patch(
                "pipeline.providers.jev.urlopen",
                side_effect=lambda req, **kw: io.BytesIO(
                    json.dumps(answer(json.loads(req.data))).encode()
                ),
            ) as network,
        ):
            first = selector.select(self.request())
            second = selector.select(self.request())
            self.assertEqual(first["target_id"], "candidate-0")
            self.assertIsNone(first["choice"])
            self.assertTrue(second["calls"][0]["cache_hit"])
            self.assertEqual(network.call_count, 1)
            body = json.loads(network.call_args.args[0].data)
            self.assertEqual(set(body["questions"]), {"has_match"})

    def test_noul_splits_rerank_even_when_half_pool_abstains(self):
        selector = self.selector(selection_mode="choice_noul")

        def choose(body):
            count = len(body["state"]["candidates"])
            return answer(body, noul=1.0 if count == 10 else 0.0)

        with patch.object(selector.client, "choose", side_effect=choose) as client:
            result = selector.select(self.request(256))
            self.assertEqual(client.call_count, 3)
            self.assertEqual(result["target_id"], "candidate-0")
            self.assertEqual(
                [len(call.args[0]["state"]["candidates"]) for call in client.call_args_list],
                [128, 128, 10],
            )

    def test_frozen_pool_stops_on_size_error_without_splitting(self):
        selector = self.selector()
        with patch.object(selector.client, "choose", side_effect=JevRequestTooLarge) as client:
            with self.assertRaisesRegex(ValueError, "cannot split candidates"):
                selector.select(self.request(20), allow_splitting=False)
            self.assertEqual(client.call_count, 1)

    def test_noul_response_validates_finite_probability_question_names_and_types(self):
        body = self.selector(selection_mode="choice_noul").build_request(self.request().context)
        for probability in (-0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(probability=probability), self.assertRaises(ValueError):
                validate_response(answer(body, noul=probability), body)
        good = answer(body, noul=0.8)
        self.assertEqual(validate_response(good, body), good)
        with self.assertRaises(ValueError):
            validate_response({**good, "answers": {}}, body)
        with self.assertRaisesRegex(ValueError, "question type"):
            validate_response(good, {**body, "questions": {"has_match": {"type": "choice"}}})

    def test_complete_cache_tracks_jev_prompt_and_mode_not_budgets(self):
        request = self.request(2)
        provider = self.provider()
        with patch(
            "pipeline.providers.jev.JevClient.choose",
            side_effect=lambda body: answer(body, NO_MATCH),
        ) as client:
            provider.judge(request)
            self.assertTrue(self.provider(max_calls=1000).judge(request).cache_hit)
            provider.jev.instructions += " Changed policy."
            self.assertFalse(provider.judge(request).cache_hit)
            self.assertFalse(self.provider(selection_mode="choice_noul").judge(request).cache_hit)
            self.assertEqual(client.call_count, 3)

    def test_transport_uses_documented_body_and_never_records_credentials(self):
        selector = self.selector()
        request = self.request()

        def http(req, **kwargs):
            self.assertEqual(req.full_url, "https://api.typesafe.ai/v1/systemone")
            self.assertEqual(req.headers["Authorization"], "Bearer hidden-key")
            self.assertEqual(kwargs["timeout"], 120)
            body = json.loads(req.data)
            self.assertEqual(set(body), {"model", "state", "questions"})
            return io.BytesIO(json.dumps(answer(body)).encode())

        with (
            patch("pipeline.providers.jev.load_api_key", return_value="hidden-key"),
            patch("pipeline.providers.jev.urlopen", side_effect=http) as network,
        ):
            first = selector.select(request)
            second = self.selector().select(request)
            self.assertEqual(first["target_id"], "candidate-0")
            self.assertTrue(second["calls"][0]["cache_hit"])
            self.assertEqual(network.call_count, 1)
        for path in self.root.rglob("*.json"):
            self.assertNotIn("hidden-key", path.read_text())

    def test_empty_pool_and_abstention(self):
        selector = self.selector()
        with patch.object(
            selector.client, "choose", side_effect=lambda body: answer(body, NO_MATCH)
        ) as client:
            self.assertIsNone(selector.select(self.request(0))["target_id"])
            client.assert_not_called()
            self.assertIsNone(selector.select(self.request())["target_id"])

    def test_oversized_pool_splits_then_reranks_and_preserves_partial_cache(self):
        selector = self.selector()
        with patch.object(selector.client, "choose", side_effect=answer) as client:
            selection = selector.select(self.request(300))
            self.assertEqual(client.call_count, 3)
            bodies = [call.args[0] for call in client.call_args_list]
            self.assertEqual(
                [len(body["questions"]["match"]["criteria"]) for body in bodies], [151, 151, 11]
            )
            self.assertEqual(selection["target_id"], "candidate-0")
            self.assertEqual(len(selection["calls"]), 3)
            selector.select(self.request(300))
            self.assertEqual(client.call_count, 3)
            selector.select(self.request(300), force=True)
            self.assertEqual(client.call_count, 6)

    def test_recursive_splits_do_not_compare_probabilities_across_halves(self):
        selector = self.selector()
        with patch.object(selector.client, "choose", side_effect=answer) as client:
            result = selector.select(self.request(600))
            self.assertEqual(len(result["calls"]), 7)
            self.assertEqual(client.call_count, 7)
            self.assertEqual(result["target_id"], "candidate-0")

    def test_request_above_old_byte_cap_reaches_transport_without_truncation(self):
        selector = self.selector()
        request = self.request()
        source = "Full source evidence. " * 2500
        request.context["focus"]["paragraph_under_consideration"]["full_text"] = source

        def http(req, **kwargs):
            self.assertGreater(len(req.data), 48_228)
            self.assertIn(source, req.data.decode())
            self.assertNotIn("Typesafe-danger-zone-long-context", req.headers)
            return io.BytesIO(json.dumps(answer(json.loads(req.data))).encode())

        with (
            patch("pipeline.providers.jev.load_api_key", return_value="key"),
            patch("pipeline.providers.jev.urlopen", side_effect=http) as network,
        ):
            self.assertEqual(selector.select(request)["target_id"], "candidate-0")
            self.assertEqual(network.call_count, 1)

    def test_provider_context_limit_splits_then_reranks(self):
        selector = self.selector()

        def http(req, **kwargs):
            body = json.loads(req.data)
            if len(body["questions"]["match"]["criteria"]) > 11:
                raise HTTPError(
                    "url",
                    400,
                    "Bad Request",
                    {},
                    io.BytesIO(b'{"detail":{"error_type":"max_tokens_exceeded"}}'),
                )
            return io.BytesIO(json.dumps(answer(body)).encode())

        with (
            patch("pipeline.providers.jev.load_api_key", return_value="key"),
            patch("pipeline.providers.jev.urlopen", side_effect=http) as network,
        ):
            result = selector.select(self.request(20))
            self.assertEqual(network.call_count, 4)
            self.assertEqual(len(result["calls"]), 3)
            self.assertEqual(result["target_id"], "candidate-0")
        records = [
            json.loads(path.read_text()) for path in (self.root / "jev/responses").glob("*.json")
        ]
        rejected = [record for record in records if record.get("http_status") == 400]
        self.assertEqual(len(rejected), 1)
        self.assertIn("max_tokens_exceeded", rejected[0]["response_text"])

    def test_provider_rejects_single_candidate_without_truncation(self):
        selector = self.selector()
        with patch.object(selector.client, "choose", side_effect=JevRequestTooLarge) as client:
            with self.assertRaisesRegex(ValueError, "no source text was truncated"):
                selector.select(self.request())
            self.assertEqual(client.call_count, 1)

    def test_unshrinkable_context_pool_stops(self):
        selector = self.selector()

        def choose(body):
            if len(body["questions"]["match"]["criteria"]) > 2:
                raise JevRequestTooLarge()
            return answer(body)

        with patch.object(selector.client, "choose", side_effect=choose) as client:
            with self.assertRaisesRegex(ValueError, "no automatic truncation"):
                selector.select(self.request(2))
            self.assertEqual(client.call_count, 3)

    def test_changed_evidence_model_or_policy_cannot_reuse_a_selection(self):
        selector = self.selector()
        request = self.request()
        with patch("pipeline.providers.jev.JevClient.choose", side_effect=answer) as client:
            selector.select(request)
            request.context["focus"]["paper_key"] = "different-source"
            selector.select(request)
            self.selector(model="jev-1.13.0").select(request)
            selector.instructions += " Additional criterion."
            selector.select(request)
            self.assertEqual(client.call_count, 4)

    def test_invalid_responses_are_rejected(self):
        body = {
            "model": "jev-1.14.0",
            "questions": {"match": {"criteria": {"a": "A", NO_MATCH: "None"}}},
        }
        for corruption in (
            "unknown",
            "missing",
            "sum",
            "confidence",
            "model",
            "usage",
        ):
            with self.subTest(corruption=corruption):
                value = answer(body)
                item = value["answers"]["match"]
                if corruption == "unknown":
                    item["choice"] = "unknown"
                elif corruption == "missing":
                    del item["probabilities"][NO_MATCH]
                elif corruption == "sum":
                    item["probabilities"]["a"] = 0.5
                elif corruption == "confidence":
                    item["confidence"] = float("nan")
                elif corruption == "model":
                    value["model"] = "jev-latest"
                elif corruption == "usage":
                    value["usage"]["input_tokens"] = True
                with self.assertRaises(ValueError):
                    validate_response(value, body)

    def test_inconsistent_choice_uses_probabilities_and_preserves_raw_response(self):
        selector = self.selector()
        request = self.request(3)
        body = selector.build_request(request.context)
        payload = answer(body, NO_MATCH)
        payload["answers"]["match"].update(
            confidence=0.44,
            probabilities={
                "candidate-0": 0.48,
                NO_MATCH: 0.47,
                "candidate-1": 0.03,
                "candidate-2": 0.02,
            },
        )
        self.assertEqual(validate_response(payload, body), payload)
        with (
            patch("pipeline.providers.jev.load_api_key", return_value="offline-key"),
            patch(
                "pipeline.providers.jev.urlopen",
                return_value=io.BytesIO(json.dumps(payload).encode()),
            ) as network,
        ):
            first = selector.select(request)
            second = selector.select(request)
        self.assertEqual(network.call_count, 1)
        for result in (first, second):
            self.assertEqual(result["target_id"], "candidate-0")
            self.assertEqual(result["calls"][0]["response"], payload)
            self.assertEqual(
                result["calls"][0]["choice_correction"],
                {
                    "reported_choice": NO_MATCH,
                    "effective_choice": "candidate-0",
                    "reason": "highest_returned_probability",
                },
            )
        self.assertTrue(second["calls"][0]["cache_hit"])
        raw_path = next((self.root / "jev/responses").glob("*.json"))
        self.assertEqual(json.loads(json.loads(raw_path.read_text())["response_text"]), payload)

    def test_probability_choice_ties_are_deterministic(self):
        for reported, expected in (("b", "b"), ("c", "a")):
            for probabilities in ({"b": 0.5, "a": 0.5, "c": 0.0}, {"c": 0.0, "a": 0.5, "b": 0.5}):
                with self.subTest(reported=reported, probabilities=probabilities):
                    self.assertEqual(
                        choice_from_probabilities(
                            {"choice": reported, "probabilities": probabilities}
                        ),
                        expected,
                    )

    def test_corrected_choice_still_respects_no_match_and_noul_gate(self):
        for mode, probability in (("choice", None), ("choice_noul", 0.5), ("choice_noul", 0.8)):
            selector = self.selector(selection_mode=mode)
            request = self.request(2)
            body = selector.build_request(request.context)
            payload = answer(body, "candidate-0", noul=probability)
            payload["answers"]["match"]["probabilities"] = (
                {"candidate-0": 0.1, "candidate-1": 0.2, NO_MATCH: 0.7}
                if mode == "choice"
                else {"candidate-0": 0.1, "candidate-1": 0.9}
            )
            with (
                self.subTest(mode=mode, noul=probability),
                patch.object(selector.client, "choose", return_value=payload),
            ):
                result = selector.select(request, force=True)
            self.assertEqual(result["target_id"], "candidate-1" if probability == 0.8 else None)

    def test_probability_rounding_preserves_original_values(self):
        body = {
            "model": "jev-1.14.0",
            "questions": {"match": {"criteria": {"a": "A", NO_MATCH: "None"}}},
        }
        for total in (0.981, 0.99, 1.0, 1.01, 1.02):
            with self.subTest(total=total):
                value = answer(body)
                value["answers"]["match"]["probabilities"] = {"a": 0.6, NO_MATCH: total - 0.6}
                self.assertEqual(validate_response(value, body), value)

    def test_probability_rounding_does_not_accept_invalid_distributions(self):
        body = {
            "model": "jev-1.14.0",
            "questions": {"match": {"criteria": {"a": "A", NO_MATCH: "None"}}},
        }
        for probabilities in (
            {"a": 0.6, NO_MATCH: 0.38},
            {"a": 0.6, NO_MATCH: 0.37},
            {"a": 0.6, NO_MATCH: 0.43},
            {"a": 1.01, NO_MATCH: -0.01},
            {"a": float("inf"), NO_MATCH: 0.0},
            {"a": float("nan"), NO_MATCH: 0.0},
        ):
            with self.subTest(probabilities=probabilities):
                value = answer(body)
                value["answers"]["match"]["probabilities"] = probabilities
                with self.assertRaises(ValueError):
                    validate_response(value, body)

    def test_bad_response_is_saved_but_not_cached(self):
        selector = self.selector()
        with (
            patch("pipeline.providers.jev.load_api_key", return_value="key"),
            patch("pipeline.providers.jev.urlopen", return_value=io.BytesIO(b'{"wrong": true}')),
        ):
            with self.assertRaises(ValueError):
                selector.select(self.request())
        self.assertEqual(len(list((self.root / "jev/responses").glob("*.json"))), 1)
        self.assertEqual(list((self.root / "jev").glob("*.json")), [])

    def test_http_and_connection_errors_do_not_retry_automatically(self):
        for error in (
            HTTPError("url", 429, "rate limit", {}, io.BytesIO(b"")),
            HTTPError("url", 400, "Bad Request", {}, io.BytesIO(b'{"detail":"invalid request"}')),
            HTTPError("url", 400, "Bad Request", {}, io.BytesIO(b"not json")),
            URLError("offline"),
        ):
            with (
                patch("pipeline.providers.jev.load_api_key", return_value="key"),
                patch("pipeline.providers.jev.urlopen", side_effect=error) as network,
            ):
                with self.assertRaises(RuntimeError):
                    self.selector().select(self.request())
                self.assertEqual(network.call_count, 1)

    def test_call_guard_stops_before_request(self):
        client = JevClient(JevSettings(max_calls=1), self.root, self.root)
        client.calls = 1
        body = {"questions": {"match": {"criteria": {"a": "A", "b": "B"}}}}
        with patch("pipeline.providers.jev.urlopen") as network:
            with self.assertRaisesRegex(ValueError, "call limit"):
                client.choose(body)
            network.assert_not_called()

    def test_provider_body_guard_stops_before_request(self):
        client = JevClient(JevSettings(), self.root, self.root)
        body = {"questions": {"match": {"criteria": {"a": "A", "b": "B"}}}}
        with (
            patch("pipeline.providers.jev.MAX_REQUEST_BYTES", 1),
            patch("pipeline.providers.jev.urlopen") as network,
        ):
            with self.assertRaisesRegex(JevRequestTooLarge, "32 MiB"):
                client.choose(body)
            network.assert_not_called()

    def test_only_explicit_provider_size_errors_allow_splitting(self):
        for status, body in (
            (400, b'{"detail":"max_tokens_exceeded"}'),
            (413, b"payload too large"),
        ):
            with (
                self.subTest(status=status),
                patch("pipeline.providers.jev.load_api_key", return_value="key"),
                patch(
                    "pipeline.providers.jev.urlopen",
                    side_effect=HTTPError("url", status, "rejected", {}, io.BytesIO(body)),
                ) as network,
            ):
                with self.assertRaisesRegex(ValueError, "no source text was truncated"):
                    self.selector().select(self.request())
                self.assertEqual(network.call_count, 1)

    def test_jev_requires_both_credentials_before_run_creation(self):
        docs = manifest(self.root, ["a", "b"], "source")
        with patch(
            "pipeline.incremental_graph.runs.load_api_key", side_effect=RuntimeError("missing key")
        ):
            with self.assertRaisesRegex(RuntimeError, "missing key"):
                start_graph(docs, self.root / "run", jev=True)
        self.assertFalse((self.root / "run").exists())

    def test_evidence_is_fixed_and_cached_independently_of_selection(self):
        provider = self.provider()
        request = self.request()
        raw = {"id": "evidence-response", "usage": {"input_tokens": 10}}
        value = {
            "target_id": "candidate-0",
            "basis": "A shared role",
            "evidence": {"focus": ["focus"], "target": ["Repeated corpus"]},
        }
        client = SimpleNamespace(
            register=lambda path: SkillRef("match-role", "skill", "1", "hash"),
            run_json=lambda *args, **kwargs: SimpleNamespace(value=value, raw_response=raw),
        )
        with (
            patch.object(provider.jev.client, "choose", side_effect=answer) as choose,
            patch("pipeline.incremental_graph.judgments.create_skill_client", return_value=client),
        ):
            first = provider.judge(request)
            self.assertEqual(first.raw_response["jev"]["target_id"], "candidate-0")
            self.assertIn('"fixed_target_id": "candidate-0"', first.rendered_user)
            self.assertTrue(self.provider().judge(request).cache_hit)
            self.assertEqual(choose.call_count, 1)

    def test_quotation_retries_do_not_reselect_and_cannot_override_jev(self):
        provider = self.provider()
        request = self.request()
        values = [
            {
                "target_id": "candidate-0",
                "basis": "Role",
                "evidence": {"focus": ["fabricated"], "target": ["Repeated corpus"]},
            },
            {
                "target_id": "candidate-0",
                "basis": "Role",
                "evidence": {"focus": ["focus"], "target": ["Repeated corpus"]},
            },
        ]
        with (
            patch.object(provider.jev.client, "choose", side_effect=answer) as choose,
            patch("pipeline.incremental_graph.judgments.create_skill_client") as client,
        ):
            client.return_value.register.return_value = SkillRef("match-role", "s", "1", "hash")
            client.return_value.run_json.side_effect = [
                SimpleNamespace(value=v, raw_response={"id": str(i)}) for i, v in enumerate(values)
            ]
            provider.judge(request)
            self.assertEqual(choose.call_count, 1)
            self.assertEqual(client.return_value.run_json.call_count, 2)
            schema = client.return_value.run_json.call_args.args[2]
            self.assertEqual(
                schema["properties"]["target_id"], {"type": "string", "enum": ["candidate-0"]}
            )
            request.force = True
            client.return_value.run_json.side_effect = [
                SimpleNamespace(
                    value={**values[1], "target_id": None}, raw_response={"id": "wrong"}
                )
            ]
            with self.assertRaisesRegex(JudgmentError, "must not change"):
                provider.judge(request)

    def test_no_match_does_not_buy_a_generative_explanation(self):
        provider = self.provider()
        with (
            patch.object(
                provider.jev.client, "choose", side_effect=lambda body: answer(body, NO_MATCH)
            ),
            patch("pipeline.incremental_graph.judgments.create_skill_client") as generative,
        ):
            result = provider.judge(self.request())
            self.assertIsNone(result.normalized["target_id"])
            generative.assert_not_called()


if __name__ == "__main__":
    unittest.main()
