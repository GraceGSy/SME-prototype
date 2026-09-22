"""Exercise the real SDK's HTTP payloads without spending API credits."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import InternalServerError, OpenAI

from pipeline.providers.contracts import (
    SkillBudgetExceeded,
    SkillCallPolicy,
    SkillRef,
    SkillSessionBudget,
    StructuredOutputValidationError,
)
from pipeline.providers.openai import OpenAISkills

SKILL = SkillRef("skills/match-role", "skill_test", "1", "a" * 64)
SCHEMA = {
    "type": "object",
    "properties": {"question": {"type": "string", "minLength": 1, "maxLength": 8}},
    "required": ["question"],
    "additionalProperties": False,
}


def response(value=None, *, status="completed", usage=None, output=None):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "gpt-5.6-sol",
        "status": status,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "output": output
        if output is not None
        else [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(value), "annotations": []}],
            }
        ],
        "usage": usage
        or {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 60, "cache_write_tokens": 20},
            "output_tokens": 10,
            "output_tokens_details": {"reasoning_tokens": 4},
            "total_tokens": 110,
        },
    }


class OpenAIProviderTest(unittest.TestCase):
    def adapter(self, root, responses):
        requests = []

        def handle(request):
            requests.append(request)
            payload = responses.pop(0)
            if isinstance(payload, httpx.Response):
                return payload
            return httpx.Response(200, json=payload)

        client = OpenAI(
            api_key="offline-test",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        )
        self.addCleanup(client.close)
        with (
            patch("pipeline.providers.openai.load_api_key", return_value="offline-test"),
            patch("openai.OpenAI", return_value=client),
        ):
            adapter = OpenAISkills(
                root, root / "registry.json", "gpt-5.6-sol", response_dir=root / "responses"
            )
        return adapter, requests

    def test_native_skills_cache_prefixes_and_accounting_survive_sdk_serialization(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            adapter, requests = self.adapter(root, [response({"question": "Why?"})])
            result = adapter.run_json(
                [SKILL],
                "focus",
                SCHEMA,
                policy=SkillCallPolicy(max_tokens=512, thinking="adaptive", effort="medium"),
                cacheable_prompt="instructions and examples",
                cacheable_context="candidate pool",
            )
            body = json.loads(requests[0].content)
            self.assertEqual(len(requests), 1)
            self.assertEqual(body["reasoning"], {"effort": "medium"})
            self.assertEqual(body["max_output_tokens"], 512)
            self.assertEqual(body["truncation"], "disabled")
            environment = body["tools"][0]["environment"]
            self.assertEqual(
                environment["skills"],
                [{"type": "skill_reference", "skill_id": "skill_test", "version": "1"}],
            )
            self.assertEqual(environment["type"], "container_auto")
            blocks = body["input"][0]["content"]
            self.assertEqual(
                [block["text"] for block in blocks],
                ["instructions and examples", "candidate pool", "focus"],
            )
            self.assertTrue(all("prompt_cache_breakpoint" in block for block in blocks[:2]))
            self.assertNotIn("prompt_cache_breakpoint", blocks[2])
            self.assertEqual(body["prompt_cache_options"], {"mode": "explicit", "ttl": "30m"})
            self.assertTrue(body["text"]["format"]["strict"])
            self.assertNotIn(
                "maxLength", body["text"]["format"]["schema"]["properties"]["question"]
            )
            self.assertEqual(result.value, {"question": "Why?"})
            self.assertEqual(result.usage["session"]["input_tokens"], 100)
            self.assertEqual(result.usage["input_tokens_details"]["cached_tokens"], 60)
            self.assertEqual(result.usage["input_tokens_details"]["cache_write_tokens"], 20)
            saved = json.loads(next((root / "responses").glob("*.json")).read_text())
            self.assertEqual(saved["provider"], "openai")
            self.assertEqual(saved["schema"], SCHEMA)

    def test_rejects_bad_output_without_repair_and_preserves_every_paid_response(self):
        cases = [
            (response({"question": "too long a quote"}), StructuredOutputValidationError),
            (response({"question": "Why?"}, status="incomplete"), SkillBudgetExceeded),
            (
                response(
                    output=[
                        {
                            "id": "m",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [{"type": "refusal", "refusal": "No"}],
                        }
                    ]
                ),
                RuntimeError,
            ),
            (response({"question": "Why?"}), SkillBudgetExceeded),
        ]
        for index, (payload, expected) in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                adapter, requests = self.adapter(root, [payload])
                with self.assertRaises(expected):
                    adapter.run_json(
                        [SKILL],
                        "focus",
                        SCHEMA,
                        policy=SkillCallPolicy(
                            max_tokens=512, max_input_tokens=99 if index == 3 else 200
                        ),
                    )
                self.assertEqual(len(requests), 1)
                self.assertEqual(len(list((root / "responses").glob("*.json"))), 1)

    def test_attachment_array_contract_and_cleanup_on_success_and_failure(self):
        schema = {"type": "array", "items": SCHEMA, "minItems": 1}
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = root / "source.txt"
                source.write_text("source evidence")
                adapter, requests = self.adapter(
                    root,
                    [
                        {
                            "id": "file_test",
                            "object": "file",
                            "bytes": 15,
                            "created_at": 1,
                            "filename": "source.txt",
                            "purpose": "user_data",
                        },
                        response(
                            {"result": [{"question": "Why?" if valid else "overlong question"}]}
                        ),
                        {"id": "file_test", "object": "file", "deleted": True},
                    ],
                )
                if valid:
                    result = adapter.run_json_file(
                        SKILL, "extract", source, schema, policy=SkillCallPolicy(max_tokens=512)
                    )
                    self.assertEqual(result.value, [{"question": "Why?"}])
                else:
                    with self.assertRaises(StructuredOutputValidationError):
                        adapter.run_json_file(
                            SKILL, "extract", source, schema, policy=SkillCallPolicy(max_tokens=512)
                        )
                body = json.loads(requests[1].content)
                self.assertEqual(body["tools"][0]["environment"]["file_ids"], ["file_test"])
                self.assertEqual(body["text"]["format"]["schema"]["required"], ["result"])
                self.assertEqual(requests[-1].method, "DELETE")
                self.assertEqual(requests[-1].url.path, "/v1/files/file_test")

    def test_registration_reuses_unchanged_bundle_and_versions_changed_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "skills" / "match-role"
            folder.mkdir(parents=True)
            manifest = folder / "SKILL.md"
            manifest.write_text("---\nname: match-role\ndescription: Match roles\n---\nUse roles.")
            adapter, requests = self.adapter(
                root,
                [
                    {
                        "id": "skill_test",
                        "default_version": "1",
                        "latest_version": "1",
                        "object": "skill",
                        "name": "match-role",
                        "description": "Match roles",
                        "created_at": 1,
                    },
                    {
                        "id": "sv_test",
                        "skill_id": "skill_test",
                        "version": "2",
                        "object": "skill.version",
                        "name": "match-role",
                        "description": "Match roles",
                        "created_at": 1,
                    },
                ],
            )
            first = adapter.register(folder)
            self.assertEqual(adapter.register(folder), first)
            self.assertEqual(len(requests), 1)
            self.assertIn(b"match-role/SKILL.md", requests[0].content)
            self.assertIn(manifest.read_bytes(), requests[0].content)
            manifest.write_text(manifest.read_text() + "\nDo not match by topic alone.")
            second = adapter.register(folder)
            self.assertEqual(second.version, "2")
            self.assertNotEqual(first.source_sha256, second.source_sha256)
            self.assertEqual(requests[1].url.path, "/v1/skills/skill_test/versions")

    def test_local_limits_stop_before_any_upload_or_api_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            adapter, requests = self.adapter(root, [])
            with self.assertRaises(SkillBudgetExceeded):
                adapter.run_json(
                    [SKILL],
                    "too long",
                    SCHEMA,
                    policy=SkillCallPolicy(max_tokens=512, max_prompt_characters=2),
                )
            source = root / "source.txt"
            source.write_text("too large")
            with self.assertRaises(SkillBudgetExceeded):
                adapter.run_json_file(
                    SKILL,
                    "extract",
                    source,
                    SCHEMA,
                    policy=SkillCallPolicy(max_tokens=512, max_attachment_bytes=2),
                )
            adapter.session_budget = SkillSessionBudget(max_api_responses=1)
            adapter.session_usage["api_responses"] = 1
            with self.assertRaises(SkillBudgetExceeded):
                adapter.run_json([SKILL], "focus", SCHEMA, policy=SkillCallPolicy(max_tokens=512))
            self.assertEqual(requests, [])

    def test_sdk_does_not_implicitly_repeat_failed_paid_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            adapter, requests = self.adapter(
                Path(temp),
                [
                    httpx.Response(
                        500, json={"error": {"message": "Internal error", "type": "server_error"}}
                    )
                ],
            )
            with self.assertRaises(InternalServerError):
                adapter.run_json([SKILL], "focus", SCHEMA, policy=SkillCallPolicy(max_tokens=512))
            self.assertEqual(len(requests), 1)
