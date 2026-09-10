"""Offline legal capacity scenarios through the unchanged graph runner.

Ordinal-based fake judgments are ONLY workload probes, never semantic results.
The real runner handles subsections, reciprocity and singleton checks. All
artifacts are temporary; API client construction fails closed. Costs use saved
HCI usage, not a claim about future matching quality or a spending upper bound.
"""

import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

from helpers.usage_budget import token_cost
from pipeline.document import QUESTION_FIELD
from pipeline.files import directory_hash, read_json, write_json
from pipeline.incremental_graph.configuration import PromptRepository, load_pipeline_config
from pipeline.incremental_graph.input_data import load_manifest
from pipeline.incremental_graph.llm import AnthropicJudgmentProvider
from pipeline.incremental_graph.models import JudgmentResult
from pipeline.incremental_graph.runner import IncrementalGraphRunner
from pipeline.incremental_graph.runs import DEFAULT_CONFIG, RunState, _policy_hash
from pipeline.llm.client import ClaudeSkills

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "datasets/legal/opinions.manifest.yaml"
HCI = ROOT / "runs/hci-concise-fresh-20260907"
QUESTION = (
    "What purpose does this passage serve in developing and supporting the court's reasoning?"
)


def hci_calibration():
    totals = defaultdict(Counter)
    seen = set()
    for path in (HCI / "cache").glob("*.json"):
        item = read_json(path)
        response = item["raw_response"]
        if response["id"] in seen:
            continue
        seen.add(response["id"])
        kind = "match" if "target_id" in item["normalized"] else "question"
        usage = response["usage"]
        input_cost = token_cost({**usage, "output_tokens": 0})
        totals[kind].update(
            {
                "calls": 1,
                "characters": len(item["rendered_system"]) + len(item["rendered_user"]),
                "input_tokens": sum(
                    usage.get(k, 0) or 0
                    for k in (
                        "input_tokens",
                        "cache_creation_input_tokens",
                        "cache_read_input_tokens",
                    )
                ),
                "cache_read_tokens": usage.get("cache_read_input_tokens", 0) or 0,
                "input_cost_usd": input_cost,
                "output_cost_usd": usage["output_tokens"] * 10 / 1_000_000,
            }
        )
    return dict(totals)


class WorkloadJudge:
    def __init__(self, renderer, fraction, papers, paragraph_fraction=None):
        self.renderer = renderer
        self.fraction = fraction
        self.paragraph_fraction = fraction if paragraph_fraction is None else paragraph_fraction
        self.paragraph_ordinals = {
            p.text: p.ordinal for paper in papers for s in paper.sections for p in s.paragraphs
        }
        self.seen = set()
        self.records = []
        self.reused = 0
        self.skill_hashes = {}

    def identity(self, context):
        if "members" in context:
            return self.identity(context["members"][0])
        if "paragraph_under_consideration" in context:
            text = context["paragraph_under_consideration"]["full_text"]
            return "paragraph", self.paragraph_ordinals[text]
        return context["unit_kind"], context["ordinal"]

    def judge(self, request):
        rendered = self.renderer.render_request(request)
        if request.skill_ref not in self.skill_hashes:
            self.skill_hashes[request.skill_ref] = directory_hash(
                self.renderer.skill_root / request.skill_ref
            )
        fingerprint = self.renderer._fingerprint(
            request, rendered, self.skill_hashes[request.skill_ref]
        )
        hit = fingerprint in self.seen
        if hit:
            self.reused += 1
        else:
            self.seen.add(fingerprint)
            self.records.append(
                {
                    "stage": request.stage_id,
                    "kind": request.output_kind,
                    "paper_index": request.paper_index,
                    "characters": len(rendered.system)
                    + len(rendered.user)
                    + len(rendered.cacheable_context or ""),
                    "candidates": len(request.allowed_match_ids),
                }
            )
        normalized = {QUESTION_FIELD: QUESTION}
        if request.output_kind == "match":
            target = None
            # No speculative realignment merges; its actual reciprocal calls
            # still run when primary matching creates eligible mixed groups.
            if "rerepresentation" not in request.stage_id:
                identity = self.identity(request.context["focus"])
                fraction = self.paragraph_fraction if identity[0] == "paragraph" else self.fraction
                included = fraction == 1 or (fraction == 0.5 and identity[1] % 2 == 0)
                if included:
                    target = next(
                        (
                            candidate_id
                            for candidate_id, candidate in zip(
                                request.allowed_match_ids,
                                request.context["candidates"],
                                strict=True,
                            )
                            if self.identity(candidate) == identity
                        ),
                        None,
                    )
            normalized = {
                "target_id": target,
                "basis": "Synthetic ordinal-only capacity probe, not a semantic judgment.",
            }
        return JudgmentResult(
            fingerprint=fingerprint,
            normalized=normalized,
            raw_response={"source": "offline-capacity-probe"},
            rendered_system=rendered.system,
            rendered_user=rendered.user,
            prompt_hash=rendered.prompt_hash,
            context_hash=rendered.context_hash,
            schema_hash=rendered.schema_hash,
            model={"provider": "offline"},
            cache_hit=hit,
        )


