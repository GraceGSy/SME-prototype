import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.incremental_graph.configuration import load_pipeline_config
from pipeline.llm.client import (
    CACHEABLE_SYSTEM,
    MESSAGE_BETAS,
    ClaudeSkills,
    SkillBudgetExceeded,
    SkillCallPolicy,
    SkillRef,
    SkillSessionBudget,
    _credential_registry,
)


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.value = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens_details": {"thinking_tokens": 0},
            "server_tool_use": {"code_execution_requests": 1},
        }

    def model_dump(self, *, mode: str) -> dict:
        return self.value


class _Response:
    def __init__(
        self,
        response_id: str,
        stop_reason: str,
        input_tokens: int,
        output_tokens: int,
        text: str = '{"answer": "ok"}',
    ) -> None:
        self.id = response_id
        self.stop_reason = stop_reason
        self.usage = _Usage(input_tokens, output_tokens)
        self.content = [SimpleNamespace(type="text", text=text)]
        self.container = SimpleNamespace(id="container-1")

    def model_dump(self, *, mode: str) -> dict:
        return {"id": self.id, "stop_reason": self.stop_reason}


class _Messages:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs) -> _Response:
        self.calls.append(kwargs)
        return self.responses.pop(0)


class _Files:
    def __init__(self) -> None:
        self.uploads: list[dict] = []
        self.deletions: list[tuple[str, list[str]]] = []

    def upload(self, **kwargs) -> SimpleNamespace:
        self.uploads.append(kwargs)
        return SimpleNamespace(id="file-1")

    def delete(self, file_id: str, *, betas: list[str]) -> None:
        self.deletions.append((file_id, betas))


