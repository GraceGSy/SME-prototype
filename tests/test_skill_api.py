from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from pipeline.incremental_graph.skill_api import (
    ClaudeSkills,
    SkillBudgetExceeded,
    SkillCallPolicy,
    SkillRef,
    SkillSessionBudget,
    _version_id,
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
    adapter.client = SimpleNamespace(
        beta=SimpleNamespace(messages=messages, files=SimpleNamespace())
    )
    return adapter, messages


SKILL = SkillRef("skills/test", "skill-1", "version-1", "hash-1")
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class SkillApiTest(unittest.TestCase):
    def test_reads_current_and_legacy_skill_version_fields(self) -> None:
        self.assertEqual(
            _version_id(SimpleNamespace(latest_version_id="current"), "latest_version_id", "latest_version"),
            "current",
        )
        self.assertEqual(
            _version_id(SimpleNamespace(version="legacy"), "id", "version"),
            "legacy",
        )

    def test_every_call_applies_low_cost_defaults(self) -> None:
        adapter, messages = _adapter(_Response("response-1", "end_turn", 100, 20))
        policy = SkillCallPolicy(max_tokens=512, max_input_tokens=1_000)

        result = adapter.run_json([SKILL], "prompt", SCHEMA, policy=policy)

        call = messages.calls[0]
        self.assertEqual(call["max_tokens"], 512)
        self.assertEqual(call["thinking"], {"type": "disabled"})
        self.assertEqual(call["output_config"]["effort"], "low")
        self.assertEqual(
            call["output_config"]["task_budget"],
            {"type": "tokens", "total": 20_000},
        )
        self.assertEqual(
            call["context_management"]["edits"][0]["type"],
            "clear_tool_uses_20250919",
        )
        self.assertEqual(result.usage["request_count"], 1)
        self.assertEqual(result.call_policy, policy.as_dict())

    def test_pause_turn_does_not_continue_without_permission(self) -> None:
        adapter, messages = _adapter(_Response("response-1", "pause_turn", 100, 20))
        policy = SkillCallPolicy(max_tokens=512, max_input_tokens=1_000)

        with self.assertRaisesRegex(SkillBudgetExceeded, "continuations are limited to 0"):
            adapter.run_json([SKILL], "prompt", SCHEMA, policy=policy)

        self.assertEqual(len(messages.calls), 1)

    def test_usage_is_aggregated_across_an_explicit_continuation(self) -> None:
        adapter, messages = _adapter(
            _Response("response-1", "pause_turn", 100, 20),
            _Response("response-2", "end_turn", 200, 30),
        )
        policy = SkillCallPolicy(
            max_tokens=512,
            max_input_tokens=1_000,
            max_continuations=1,
        )

        result = adapter.run_json([SKILL], "prompt", SCHEMA, policy=policy)

        self.assertEqual(len(messages.calls), 2)
        self.assertEqual(result.usage["input_tokens"], 300)
        self.assertEqual(result.usage["output_tokens"], 50)
        self.assertEqual(result.usage["continuations"], 1)

    def test_input_usage_limit_fails_closed(self) -> None:
        adapter, _ = _adapter(_Response("response-1", "end_turn", 1_001, 20))
        policy = SkillCallPolicy(max_tokens=512, max_input_tokens=1_000)

        with self.assertRaisesRegex(SkillBudgetExceeded, "1,001 input tokens") as raised:
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

    def test_process_call_limit_stops_before_another_request(self) -> None:
        adapter, messages = _adapter(_Response("response-1", "end_turn", 100, 20))
        adapter.session_budget = SkillSessionBudget(max_api_responses=1)
        adapter.session_usage["api_responses"] = 1

        with self.assertRaisesRegex(SkillBudgetExceeded, "1-response limit"):
            adapter.run_json(
                [SKILL],
                "prompt",
                SCHEMA,
                policy=SkillCallPolicy(max_tokens=512),
            )

        self.assertEqual(messages.calls, [])


if __name__ == "__main__":
    unittest.main()