def scenario(fraction, calibration, paragraph_fraction=None):
    config = load_pipeline_config(DEFAULT_CONFIG)
    manifest, papers = load_manifest(MANIFEST)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        renderer = AnthropicJudgmentProvider(
            PromptRepository(config.prompt_root, config.context_root),
            config.model,
            root / "cache",
            config.skill_root,
        )
        judge = WorkloadJudge(renderer, fraction, papers, paragraph_fraction)
        revision_calls = []
        for count in range(2, 6):
            before = len(judge.records)
            _, fresh = load_manifest(MANIFEST)
            runner = IncrementalGraphRunner(
                config, judge, root / f"revision-{count}", max_granularity=manifest.max_granularity
            )
            runner.run(fresh[:count])
            revision_calls.append({"papers": count, "new_calls": len(judge.records) - before})
        stages = {}
        for stage in sorted({r["stage"] for r in judge.records}):
            records = [r for r in judge.records if r["stage"] == stage]
            observed = calibration[records[0]["kind"]]
            characters = sum(r["characters"] for r in records)
            cost = (
                characters * observed["input_cost_usd"] / observed["characters"]
                + len(records) * observed["output_cost_usd"] / observed["calls"]
            )
            stages[stage] = {
                "calls": len(records),
                "characters": characters,
                "hci_calibrated_usd": round(cost, 4),
            }
        largest = max(judge.records, key=lambda r: r["characters"])
        input_estimates = [
            r["characters"]
            * calibration[r["kind"]]["input_tokens"]
            / calibration[r["kind"]]["characters"]
            for r in judge.records
        ]
        output_cost = sum(
            calibration[r["kind"]]["output_cost_usd"] / calibration[r["kind"]]["calls"]
            for r in judge.records
        )
        return {
            "synthetic_alignment_fraction": fraction,
            "synthetic_paragraph_alignment_fraction": judge.paragraph_fraction,
            "unique_calls": len(judge.records),
            "reused_completed_calls": judge.reused,
            "revisions": revision_calls,
            "stages": stages,
            "hci_calibrated_token_cost_usd": round(
                sum(s["hci_calibrated_usd"] for s in stages.values()), 2
            ),
            "largest_prompt": largest,
            "all_prompts_within_default_guard": all(
                r["characters"] <= config.model.max_prompt_characters for r in judge.records
            ),
            "hci_calibrated_input_tokens": round(sum(input_estimates)),
            "largest_call_hci_calibrated_input_tokens": round(max(input_estimates)),
            "no_prompt_cache_sensitivity_usd": round(
                sum(input_estimates) * 2 / 1_000_000 + output_cost, 2
            ),
        }


def main():
    with patch.object(
        ClaudeSkills,
        "__init__",
        side_effect=AssertionError("Offline preflight forbids API clients"),
    ):
        calibration = hci_calibration()
        _, papers = load_manifest(MANIFEST)
        state = RunState.model_validate(read_json(HCI / "run.json"))
        report = {
            "mode": "offline-synthetic-workload-only",
            "hci_saved_policy_matches_current_code": state.policy_sha256
            == _policy_hash(state.config),
            "paragraphs": sum(len(s.paragraphs) for p in papers for s in p.sections),
            "words": sum(
                len(q.text.split()) for p in papers for s in p.sections for q in s.paragraphs
            ),
            "structural_units": sum(len(p.sections) for p in papers),
            "calibration": calibration,
            "assumptions": "Start two fresh content-only opinions, then append one at a time. Real runner and prompt encoder; fake fixed generic questions and ordinal-only primary matches, no accepted realignment merges. Exact completed-request fingerprint reuse across revisions. HCI observed input cost per prompt character and output cost per judgment, separately for questions and matches. Includes executed singleton checks, group questions, native Skill overhead through empirical calibration. No-prompt-cache sensitivity charges all estimated input at the uncached rate but still reuses completed judgments. Excludes retries, tool fees, unknown billing usage, and extraction already completed. Scenarios are NOT predictions, bounds, or evidence of semantic matching quality. No API calls or persistent graph created.",
            "scenarios": [scenario(fraction, calibration) for fraction in (0, 0.5, 1)]
            + [scenario(1, calibration, fraction) for fraction in (0, 0.5)],
        }
    write_json(ROOT / "output/legal-opinions-preflight-20260910.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