def _adapter(*responses: _Response) -> tuple[ClaudeSkills, _Messages]:
    messages = _Messages(list(responses))
    adapter = object.__new__(ClaudeSkills)
    adapter.model = "claude-sonnet-5"
    adapter.session_budget = SkillSessionBudget()
    adapter.session_usage = {
        "api_responses": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    adapter.client = SimpleNamespace(beta=SimpleNamespace(messages=messages, files=_Files()))
    return adapter, messages


SKILL = SkillRef("skills/test", "skill-1", "version-1", "hash-1")
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class SkillApiTest(unittest.TestCase):
    def test_final_answer_after_tool_result_excludes_intermediate_json(self):
        response = _Response("final", "end_turn", 100, 50)
        response.content = [
            SimpleNamespace(type="text", text='{"answer":"intermediate"}'),
            SimpleNamespace(type="server_tool_use"),
            SimpleNamespace(type="bash_code_execution_tool_result"),
            SimpleNamespace(type="text", text='{"answer":"final"}'),
        ]
        adapter, _ = _adapter(response)
        result = adapter.run_json([SKILL], "input", SCHEMA, policy=SkillCallPolicy(max_tokens=100))
        self.assertEqual(result.value, {"answer": "final"})

    def test_two_final_json_objects_still_rejected(self):
        response = _Response("ambiguous", "end_turn", 100, 50)
        response.content.append(SimpleNamespace(type="text", text='{"answer":"other"}'))
        adapter, _ = _adapter(response)
        with self.assertRaises(json.JSONDecodeError):
            adapter.run_json([SKILL], "input", SCHEMA, policy=SkillCallPolicy(max_tokens=100))

    def test_response_retained_before_usage_rejection(self):
        adapter, _ = _adapter(_Response("paid-response", "end_turn", 201, 10))
        with tempfile.TemporaryDirectory() as directory:
            adapter.response_dir = Path(directory)
            with self.assertRaises(SkillBudgetExceeded):
                adapter.run_json(
                    [SKILL],
                    "input",
                    SCHEMA,
                    policy=SkillCallPolicy(max_tokens=100, max_input_tokens=200),
                )
            records = list(Path(directory).glob("*.json"))
            self.assertEqual(len(records), 1)
            record = json.loads(records[0].read_text())
            self.assertEqual(record["response"]["id"], "paid-response")
            self.assertEqual(record["usage"]["input_tokens"], 201)
            self.assertGreater(record["request_text_characters"], 0)

    def test_native_skill_registration_is_reused_until_source_or_account_changes(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("pipeline.llm.client.load_api_key", return_value="test-account-one") as key,
            patch("anthropic.Anthropic") as api,
        ):
            root = Path(directory)
            skill = root / "skills" / "test"
            skill.mkdir(parents=True)
            instructions = skill / "SKILL.md"
            instructions.write_text("---\nname: test\ndescription: Test\n---\nInstructions")
            registry = root / "_cache" / "skill-registry.json"
            remote = api.return_value.beta.skills
            remote.create.return_value = SimpleNamespace(id="skill-1", latest_version_id="v1")
            remote.versions.create.return_value = SimpleNamespace(id="v2")

            first = ClaudeSkills(root, registry, "model").register(skill)
            second = ClaudeSkills(root, registry, "model").register(skill)
            self.assertEqual(first, second)
            self.assertEqual(remote.create.call_count, 1)
            self.assertNotIn("betas", remote.create.call_args.kwargs)
            remote.versions.create.assert_not_called()

            instructions.write_text("---\nname: test\ndescription: Test\n---\nChanged instructions")
            updated = ClaudeSkills(root, registry, "model").register(skill)
            self.assertEqual(updated.version, "v2")
            self.assertNotEqual(first.source_sha256, updated.source_sha256)
            self.assertEqual(remote.versions.create.call_count, 1)
            self.assertNotIn("betas", remote.versions.create.call_args.kwargs)

            key.return_value = "test-account-two"
            ClaudeSkills(root, registry, "model").register(skill)
            self.assertEqual(remote.create.call_count, 2)

    def test_native_skill_caches_candidate_prefix_before_changing_focus(self):
        adapter, messages = _adapter(_Response("direct", "end_turn", 100, 20))
        adapter.run_json(
            [SKILL],
            "Focus",
            SCHEMA,
            policy=SkillCallPolicy(max_tokens=512),
            cacheable_prompt="Task instructions",
            cacheable_context="Candidate corpus",
        )
        call = messages.calls[0]
        self.assertEqual(call["container"], {"skills": [SKILL.api_value()]})
        self.assertEqual(call["tools"][0]["name"], "code_execution")
        self.assertEqual(call["betas"], MESSAGE_BETAS)
        self.assertEqual(call["system"], CACHEABLE_SYSTEM)
        content = call["messages"][0]["content"]
        self.assertEqual(content[0]["text"], "Task instructions")
        self.assertEqual(content[0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(content[1]["text"], "Candidate corpus")
        self.assertEqual(content[1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(content[2], {"type": "text", "text": "Focus"})

    def test_cached_candidate_text_still_counts_toward_prompt_limit(self):
        adapter, messages = _adapter()
        with self.assertRaises(SkillBudgetExceeded):
            adapter.run_json(
                [SKILL],
                "focus",
                SCHEMA,
                policy=SkillCallPolicy(max_tokens=512, max_prompt_characters=10),
                cacheable_prompt="rules",
                cacheable_context="large pool",
            )
        self.assertEqual(messages.calls, [])

    def test_skill_registry_is_scoped_without_storing_api_keys(self) -> None:
        state = {"schema_version": 1, "accounts": {}}
        document, first_registry = _credential_registry(state, "key-one")
        first_registry["skills/test"] = {
            "skill_id": "skill-1",
            "version": "v1",
            "source_sha256": "0" * 64,
        }
        _, second_registry = _credential_registry(document, "key-two")
        self.assertEqual(second_registry, {})
        self.assertNotIn("key-one", str(document))
        self.assertNotIn("key-two", str(document))

    def test_registry_rejects_legacy_and_malformed_shapes(self) -> None:
        for state in (
            {},
            {"skills/test": {"skill_id": "legacy"}},
            {"schema_version": "1", "accounts": {}},
            {"schema_version": 1, "accounts": {}, "extra": True},
            {"schema_version": 1, "accounts": {"not-a-hash": {}}},
        ):
            with self.subTest(state=state), self.assertRaises(ValueError):
                _credential_registry(state, "key")

    def test_transport_rejects_malformed_json_instead_of_repairing_it(self) -> None:
        for text in (
            '```json\\n{"answer":"ok"}\\n```',
            '{"answer": 7}',
            '{"answer":"ok", "extra":true}',
        ):
            adapter, messages = _adapter(_Response("response-1", "end_turn", 100, 20, text=text))
            with self.subTest(text=text), self.assertRaises(ValueError):
                adapter.run_json([SKILL], "prompt", SCHEMA, policy=SkillCallPolicy(max_tokens=512))
            self.assertEqual(len(messages.calls), 1)

    def test_exhausted_token_budget_blocks_the_next_call(self) -> None:
        adapter, messages = _adapter(_Response("unused", "end_turn", 1, 1))
        adapter.session_usage["input_tokens"] = adapter.session_budget.max_input_tokens
        with self.assertRaises(SkillBudgetExceeded):
            adapter.run_json([SKILL], "prompt", SCHEMA, policy=SkillCallPolicy(max_tokens=512))
        self.assertEqual(messages.calls, [])

    def test_every_call_applies_low_cost_defaults(self) -> None:
        self.assertNotIn("skills-2025-10-02", MESSAGE_BETAS)
        adapter, messages = _adapter(_Response("response-1", "end_turn", 100, 20))
        policy = SkillCallPolicy(max_tokens=512, max_input_tokens=1_000)

        result = adapter.run_json([SKILL], "prompt", SCHEMA, policy=policy)

        call = messages.calls[0]
        self.assertEqual(call["max_tokens"], 512)
        self.assertEqual(call["thinking"], {"type": "disabled"})
        self.assertEqual(call["output_config"]["effort"], "low")
        self.assertNotIn("task_budget", call["output_config"])
        self.assertNotIn("task-budgets-2026-03-13", MESSAGE_BETAS)
        self.assertEqual(call["system"], CACHEABLE_SYSTEM)
        self.assertEqual(
            call["system"][-1]["cache_control"],
            {"type": "ephemeral"},
        )
        self.assertNotIn("cache_control", call["tools"][-1])
        self.assertEqual(
            call["messages"],
            [{"role": "user", "content": [{"type": "text", "text": "prompt"}]}],
        )
        self.assertEqual(
            call["context_management"]["edits"][0]["type"],
            "clear_tool_uses_20250919",
        )
        self.assertEqual(result.usage["request_count"], 1)
        self.assertEqual(result.call_policy, policy.as_dict())

    def test_graph_config_sends_medium_adaptive_thinking_with_output_room(self) -> None:
        config = load_pipeline_config(
            Path(__file__).resolve().parents[1]
            / "pipeline/incremental_graph/configs/incremental-v1.yaml"
        )
        self.assertEqual(config.model.name, "claude-sonnet-5")
        for stage in config.stages:
            if not stage.skill:
                continue
            with self.subTest(stage=stage.id):
                adapter, messages = _adapter(_Response("response-1", "end_turn", 100, 20))
                adapter.model = config.model.name
                policy = SkillCallPolicy(
                    max_tokens=stage.max_tokens or config.model.max_tokens,
                    effort=config.model.effort,
                    thinking=config.model.thinking,
                )
                adapter.run_json([SKILL], "prompt", SCHEMA, policy=policy)
                call = messages.calls[0]
                self.assertEqual(call["model"], "claude-sonnet-5")
                self.assertEqual(call["thinking"], {"type": "adaptive"})
                self.assertEqual(call["output_config"]["effort"], "medium")
                expected_tokens = 2048 if stage.skill == "generate-question" else 4096
                self.assertEqual(call["max_tokens"], expected_tokens)

    def test_cacheable_instructions_precede_dynamic_input_in_one_turn(self) -> None:
        adapter, messages = _adapter(_Response("response-1", "end_turn", 100, 20))

        adapter.run_json(
            [SKILL],
            "dynamic input",
            SCHEMA,
            policy=SkillCallPolicy(max_tokens=512),
            cacheable_prompt="stable instructions",
        )

        content = messages.calls[0]["messages"][0]["content"]
        self.assertEqual(len(messages.calls), 1)
        self.assertEqual(content[0]["text"], "stable instructions")
        self.assertEqual(content[0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(content[1], {"type": "text", "text": "dynamic input"})

    def test_pause_turn_never_creates_a_second_request(self) -> None:
        adapter, messages = _adapter(
            _Response("response-1", "pause_turn", 100, 20),
            _Response("response-2", "end_turn", 200, 30),
        )
        policy = SkillCallPolicy(max_tokens=512, max_input_tokens=1_000)

        with self.assertRaisesRegex(SkillBudgetExceeded, "never sends a follow-up turn"):
            adapter.run_json([SKILL], "prompt", SCHEMA, policy=policy)

        self.assertEqual(len(messages.calls), 1)
        self.assertEqual(len(messages.responses), 1)

    def test_input_usage_limit_fails_closed(self) -> None:
        adapter, _ = _adapter(_Response("response-1", "end_turn", 1_001, 20))
        policy = SkillCallPolicy(max_tokens=512, max_input_tokens=1_000)

        with self.assertRaisesRegex(
            SkillBudgetExceeded, "1,001 aggregate input-usage tokens"
        ) as raised:
            adapter.run_json([SKILL], "prompt", SCHEMA, policy=policy)

        self.assertEqual(raised.exception.response_id, "response-1")
        self.assertEqual(raised.exception.usage["input_tokens"], 1_001)

    def test_attachment_limit_is_checked_before_upload(self) -> None:
        adapter, _ = _adapter()
        policy = SkillCallPolicy(max_tokens=512, max_attachment_bytes=4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.txt"
            path.write_text("12345", encoding="utf-8")

            with self.assertRaisesRegex(SkillBudgetExceeded, "configured maximum is 4"):
                adapter.run_json_file(SKILL, "prompt", path, SCHEMA, policy=policy)

    def test_uploaded_file_is_deleted_after_single_request(self) -> None:
        adapter, messages = _adapter(_Response("response-1", "end_turn", 100, 20))
        policy = SkillCallPolicy(max_tokens=512, max_attachment_bytes=100)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.txt"
            path.write_text("source", encoding="utf-8")

            result = adapter.run_json_file(
                SKILL,
                "dynamic input",
                path,
                SCHEMA,
                policy=policy,
                cacheable_prompt="stable instructions",
            )

        files = adapter.client.beta.files
        self.assertEqual(result.usage["request_count"], 1)
        self.assertEqual(len(messages.calls), 1)
        self.assertEqual(len(files.uploads), 1)
        self.assertEqual(files.deletions, [("file-1", ["files-api-2025-04-14"])])
        content = messages.calls[0]["messages"][0]["content"]
        self.assertEqual(content[0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(content[-1], {"type": "container_upload", "file_id": "file-1"})

    def test_process_call_limit_stops_before_another_request(self) -> None:
        adapter, messages = _adapter(_Response("response-1", "end_turn", 100, 20))
        adapter.session_budget = SkillSessionBudget(max_api_responses=1)
        adapter.session_usage["api_responses"] = 1

        with self.assertRaisesRegex(SkillBudgetExceeded, "response or observed-token limit"):
            adapter.run_json(
                [SKILL],
                "prompt",
                SCHEMA,
                policy=SkillCallPolicy(max_tokens=512),
            )

        self.assertEqual(messages.calls, [])


if __name__ == "__main__":
    unittest.main()
