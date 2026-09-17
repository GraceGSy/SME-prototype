"""One-time, offline HCI evidence-contract transition; no model calls or repairs.

Preserves the original run and original judgment provenance. Only cache lookup
keys change after replay verifies identical evidence, candidates, and decisions.
The derivative is a mixed-contract continuation, not a fresh evaluation.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from helpers.usage_budget import ResponseLedger
from pipeline.files import directory_hash, read_json, write_json
from pipeline.incremental_graph.configuration import PromptRepository, load_pipeline_config
from pipeline.incremental_graph.input_data import load_manifest
from pipeline.incremental_graph.llm import AnthropicJudgmentProvider
from pipeline.incremental_graph.models import JudgmentResult
from pipeline.incremental_graph.runner import IncrementalGraphRunner
from pipeline.incremental_graph.runs import DEFAULT_CONFIG, RunState, _policy_hash

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runs/hci-section-medium-thinking-20260917"
DESTINATION = ROOT / "runs/hci-section-medium-excerpts-20260917"
SOURCE_POLICY = "d71e0f1832ced09b46d356bd654d3da39670ed063eac2e7feadd3d87803e847b"
CONTRACT = "pipeline/incremental_graph/prompts/shared/match-evidence.md"


class NeedsPaidJudgment(Exception):
    """Stop the offline replay at the first unfinished request."""


def prepare():
    if DESTINATION.exists():
        raise ValueError("Destination exists; never overwrite a continuation")
    source_hash = directory_hash(SOURCE)
    state = RunState.model_validate(read_json(SOURCE / "run.json"))
    if state.policy_sha256 != SOURCE_POLICY or state.current_revision is not None:
        raise ValueError("Expected the paused, unfinished first pair under the original policy")
    if state.config != load_pipeline_config(DEFAULT_CONFIG):
        raise ValueError("Model settings or pipeline stages changed")
    budget = read_json(SOURCE / "budget.json")
    ledger = ResponseLedger(SOURCE / "cache/responses")
    if not budget["last_call_usage_known"] or budget["authorized_budget_usd"] != 17.64:
        raise ValueError("Usage must be reconciled within the existing authorization")
    if abs(ledger.spent - budget["estimated_token_cost_usd"]) > 1e-9:
        raise ValueError("Saved costs differ from recorded responses")
    ledger.require_headroom(17.64, 3)
    inputs = SOURCE / "inputs" / state.latest_revision
    if directory_hash(inputs) != state.input_sha256[state.latest_revision]:
        raise ValueError("Source inputs changed")
    manifest, papers = load_manifest(inputs / "manifest.yaml")
    rows = {}
    for line in (
        (SOURCE / "revisions" / state.latest_revision / "provenance/attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        row = json.loads(line)
        if row["request_key"] in rows:
            raise ValueError("Duplicate recorded request")
        rows[row["request_key"]] = row
    old_contract = subprocess.check_output(
        ["git", "show", f"6b592fe:{CONTRACT}"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()
    new_contract = (ROOT / CONTRACT).read_text(encoding="utf-8").strip()
    aliases = {}
    reused = set()

    with tempfile.TemporaryDirectory() as temporary:
        live = AnthropicJudgmentProvider(
            PromptRepository(state.config.prompt_root, state.config.context_root),
            state.config.model,
            Path(temporary) / "cache",
            state.config.skill_root,
        )

        class Replay:
            def judge(self, request):
                if request.key not in rows:
                    raise NeedsPaidJudgment(request.key)
                row = rows[request.key]
                rendered = live.render_request(request)
                if (
                    row["context_hash"] != rendered.context_hash
                    or row["schema_hash"] != rendered.schema_hash
                    or row["candidate_ids"] != request.allowed_match_ids
                    or row["output_kind"] != request.output_kind
                    or row["max_tokens"] != request.max_tokens
                    or row["max_input_tokens"] != request.max_input_tokens
                    or row["rendered_system"] != rendered.system.replace(new_contract, old_contract)
                ):
                    raise ValueError(
                        f"Evidence, schema, or role instructions changed: {request.key}"
                    )
                result = JudgmentResult.model_validate(
                    {key: row[key] for key in JudgmentResult.model_fields}
                )
                live._validate(request, result.normalized)
                lookup = live._fingerprint(
                    request, rendered, directory_hash(state.config.skill_root / request.skill_ref)
                )
                result.model["inherited_evidence_contract"] = {
                    "source_run": SOURCE.name,
                    "source_policy_sha256": SOURCE_POLICY,
                    "cache_lookup_fingerprint": lookup,
                }
                result.cache_hit = True
                aliases[lookup] = result.model_dump(mode="json")
                reused.add(request.key)
                return result

        runner = IncrementalGraphRunner(
            state.config,
            Replay(),
            Path(temporary) / "replay",
            max_granularity=manifest.max_granularity,
        )
        try:
            runner.run(papers)
        except NeedsPaidJudgment as boundary:
            next_request = str(boundary)
        else:
            raise ValueError("Expected an unfinished judgment")
    if reused != set(rows):
        raise ValueError("Offline replay did not preserve every recorded judgment")
    if directory_hash(SOURCE) != source_hash:
        raise ValueError("Source run changed during replay")
    shutil.copytree(SOURCE, DESTINATION)
    if directory_hash(DESTINATION) != source_hash:
        raise ValueError("Run copy did not preserve the source")
    state.policy_sha256 = _policy_hash(state.config)
    write_json(
        DESTINATION / "continuation.json",
        {
            "classification": "Mixed evidence-contract continuation; not a fresh evaluation",
            "source_run": str(SOURCE),
            "source_directory_sha256": source_hash,
            "source_policy_sha256": SOURCE_POLICY,
            "continuation_policy_sha256": state.policy_sha256,
            "reused_judgments": len(reused),
            "next_request": next_request,
            "inherited_token_cost_usd": ledger.spent,
            "changes": "Bounded quote-length retries and verified five-word-endpoint excerpts only",
            "original_results": "Preserved original fingerprints, prompts, model metadata and responses",
        },
    )
    for lookup, result in aliases.items():
        write_json(DESTINATION / "cache" / f"{lookup}.json", result)
    write_json(DESTINATION / "run.json", state.model_dump(mode="json"))
    print(f"Verified {len(reused)} inherited judgments; next: {next_request}")
    print(f"Prepared {DESTINATION}; inherited token cost ${ledger.spent:.4f}; no paid calls")


if __name__ == "__main__":
    prepare()
