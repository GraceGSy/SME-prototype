"""Replay explicit saved Jev decisions with fixed evidence, never rebuild a graph."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from .files import read_json, write_json
from .incremental_graph.configuration import load_pipeline_config
from .incremental_graph.evidence_encoding import encode_evidence
from .incremental_graph.jev_selection import JevSelector
from .incremental_graph.match_evidence import candidate_handle
from .incremental_graph.models import JudgmentRequest
from .providers.jev import JevClient, JevSettings, encode_request, validate_response

ROOT = Path(__file__).resolve().parents[1]
MODES = ("choice", "choice_noul")


def decode_saved_state(state: dict) -> dict:
    """Restore the old lossless text references, checking the round trip."""
    texts = state["source_texts"]

    def visit(item):
        if isinstance(item, list):
            return [visit(child) for child in item]
        if not isinstance(item, dict):
            return item
        return {
            "full_text" if key == "full_text_refs" else key: "\n\n".join(
                texts[reference] for reference in value
            )
            if key == "full_text_refs"
            else visit(value)
            for key, value in item.items()
        }

    context = visit(
        {
            key: value
            for key, value in state.items()
            if key not in {"source_texts", "text_reference_contract"}
        }
    )
    if encode_evidence(context) != state:
        raise ValueError("Saved evidence did not round-trip exactly")
    return context


def saved_cases(revision: Path, cases: list[dict]) -> list[tuple[dict, JudgmentRequest]]:
    attempts = {
        item["attempt_id"]: item
        for line in (revision / "provenance/attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if (item := json.loads(line))
    }
    ids = [case["attempt_id"] for case in cases]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Specify a nonempty list of unique saved attempts")
    result = []
    for case in cases:
        attempt = attempts[case["attempt_id"]]
        selection = attempt["raw_response"]["jev"]
        if len(selection["calls"]) != 1:
            raise ValueError("Comparison requires original unsplit candidate pools")
        fingerprint = selection["calls"][0]["fingerprint"]
        saved = read_json(revision.parent.parent / "cache/jev" / f"{fingerprint}.json")
        if hashlib.sha256(encode_request(saved["request"])).hexdigest() != fingerprint:
            raise ValueError("Saved request fingerprint mismatch")
        validate_response(saved["response"], saved["request"])
        context = decode_saved_state(saved["request"]["state"])
        ids = [candidate_handle(candidate) for candidate in context["candidates"]]
        if ids != attempt["candidate_ids"]:
            raise ValueError("Saved candidate pool differs from the attempt")
        request = JudgmentRequest(
            key=attempt["request_key"],
            paper_index=attempt["paper_index"],
            stage_id=attempt["stage_id"],
            output_kind="match",
            prompt_ref=attempt["prompt_ref"],
            context_ref=attempt["context_ref"],
            context=context,
            allowed_match_ids=ids,
        )
        result.append(
            (
                {
                    **case,
                    "request_key": request.key,
                    "candidate_count": len(ids),
                    "legacy_fingerprint": fingerprint,
                    "legacy_target_id": selection["target_id"],
                    "legacy_response": saved["response"],
                },
                request,
            )
        )
    return result


def compare_prompts(
    revision: Path,
    cases_path: Path,
    output: Path,
    *,
    live: bool = False,
    max_calls: int = 24,
    max_input_tokens: int = 500_000,
) -> dict:
    revision, output = revision.resolve(), output.resolve()
    run = revision.parent.parent
    if output == run or output.is_relative_to(run):
        raise ValueError("Write comparisons outside the original run")
    cases = saved_cases(revision, read_json(cases_path))
    models = {case["legacy_response"]["model"] for case, _ in cases}
    if len(models) != 1:
        raise ValueError("Compare one pinned model at a time")
    config = load_pipeline_config(ROOT / "pipeline/incremental_graph/configs/incremental-v1.yaml")
    settings = JevSettings(
        model=models.pop(), max_calls=max_calls, max_input_tokens=max_input_tokens
    )
    client = JevClient(settings, ROOT, output / "cache/responses")
    selectors = {}
    for mode in MODES:
        selector = JevSelector(
            settings.model_copy(update={"selection_mode": mode}),
            output / "cache",
            config.skill_root,
            config.prompt_root,
        )
        selector.client = client  # One process-wide spending guard across both variants.
        selectors[mode] = selector
    plan = {"revision": str(revision), "cases": [], "model": settings.model}
    for case, request in cases:
        payloads = {
            mode: selector.build_request(request.context) for mode, selector in selectors.items()
        }
        plan["cases"].append({**case, "requests": payloads})
    plan_path = output / "plan.json"
    if plan_path.exists() and read_json(plan_path) != plan:
        raise ValueError("Comparison inputs or prompts changed; choose a new output directory")
    write_json(plan_path, plan)
    report_path = output / "comparison.json"
    report = (
        read_json(report_path)
        if report_path.exists()
        else {
            "revision": str(revision),
            "model": settings.model,
            "cases": [],
            "warning": "Directional decision comparison, not accuracy or a reconstructed graph. No human labels.",
        }
    )
    if not live:
        return {
            "plan": str(plan_path),
            "cases": len(cases),
            "planned_calls": 2 * len(cases),
            "http_attempts": 0,
        }
    try:
        for case, request in cases:
            row = next(
                (item for item in report["cases"] if item["attempt_id"] == case["attempt_id"]), None
            )
            if row is None:
                row = {**case, "variants": {}}
                report["cases"].append(row)
            for mode, selector in selectors.items():
                start = perf_counter()
                selection = selector.select(request, allow_splitting=False)
                elapsed = perf_counter() - start
                # Retain the original measured latency when resuming from valid caches.
                if mode not in row["variants"] or not all(
                    call["cache_hit"] for call in selection["calls"]
                ):
                    row["variants"][mode] = {
                        **selection,
                        "elapsed_seconds": None
                        if all(call["cache_hit"] for call in selection["calls"])
                        else elapsed,
                        "input_tokens": sum(
                            call["response"]["usage"]["input_tokens"] for call in selection["calls"]
                        ),
                    }
                write_json(report_path, report)
                print(f"{case['attempt_id']} {mode}: {selection['target_id']}", flush=True)
        report["status"] = "complete"
        report.pop("error", None)
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["last_invocation"] = {
            "http_attempts": client.calls,
            "reported_input_tokens": client.input_tokens,
        }
        write_json(report_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("revision", type=Path)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--live", action="store_true", help="Make paid Jev calls; otherwise write an offline plan"
    )
    parser.add_argument("--max-calls", type=int, default=24)
    parser.add_argument("--max-input-tokens", type=int, default=500_000)
    args = parser.parse_args()
    report = compare_prompts(
        args.revision,
        args.cases,
        args.out,
        live=args.live,
        max_calls=args.max_calls,
        max_input_tokens=args.max_input_tokens,
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if not isinstance(value, list)}, indent=2
        )
    )


if __name__ == "__main__":
    main()
