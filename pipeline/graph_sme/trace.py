"""Instrumented replay of the stage-2 alignment algorithm that records every
intermediate decision -- candidate generation, each parallel-connectivity
pruning pass, the built kernels, and every accept/reject decision in the
greedy merge -- for the step-wise viewer in viz/align_viewer.html.

Reuses the core candidate-generation, kernel-building, and scoring logic from
align_graphs.py unchanged; only the arc-consistency loop and the greedy merge
loop are re-run here with step-by-step trace recording layered on top, so the
"real" algorithm in align_graphs.py stays simple and untangled from tracing
concerns.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

from .align import (
    build_kernels,
    entity_candidates,
    proposition_candidates,
    score_kernel,
)
from .models import PaperGraph


def _arc_consistency_trace(
    graph_a: PaperGraph,
    graph_b: PaperGraph,
    prop_cands: set[tuple[str, str]],
    entity_cands: dict[tuple[str, str], float],
) -> tuple[set[tuple[str, str]], list[dict]]:
    a_props = {p.id: p for p in graph_a.propositions}
    b_props = {p.id: p for p in graph_b.propositions}
    a_entity_ids = {e.id for e in graph_a.entities}
    b_entity_ids = {e.id for e in graph_b.entities}
    entity_cand_set = set(entity_cands.keys())

    surviving = set(prop_cands)
    passes = []
    pass_num = 0
    while True:
        pass_num += 1
        to_remove = []
        for pa_id, pb_id in surviving:
            pa, pb = a_props[pa_id], b_props[pb_id]
            reason = None
            for i, (arg_a, arg_b) in enumerate(zip(pa.args, pb.args)):
                a_is_entity = arg_a in a_entity_ids
                b_is_entity = arg_b in b_entity_ids
                if a_is_entity != b_is_entity:
                    reason = f"argument {i}: one side is an entity, the other a proposition"
                    break
                if a_is_entity:
                    if (arg_a, arg_b) not in entity_cand_set:
                        reason = f"argument {i}: entities {arg_a}/{arg_b} were never a candidate pair"
                        break
                else:
                    if (arg_a, arg_b) not in surviving:
                        reason = f"argument {i}: sub-proposition {arg_a}/{arg_b} didn't survive an earlier pass"
                        break
            if reason:
                to_remove.append({"a": pa_id, "b": pb_id, "reason": reason})
        if not to_remove:
            break
        for item in to_remove:
            surviving.discard((item["a"], item["b"]))
        passes.append({"pass": pass_num, "removed": to_remove, "surviving_count": len(surviving)})
    return surviving, passes


def _merge_trace(
    kernels: list[list[tuple[str, str, str]]],
    scores: list[float],
) -> tuple[list[list[tuple[str, str, str]]], list[dict]]:
    order = sorted(range(len(kernels)), key=lambda i: scores[i], reverse=True)
    a_to_b: dict[str, str] = {}
    b_to_a: dict[str, str] = {}
    accepted = []
    steps = []
    for rank, i in enumerate(order):
        kernel = kernels[i]
        conflict = None
        for _, a_id, b_id in kernel:
            if a_to_b.get(a_id, b_id) != b_id:
                conflict = {"id": a_id, "side": "a", "existing_partner": a_to_b[a_id], "wanted_partner": b_id}
                break
            if b_to_a.get(b_id, a_id) != a_id:
                conflict = {"id": b_id, "side": "b", "existing_partner": b_to_a[b_id], "wanted_partner": a_id}
                break
        decision = "accepted" if conflict is None else "rejected"
        if conflict is None:
            accepted.append(kernel)
            for _, a_id, b_id in kernel:
                a_to_b[a_id] = b_id
                b_to_a[b_id] = a_id
        steps.append({
            "rank": rank,
            "kernel_index": i,
            "score": round(scores[i], 2),
            "nodes": [{"kind": k, "a": a, "b": b} for k, a, b in kernel],
            "decision": decision,
            "conflict": conflict,
        })
    return accepted, steps


def align_with_trace(graph_a: PaperGraph, graph_b: PaperGraph) -> dict:
    entity_cands = entity_candidates(graph_a, graph_b)
    prop_cands_raw = proposition_candidates(graph_a, graph_b)

    surviving, connectivity_passes = _arc_consistency_trace(graph_a, graph_b, prop_cands_raw, entity_cands)
    kernels = build_kernels(graph_a, graph_b, surviving)

    orders_a = graph_a.proposition_orders()
    orders_b = graph_b.proposition_orders()
    scores = [score_kernel(k, orders_a, orders_b, entity_cands) for k in kernels]

    accepted, merge_steps = _merge_trace(kernels, scores)

    entity_seen: dict[str, dict] = {}
    prop_seen: dict[str, dict] = {}
    for kernel in accepted:
        for kind, a_id, b_id in kernel:
            if kind == "entity":
                entity_seen[a_id] = {"a": a_id, "b": b_id, "name_similarity": round(entity_cands.get((a_id, b_id), 0.0), 3)}
            else:
                prop_seen[a_id] = {"a": a_id, "b": b_id, "order_a": orders_a.get(a_id, 0), "order_b": orders_b.get(b_id, 0)}

    return {
        "paper_a": graph_a.model_dump(),
        "paper_b": graph_b.model_dump(),
        "candidates": {
            "entity_candidate_count": len(entity_cands),
            "proposition_candidate_count": len(prop_cands_raw),
            "proposition_candidates": [{"a": a, "b": b} for a, b in sorted(prop_cands_raw)],
        },
        "connectivity_passes": connectivity_passes,
        "surviving_after_connectivity": [{"a": a, "b": b} for a, b in sorted(surviving)],
        "kernels": [
            {
                "index": i,
                "score": round(scores[i], 2),
                "nodes": [{"kind": k, "a": a, "b": b} for k, a, b in kernel],
            }
            for i, kernel in enumerate(kernels)
        ],
        "merge_steps": merge_steps,
        "final": {
            "entity_correspondences": sorted(entity_seen.values(), key=lambda x: -x["name_similarity"]),
            "proposition_correspondences": sorted(prop_seen.values(), key=lambda x: -(x["order_a"] + x["order_b"])),
        },
    }


def main() -> None:
    output_dir = Path(__file__).resolve().parent / "output"
    manifest = json.loads((output_dir / "manifest.json").read_text())
    graphs = {m["paper_id"]: PaperGraph.model_validate(json.loads((output_dir / m["file"]).read_text())) for m in manifest}

    ids = list(graphs.keys())
    if len(sys.argv) > 1:
        ids = sys.argv[1:]

    trace_manifest = []
    for id_a, id_b in itertools.combinations(ids, 2):
        trace = align_with_trace(graphs[id_a], graphs[id_b])
        filename = f"trace_{id_a}_vs_{id_b}.json"
        (output_dir / filename).write_text(json.dumps(trace, indent=2))
        trace_manifest.append({
            "paper_a": id_a, "paper_b": id_b, "file": filename,
            "num_steps": 1 + len(trace["connectivity_passes"]) + 1 + len(trace["merge_steps"]) + 1,
        })
        print(f"wrote {output_dir / filename} ({trace_manifest[-1]['num_steps']} steps)")

    (output_dir / "trace_manifest.json").write_text(json.dumps(trace_manifest, indent=2))
    print(f"wrote {output_dir / 'trace_manifest.json'}")


if __name__ == "__main__":
    main()
