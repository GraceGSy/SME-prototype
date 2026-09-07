"""Rescue this HCI experiment only; never imported by runtime code.

Default: offline replay. --execute continues paid, enum-constrained judgments.
Repeated execution preserves revisions and this experiment's completed work.
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
PREVIOUS = ROOT / "runs/hci-first-two-content-20260907-recovered"
DESTINATION = ROOT / "runs/hci-first-two-content-20260907-rescued"
PAPERS = ("abstractexplorer", "corpusstudio")


class ReplayComplete(Exception):
    """Offline replay reached the first request needing a new model response."""


def normalize_hci_target(target, request):
    """Remove a known qualifier only when one eligible candidate is identified."""
    if target is None or target in request.allowed_match_ids:
        return target
    if not isinstance(target, str):
        raise ValueError("Cannot rescue a non-string selection")
    value = target.strip()
    matches = {value} if value in request.allowed_match_ids else set()
    for paper_id in PAPERS:
        for separator in (".", "-", ":", "/"):
            prefix = paper_id + separator
            if not value.startswith(prefix):
                continue
            candidate_id = value[len(prefix) :]
            candidates = [
                candidate
                for candidate in request.context["candidates"]
                if candidate.get(
                    "selection_id", candidate.get("group_id", candidate.get("section_id"))
                )
                == candidate_id
                and candidate.get("paper_id", paper_id) == paper_id
            ]
            if candidate_id in request.allowed_match_ids and len(candidates) == 1:
                matches.add(candidate_id)
    if len(matches) != 1:
        raise ValueError(f"Cannot unambiguously rescue HCI selection: {target!r}")
    return matches.pop()


class RecoveryProvider:
    def __init__(self, live, records, rejected, output, *, execute=False):
        self.live, self.records, self.rejected = live, records, rejected
        self.output, self.execute = output, execute
        self.reused = self.corrected = 0

    def judge(self, request):
        rendered = self.live.render_request(request)
        original_schema = self.live.prompts.render(
            request.prompt_ref, request.context_ref, request.context
        ).schema_hash
        if request.key in self.records:
            row = self.records[request.key]
            if (
                row["context_hash"] != rendered.context_hash
                or row["prompt_hash"] != rendered.prompt_hash
                or row["schema_hash"] not in {rendered.schema_hash, original_schema}
                or row["candidate_ids"] != request.allowed_match_ids
                or row["output_kind"] != request.output_kind
            ):
                raise ValueError(f"Source judgment no longer fits request: {request.key}")
            result = JudgmentResult.model_validate(
                {key: row[key] for key in JudgmentResult.model_fields}
            )
            self.live._validate(request, result.normalized)
            result.cache_hit = True
            self.reused += 1
            return result
        if request.key in self.rejected:
            record = self.rejected[request.key]
            old_request = record["request"]
            if (
                old_request["context"] != request.context
                or old_request["allowed_match_ids"] != request.allowed_match_ids
                or old_request["prompt_ref"] != request.prompt_ref
                or request.output_kind != "match"
            ):
                raise ValueError("Rejected judgment no longer fits current evidence")
            result = JudgmentResult.model_validate(record["result"])
            original = dict(result.normalized)
            target = normalize_hci_target(original["target_id"], request)
            result.normalized = {**original, "target_id": target}
            self.live._validate(request, result.normalized)
            correction = {
                "original": original,
                "corrected": result.normalized,
                "source_fingerprint": result.fingerprint,
                "authorization": "Dataset-specific HCI rescue, 2026-09-07",
            }
            result.fingerprint = hashlib.sha256(
                json.dumps(correction, sort_keys=True).encode()
            ).hexdigest()
            result.model = {**result.model, "id_correction": correction}
            result.cache_hit = True
            self.corrected += 1
            if self.execute:
                write_json(
                    self.output / "corrections" / f"{result.fingerprint}.json",
                    result.model_dump(mode="json"),
                )
            return result
        if not self.execute:
            raise ReplayComplete(request.key)
        return self.live.judge(request)


def run(execute=False):
    state = RunState.model_validate(read_json(SOURCE / "run.json"))
    # One observed paragraph match exhausted 512 tokens; retain the normal default.
    for stage in state.config.stages:
        if stage.id == "paragraph_matching":
            stage.max_tokens = 1024
    inputs = SOURCE / "inputs/revision-0002"
    if directory_hash(inputs) != state.input_sha256["revision-0002"]:
        raise ValueError("Source inputs changed")
    manifest, papers = load_manifest(inputs / "manifest.yaml")
    if tuple(paper.paper_id for paper in papers) != PAPERS:
        raise ValueError("Expected only the two HCI papers")
    paths = [PREVIOUS / "revision/provenance/attempts.jsonl"]
    revisions = sorted((DESTINATION / "revisions").glob("revision-*"))
    if revisions:
        paths.append(revisions[-1] / "provenance/attempts.jsonl")
    records = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            records[row["request_key"]] = row
    if len(records) < 210:
        raise ValueError("Expected all previously completed and recovered judgments")
    rejected = {}
    for root in (PREVIOUS, DESTINATION):
        for path in sorted(
            (root / "cache/rejected").glob("*.json"), key=lambda p: p.stat().st_mtime_ns
        ):
            row = read_json(path)
            rejected[row["request"]["key"]] = row
    with tempfile.TemporaryDirectory() as temporary:
        output = DESTINATION if execute else Path(temporary) / "preview"
        output.mkdir(exist_ok=True)
        if execute:
            if not (output / "inputs").exists():
                shutil.copytree(inputs, output / "inputs")
            if directory_hash(output / "inputs") != directory_hash(inputs):
                raise ValueError("Rescue inputs changed")
        revision = output / "revisions" / f"revision-{len(revisions) + 1:04d}"
        live = AnthropicJudgmentProvider(
            PromptRepository(state.config.prompt_root, state.config.context_root),
            state.config.model,
            output / "cache",
            state.config.skill_root,
        )
        judge = RecoveryProvider(live, records, rejected, output, execute=execute)
        runner = IncrementalGraphRunner(
            state.config, judge, revision, max_granularity=manifest.max_granularity
        )
        if execute:
            write_json(
                revision / "recovery.json",
                {
                    "classification": "rescued mixed-policy diagnostic; not a clean evaluation",
                    "source_run": str(SOURCE),
                    "previous_recovery": str(PREVIOUS),
                    "continuation_policy_sha256": _policy_hash(state.config),
                    "available_prior_judgments": len(records),
                "first_correction_original_basis_available": False,
                "continuation_overrides": {"paragraph_matching.max_tokens": 1024},
                },
            )
        try:
            summary = runner.run(papers)
        except ReplayComplete as boundary:
            if judge.reused != len(records):
                raise ValueError("Replay did not preserve every completed judgment") from boundary
            print(
                f"Offline verified: {judge.reused} reused, {judge.corrected} ID corrections. Next: {boundary}"
            )
        except Exception as error:
            write_json(
                revision / "failure.json", {"type": type(error).__name__, "message": str(error)}
            )
            raise
        else:
            print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    run(parser.parse_args().execute)
