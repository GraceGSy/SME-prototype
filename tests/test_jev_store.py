"""Jev requests are stored once, rebuild byte for byte, and old caches still replay."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_judgment_cache
from test_jev import answer

from pipeline.files import read_json, write_json
from pipeline.incremental_graph.jev_selection import JevSelector
from pipeline.providers.jev import JevSettings
from pipeline.providers.jev_store import JevStore, compact_cache, fingerprint

PAPER = [
    "paper-1 s1 Introduction | Role: States the problem the paper addresses.",
    "    " + "Interfaces for comparing many documents are hard to scan; " * 4,
    "  paper-1 s1.p2 [context only]",
    '    Ünïcode, quotes " and a backslash \\ survive the round trip. ' * 3,
    "",
    "    short",
]


def body(focus: str, model: str = "jev-1.14.0") -> dict:
    state = "\n".join(["Focus", focus, "", "Context", *PAPER, "Candidates", "Group P1 Role: x"])
    return {"model": model, "state": state, "questions": {"has_match": {"type": "noul"}}}


class JevStoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = JevStore(self.root / "jev")

    def test_requests_rebuild_exactly_and_share_paper_text(self):
        first, second = body("paper-2 s1 focus one"), body("paper-2 s1 focus two")
        keys = [self.store.save(first), self.store.save(second)]
        self.assertEqual(keys, [fingerprint(first), fingerprint(second)])
        for key, original in zip(keys, (first, second)):
            rebuilt = self.store.load(key)
            self.assertEqual(json.dumps(rebuilt), json.dumps(original))  # Same key order.
        # The two long paper lines are kept once, though both requests contain them.
        self.assertEqual(len(list(self.store.lines.glob("*.txt"))), 2)
        stored = sum(p.stat().st_size for p in self.store.root.rglob("*") if p.is_file())
        self.assertLess(stored, len(json.dumps(first)) + len(json.dumps(second)))
        self.assertEqual(self.store.save(first), keys[0])  # Saving again changes nothing.

    def test_a_damaged_text_file_fails_instead_of_answering_another_request(self):
        key = self.store.save(body("focus"))
        line = next(self.store.lines.glob("*.txt"))
        line.write_bytes(line.read_bytes().replace(b"hard", b"easy"))
        with self.assertRaisesRegex(ValueError, "does not match its fingerprint"):
            self.store.load(key)
        with self.assertRaisesRegex(ValueError, "collision"):
            self.store.save(body("another focus"))

    def test_requests_without_text_state_are_kept_whole(self):
        for original in ({"questions": {"m": {}}}, {"state": {"a": 1}, "questions": {}}):
            self.assertEqual(self.store.load(self.store.save(original)), original)


class CompactCacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def selector(self):
        return JevSelector(JevSettings(long_context_retry=False), self.root / "jev")

    def request(self, count):
        request = test_judgment_cache.JudgmentCacheTest().request()
        request.allowed_match_ids = [f"candidate-{i}" for i in range(count)]
        source = request.context["candidates"][0]
        request.context["candidates"] = [
            {**source, "selection_id": key, "paragraph_under_consideration": {"full_text": key}}
            for key in request.allowed_match_ids
        ]
        return request

    def test_new_calls_store_the_request_once_and_logs_point_to_it(self):
        selector = self.selector()
        request = self.request(2)

        def http(req, **kwargs):
            return io.BytesIO(json.dumps(answer(json.loads(req.data))).encode())

        with (
            patch("pipeline.providers.jev.load_api_key", return_value="hidden-key"),
            patch("pipeline.providers.jev.urlopen", side_effect=http) as network,
        ):
            first = selector.select(request)
            again = self.selector().select(request)
        self.assertEqual(network.call_count, 2)  # Gate and ranking, then both cached.
        self.assertTrue(all(call["cache_hit"] for call in again["calls"]))
        self.assertEqual(again["target_id"], first["target_id"])
        cache = self.root / "jev"
        for path in [*cache.glob("*.json"), *(cache / "responses").glob("*.json")]:
            record = read_json(path)
            self.assertNotIn("request", record)
            sent = selector.store.load(record["request_fingerprint"])
            self.assertEqual(fingerprint(sent), record["request_fingerprint"])
        self.assertEqual(len(list((cache / "requests").glob("*.json"))), 2)

    def test_an_old_cache_converts_and_replays_without_calls(self):
        selector = self.selector()
        request = self.request(2)
        with patch.object(selector.client, "choose", side_effect=answer):
            first = selector.select(request)
        cache = self.root / "jev"
        # Rewrite the new cache in the old format: every file carries its request inline.
        for path in cache.glob("*.json"):
            record = read_json(path)
            record = {"request": selector.store.load(record.pop("request_fingerprint")), **record}
            write_json(path, record)
        # A long-context answer, a size marker and a call log for a request this run never asks.
        saved = read_json(next(iter(cache.glob("*.json"))))
        old_body = {**saved["request"], "model": "jev-9.9.9"}
        old_answer = {"request": old_body, "response": {**saved["response"], "model": "jev-9.9.9"}}
        write_json(cache / "long-context" / f"{fingerprint(old_body)}.json", old_answer)
        write_json(cache / "too-large" / f"{fingerprint(old_body)}.json", {"request": old_body})
        write_json(
            cache / "responses" / "log.json",
            {"provider": "jev", "request": old_body, "call_index": 1, "response_text": "{}"},
        )
        for folder in ("requests", "text"):
            for path in sorted((cache / folder).rglob("*"), reverse=True):
                path.unlink() if path.is_file() else path.rmdir()

        counts = compact_cache(cache)
        self.assertEqual(counts, {"answers": 3, "markers": 1, "call_logs": 1, "already_compact": 0})
        log = read_json(cache / "responses" / "log.json")
        self.assertEqual(log["request_fingerprint"], fingerprint(old_body))
        self.assertEqual(log["questions"], list(old_body["questions"]))
        self.assertEqual(log["response_text"], "{}")
        self.assertEqual(compact_cache(cache)["already_compact"], 5)

        replay = JevSelector(JevSettings(long_context_retry=False), cache)
        with patch.object(replay.client, "choose", side_effect=AssertionError("paid call")):
            again = replay.select(request)
        self.assertEqual(again["target_id"], first["target_id"])
        self.assertEqual(
            [c["response"] for c in again["calls"]], [c["response"] for c in first["calls"]]
        )


if __name__ == "__main__":
    unittest.main()
