"""Recover one final post-tool JSON answer, offline; never normalize runtime output."""

import argparse
import json
from unittest.mock import patch

from jsonschema import Draft202012Validator

from helpers.extend_hci_20260907 import OUTPUT, run
from helpers.recover_hci_20260907 import RecoveryProvider, ReplayComplete
from pipeline.files import directory_hash, read_json, write_json
from pipeline.incremental_graph.models import JudgmentResult
from pipeline.providers.anthropic import _prompt_content

SOURCE = OUTPUT / "cache/responses/6b7ae2c38d134944849f64c604a42f83.json"


def repair(execute=False):
    saved = read_json(SOURCE)
    original = RecoveryProvider.judge

    def inspect(provider, request):
        try:
            return original(provider, request)
        except ReplayComplete:
            rendered = provider.live.render_request(request)
            expected = [
                {
                    "role": "user",
                    "content": _prompt_content(
                        rendered.user, rendered.system, rendered.cacheable_context
                    ),
                }
            ]
            if saved["messages"] != expected or saved["schema"] != rendered.schema:
                raise ValueError("Saved response does not match the exact next request")
            response = saved["response"]
            blocks = response["content"]
            if response["stop_reason"] != "end_turn" or [b["type"] for b in blocks] != [
                "server_tool_use",
                "text_editor_code_execution_tool_result",
                "text",
                "server_tool_use",
                "bash_code_execution_tool_result",
                "text",
            ]:
                raise ValueError("Unexpected response structure; do not guess the final answer")
            value = json.loads(blocks[-1]["text"])
            Draft202012Validator(rendered.schema).validate(value)
            provider.live._validate(request, value)
            fingerprint = provider.live._fingerprint(
                request, rendered, directory_hash(provider.live.skill_root / request.skill_ref)
            )
            result = JudgmentResult(
                fingerprint=fingerprint,
                normalized=value,
                raw_response=response,
                rendered_system=rendered.system,
                rendered_user="\n\n".join(
                    x for x in (rendered.cacheable_context, rendered.user) if x
                ),
                prompt_hash=rendered.prompt_hash,
                context_hash=rendered.context_hash,
                schema_hash=rendered.schema_hash,
                model={
                    **provider.live.model.model_dump(mode="json"),
                    "recovery": {
                        "source": str(SOURCE),
                        "method": "final text block after last tool result",
                        "discarded_intermediate_answer": json.loads(blocks[2]["text"]),
                        "final_answer_unchanged": True,
                    },
                },
            )
            destination = OUTPUT / "cache" / f"{fingerprint}.json"
            if execute:
                if destination.exists():
                    raise ValueError("Refusing to overwrite an existing judgment")
                write_json(destination, result.model_dump(mode="json"))
                write_json(
                    OUTPUT / "repairs/final-json-20260907.json",
                    {
                        "request_key": request.key,
                        "source": str(SOURCE),
                        "cache_path": str(destination),
                        "normalized": value,
                        "repair": result.model["recovery"],
                    },
                )
            print(f"{'Saved' if execute else 'Validated'} final JSON for {request.key}")
            raise

    with patch.object(RecoveryProvider, "judge", inspect):
        run(execute=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    repair(parser.parse_args().execute)
