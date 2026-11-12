import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pipeline.files import write_json
from pipeline.providers.contracts import SkillCallPolicy
from pipeline.providers.jev import encode_request
from pipeline.providers.responses import save_response, send_recorded
from pipeline.viewer.trace import Trace, revisions


class RunTraceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = Path(tmp.name).resolve() / "demo"
        self.rev = self.run / "revisions/revision-0001"
        self.prov = self.rev / "provenance"
        self.prov.mkdir(parents=True)

    def journal(self, kind, rows):
        (self.prov / (kind + ".jsonl")).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def test_gate_cache_reciprocal_and_replay_are_separate(self):
        body = {"state": "example", "questions": {"has_match": {}}}
        answer = {"answers": {"has_match": {"noul": 0.8}}}
        fp = hashlib.sha256(encode_request(body)).hexdigest()
        write_json(
            self.run / "cache/jev/responses/receipt.json",
            {"provider": "jev", "request": body, "response_text": json.dumps(answer)},
        )
        aid = "attempt-000001"
        a = dict(
            attempt_id=aid,
            paper_index=2,
            request_key="paper:section_matching:s1",
            stage_id="section_matching",
            output_kind="match",
            model={},
            raw_response={
                "jev": {"calls": [{"fingerprint": fp, "response": answer, "cache_hit": True}]}
            },
            normalized={"target_id": "group"},
            cache_hit=True,
        )
        vote = dict(source_id="s1", target_id="group", attempt_id=aid)
        other = dict(source_id="group", target_id=None, attempt_id="attempt-000002")
        self.journal("attempts", [a])
        write_json(
            self.rev / "stages/0002-section_matching.json",
            {"forward": {"s1": vote}, "reverse": {"group": other}},
        )
        write_json(self.rev / "stages/0002-section_reconciliation.json", {"s1": "singleton"})
        e = dict(
            event_id="event-000001",
            action="node_created",
            paper_index=2,
            node_id="singleton",
            level="section",
            member={"unit_id": "s1"},
        )
        self.journal(
            "events",
            [
                e,
                {
                    **e,
                    "event_id": "event-000002",
                    "action": "member_added",
                    "member": {"unit_id": "s2"},
                },
                dict(
                    event_id="event-000003",
                    action="match_recorded",
                    paper_index=2,
                    attempt_id=aid,
                    source_id="s1",
                    target_id="group",
                ),
            ],
        )
        trace = Trace(self.run, self.rev.name)
        self.assertEqual(revisions(self.run.parent)[0]["status"], "Unfinished")
        result = trace.decision(aid)
        self.assertEqual(result["calls"][0]["sent"], body)
        self.assertTrue(result["calls"][0]["cached"])
        self.assertEqual(result["stage_result"]["opposite"], other)
        self.assertEqual(result["stage_result"]["group"], "singleton")
        self.assertEqual([e["event_id"] for e in result["effects"]], ["event-000003"])
        self.assertEqual(trace.receipt(result["calls"][0]["receipts"][0])["attempts"], [aid])
        self.assertEqual(len(trace.event("event-000001")["affected"]["singleton"]["members"]), 1)
        self.assertEqual(len(trace.event("event-000002")["affected"]["singleton"]["members"]), 2)

    def test_request_capture_and_unlinked_errors(self):
        store = self.run / "cache/responses"
        messages = [{"role": "user", "content": [{"type": "text", "text": "Only once"}]}]
        for provider, field in (("anthropic", "messages"), ("openai", "input")):
            params = {field: messages, "model": "example"}
            save_response(
                store,
                provider=provider,
                response={"id": provider},
                usage={},
                policy=SkillCallPolicy(max_tokens=100),
                schema={},
                messages=messages,
                input_tokens=10,
                request_parameters=params,
            )

        def fail(**kwargs):
            raise TimeoutError("test only")

        with self.assertRaises(TimeoutError):
            send_recorded(fail, store, "anthropic", {"model": "failed", "messages": messages})
        trace = Trace(self.run, self.rev.name)
        details = [trace.receipt(r["id"]) for r in trace.index()["receipts"]]
        self.assertEqual(len(details), 3)
        for d in details:
            self.assertEqual(
                d["sent"]["messages" if d["provider"] == "anthropic" else "input"], messages
            )
            self.assertEqual(d["attempts"], [])
        [error] = [d for d in details if d["error"]]
        self.assertEqual(error["error"], "TimeoutError")
        self.assertIsNone(error["returned"])
