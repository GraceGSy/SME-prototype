"""One authorized HCI ID correction; never imported by the normal graph pipeline.

Default: offline replay through the correction. --execute continues paid judgments.
The output is explicitly mixed-policy diagnostic data, not a clean experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from pipeline.files import directory_hash, read_json, write_json
from pipeline.incremental_graph.configuration import PromptRepository
from pipeline.incremental_graph.input_data import load_manifest
from pipeline.incremental_graph.llm import AnthropicJudgmentProvider
from pipeline.incremental_graph.models import JudgmentResult
from pipeline.incremental_graph.runner import IncrementalGraphRunner
from pipeline.incremental_graph.runs import RunState, _policy_hash

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runs/hci-first-two-content-20260907"
DESTINATION = ROOT / "runs/hci-first-two-content-20260907-recovered"
REVISION = "revision-0002"
FAILED_KEY = "corpusstudio:section_matching:group_to_new:section-group-264d31b73b39"
ORIGINAL_ID = "corpusstudio-s0003"
CORRECTED_ID = "s0003"


class ReplayComplete(Exception):
    """Offline replay reached the first request needing a new model response."""


class RecoveryProvider:
    def __init__(self, live, records, failure, *, execute=False):
        self.live = live
        self.records = {row["request_key"]: row for row in records}
        if len(self.records) != len(records):
            raise ValueError("Duplicate source request keys")
        self.failure = failure
        self.execute = execute
        self.reused = 0
        self.corrected = 0

    def judge(self, request):
        rendered = self.live.prompts.render(
            request.prompt_ref, request.context_ref, request.context
        )
        if request.key in self.records:
            row = self.records[request.key]
            if (
                row["context_hash"] != rendered.context_hash
                or row["prompt_hash"] != rendered.prompt_hash
                or row["schema_hash"] != rendered.schema_hash
                or row["candidate_ids"] != request.allowed_match_ids
                or row["output_kind"] != request.output_kind
            ):
                raise ValueError(f"Source judgment no longer fits request: {request.key}")
            result = JudgmentResult.model_validate(
                {key: row[key] for key in JudgmentResult.model_fields}
            )
            self.live._validate(request, result.normalized)
            result.cache_hit = True
            result.model = {
                **result.model,
                "recovery_source": str(SOURCE / "revisions" / REVISION),
                "recovery_source_attempt": row["attempt_id"],
            }
            self.reused += 1
            return result
        if request.key == FAILED_KEY:
            if (
                self.failure["type"] != "JudgmentError"
                or not self.failure["message"].startswith(
                    f"{FAILED_KEY} selected '{ORIGINAL_ID}'; allowed values are "
                )
                or request.output_kind != "match"
                or CORRECTED_ID not in request.allowed_match_ids
                or sum(
                    candidate.get("section_id") == CORRECTED_ID
                    and candidate.get("paper_id") == "corpusstudio"
                    for candidate in request.context["candidates"]
                )
                != 1
            ):
                raise ValueError("This request does not support the authorized exact correction")
            evidence = {
                "source": "user_authorized_one_time_id_correction",
                "source_failure": self.failure,
                "original_target_id": ORIGINAL_ID,
                "corrected_target_id": CORRECTED_ID,
                "original_basis_available": False,
                "original_raw_response_available": False,
                "context_hash": rendered.context_hash,
            }
            value = {
                "target_id": CORRECTED_ID,
                "basis": (
                    "User-authorized ID-only recovery: corpusstudio-s0003 -> s0003. "
                    "The original model rationale was not retained; this is not a "
                    "reconstructed semantic justification."
                ),
            }
            self.live._validate(request, value)
            self.corrected += 1
            result = JudgmentResult(
                fingerprint=hashlib.sha256(
                    json.dumps(evidence, sort_keys=True).encode()
                ).hexdigest(),
                normalized=value,
                raw_response=evidence,
                rendered_system=rendered.system,
                rendered_user="\n\n".join(
                    block for block in (rendered.cacheable_context, rendered.user) if block
                ),
                prompt_hash=rendered.prompt_hash,
                context_hash=rendered.context_hash,
                schema_hash=rendered.schema_hash,
                model={"provider": "manual_recovery", "name": "authorized_id_correction"},
                cache_hit=True,
            )
            if self.execute:
                write_json(DESTINATION / "correction.json", result.model_dump(mode="json"))
            return result
        if not self.execute:
            raise ReplayComplete(request.key)
        return self.live.judge(request)


def run(execute=False):
    state = RunState.model_validate(read_json(SOURCE / "run.json"))
    inputs = SOURCE / "inputs" / REVISION
    if directory_hash(inputs) != state.input_sha256[REVISION]:
        raise ValueError("Source inputs changed")
    manifest, papers = load_manifest(inputs / "manifest.yaml")
    if [paper.paper_id for paper in papers] != ["abstractexplorer", "corpusstudio"]:
        raise ValueError("Expected only the two HCI papers")
    source_revision = SOURCE / "revisions" / REVISION
    records = [
        json.loads(line)
        for line in (source_revision / "provenance/attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    if len(records) != 206:
        raise ValueError("Expected the original 206 completed judgments")
    failure = read_json(source_revision / "failure.json")
    with tempfile.TemporaryDirectory() as temporary:
        output = DESTINATION if execute else Path(temporary) / "preview"
        output.mkdir(exist_ok=False)
        live = AnthropicJudgmentProvider(
            PromptRepository(state.config.prompt_root, state.config.context_root),
            state.config.model,
            output / "cache",
            state.config.skill_root,
        )
        judge = RecoveryProvider(live, records, failure, execute=execute)
        if execute:
            shutil.copytree(inputs, output / "inputs")
            write_json(
                output / "recovery.json",
                {
                    "classification": "mixed-policy diagnostic; not a clean evaluation",
                    "source_run": str(SOURCE),
                    "source_revision": REVISION,
                    "source_policy_sha256": state.policy_sha256,
                    "continuation_policy_sha256": _policy_hash(state.config),
                    "reused_judgments": 206,
                    "manual_id_corrections": 1,
                    "original_basis_available": False,
                },
            )
        runner = IncrementalGraphRunner(
            state.config, judge, output / "revision", max_granularity=manifest.max_granularity
        )
        try:
            summary = runner.run(papers)
        except ReplayComplete as boundary:
            if (judge.reused, judge.corrected) != (206, 1):
                raise ValueError("Replay did not preserve every completed judgment") from boundary
            print(f"Offline verified: 206 reused, 1 exact correction. Next: {boundary}")
        except Exception as error:
            write_json(
                output / "failure.json", {"type": type(error).__name__, "message": str(error)}
            )
            raise
        else:
            write_json(output / "summary.json", summary)
            print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    run(parser.parse_args().execute)
