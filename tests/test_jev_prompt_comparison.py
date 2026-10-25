"""Frozen-source comparison uses no generative model and never edits the source run."""

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_judgment_cache
from test_jev import answer

from pipeline.files import read_json, write_json
from pipeline.incremental_graph.evidence_encoding import encode_evidence
from pipeline.incremental_graph.match_evidence import candidate_handle
from pipeline.jev_prompt_comparison import compare_prompts, decode_saved_state
from pipeline.providers.jev import encode_request


class PromptComparisonTest(unittest.TestCase):
    def test_lossless_decode_preserves_text_order_and_empty_paragraphs(self):
        context = {
            "focus": {"full_text": "First.\n\nSecond.\n\n"},
            "candidates": [{"full_text": "Second.\n\nFirst."}],
        }
        self.assertEqual(decode_saved_state(encode_evidence(context)), context)

    def test_plan_live_cache_and_changed_plan_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            revision = root / "run/revisions/revision-0001"
            request = test_judgment_cache.JudgmentCacheTest().request()
            candidate = candidate_handle(request.context["candidates"][0])
            body = {
                "model": "jev-1.14.0",
                "state": encode_evidence(request.context),
                "questions": {
                    "match": {
                        "type": "choice",
                        "criteria": {candidate: "Candidate", "NO_MATCH": "None"},
                    }
                },
            }
            fingerprint = hashlib.sha256(encode_request(body)).hexdigest()
            write_json(
                root / "run/cache/jev" / f"{fingerprint}.json",
                {"request": body, "response": answer(body)},
            )
            attempt = {
                "attempt_id": "attempt-000001",
                "request_key": request.key,
                "paper_index": request.paper_index,
                "stage_id": request.stage_id,
                "prompt_ref": request.prompt_ref,
                "context_ref": request.context_ref,
                "candidate_ids": [candidate],
                "raw_response": {
                    "jev": {"target_id": candidate, "calls": [{"fingerprint": fingerprint}]}
                },
            }
            # write_json's default indent is multiline, so supply a JSONL line here.
            provenance = revision / "provenance/attempts.jsonl"
            provenance.parent.mkdir(parents=True)
            provenance.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
            cases = root / "cases.json"
            write_json(cases, [{"attempt_id": "attempt-000001", "label": "Example"}])
            original = {p: p.read_bytes() for p in (root / "run").rglob("*") if p.is_file()}
            with (
                patch("pipeline.providers.jev.load_api_key", return_value="offline-key"),
                patch(
                    "pipeline.providers.jev.urlopen",
                    side_effect=lambda req, **kw: io.BytesIO(
                        json.dumps(answer(json.loads(req.data))).encode()
                    ),
                ) as network,
            ):
                plan = compare_prompts(revision, cases, root / "out")
                self.assertEqual(plan["http_attempts"], 0)
                network.assert_not_called()
                result = compare_prompts(revision, cases, root / "out", live=True)
                self.assertEqual(result["last_invocation"]["http_attempts"], 2)
                self.assertEqual(set(result["cases"][0]["variants"]), {"choice", "choice_noul"})
                compare_prompts(revision, cases, root / "out", live=True)
                self.assertEqual(network.call_count, 2)
                with patch(
                    "pipeline.incremental_graph.jev_selection.matching_examples", return_value=[]
                ):
                    with self.assertRaisesRegex(ValueError, "prompts changed"):
                        compare_prompts(revision, cases, root / "out", live=True)
                with self.assertRaisesRegex(ValueError, "outside the original run"):
                    compare_prompts(revision, cases, revision / "out")
            self.assertEqual(original, {p: p.read_bytes() for p in original})
            self.assertEqual(read_json(root / "out/comparison.json")["status"], "complete")


if __name__ == "__main__":
    unittest.main()
