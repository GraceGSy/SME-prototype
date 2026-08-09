"""Variant of reassign_via_milp.py: since Matrix 2 (question_paragraph_
ranking.json) only ever ranks paragraphs WITHIN one paper to begin with --
it never actually compares paragraphs across papers -- this solves the
balanced-assignment MILP separately for each paper's own paragraphs, instead
of pooling all 3 papers into one combined N=236 problem with an artificial
cross-paper concatenation to fake a global group_rank (see
reassign_via_milp.py's docstring for why that concatenation was needed
there). Solving per paper uses Matrix 2 exactly as computed, with no
concatenation trick.

Each paper's sub-problem is a smaller instance of the same "N items / K
groups" MILP: N = that paper's own paragraph count, K = 21 groups (same
group_ids/questions as before). The three independent solutions are then
combined into one groups structure (each group's members drawn from all 3
papers' own solves).

The size-balance target is the original combined target (round(236/21) =
11) divided by the number of papers (3): round(11/3) = 4, applied uniformly
to every paper's sub-problem -- so each paper aims to put ~4 of its own
paragraphs in each group, rather than ~11 pooled from wherever.

run_per_paper() is the reusable core (penalty_mode/lambda_override/output
filename are all parameters), imported by the no-penalty and quadratic-
penalty variant scripts so the per-paper solve logic isn't duplicated three
times. Each variant writes its own output file and never overwrites another
variant's.

Pure local computation over already-saved JSON -- no Claude API calls.

Usage:
    python3 reassign_via_milp_per_paper.py
"""
from __future__ import annotations

import json
from pathlib import Path

from reassign_via_milp import ALPHA, BETA, load_papers, build_item_rank, solve

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"


def build_cost_matrix_for_paper(items, group_ids, item_rank, matrix2, paper_id):
    """Same normalization as reassign_via_milp.build_cost_matrix, but
    group_rank comes directly from this paper's own Matrix-2 ranking --
    no cross-paper concatenation needed since everything here is already
    scoped to one paper."""
    N, K = len(items), len(group_ids)
    cost = {}
    for i, item in enumerate(items):
        for k, gid in enumerate(group_ids):
            norm_item = (item_rank[item][gid] - 1) / (K - 1) if K > 1 else 0.0
            ranking = (matrix2.get(gid, {}) or {}).get(paper_id, [])
            g_rank = (ranking.index(item[1]) + 1) if item[1] in ranking else N + 1
            norm_group = (g_rank - 1) / (N - 1) if N > 1 else 0.0
            cost[(i, k)] = ALPHA * norm_item + BETA * norm_group
    return cost


def run_per_paper(
    output_filename: str,
    penalty_mode: str = "linear",
    lambda_override: float | None = None,
) -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    paper_ids_in_order = [m["paper_id"] for m in manifest]
    papers = load_papers(manifest)

    quote_groups = json.loads((OUTPUT_DIR / "quote_groups.json").read_text())
    groups_meta = quote_groups.get("paragraphs", [])
    if not groups_meta or not all(g.get("overarching_question") for g in groups_meta):
        raise RuntimeError("quote_groups.json has no paragraph groups with an overarching_question -- run summarize_groups.py first")
    group_ids = [g["group_id"] for g in groups_meta]
    question_by_group = {g["group_id"]: g["overarching_question"] for g in groups_meta}
    K = len(group_ids)

    matrix1 = json.loads((OUTPUT_DIR / "paragraph_question_ranking.json").read_text())
    matrix2 = json.loads((OUTPUT_DIR / "question_paragraph_ranking.json").read_text())

    total_paragraphs = sum(len(papers[p].paragraphs) for p in paper_ids_in_order)
    global_target_size = round(total_paragraphs / K)
    per_paper_target_size = round(global_target_size / len(paper_ids_in_order))
    print(f"penalty_mode={penalty_mode!r}  total paragraphs = {total_paragraphs}, K = {K}, global target "
          f"{global_target_size} -> per-paper target {per_paper_target_size} (divided by {len(paper_ids_in_order)} papers)\n")

    groups_out: dict[str, list[dict]] = {gid: [] for gid in group_ids}
    per_paper_status = {}
    total_top1 = 0
    total_rank_sum = 0.0

    for paper_id in paper_ids_in_order:
        items = [(paper_id, p.id) for p in papers[paper_id].paragraphs]
        tag_by_item = {(paper_id, p.id): p.tag for p in papers[paper_id].paragraphs}
        N = len(items)
        print(f"=== {paper_id}: N = {N} paragraphs ===")

        item_rank = build_item_rank(items, matrix1, group_ids)
        cost = build_cost_matrix_for_paper(items, group_ids, item_rank, matrix2, paper_id)

        assignment, status_name, objective = solve(
            items, group_ids, cost,
            target_size=per_paper_target_size,
            penalty_mode=penalty_mode,
            lambda_override=lambda_override,
        )
        per_paper_status[paper_id] = status_name
        print(f"  solver status: {status_name}, objective: {objective:.1f}")
        if status_name not in ("OPTIMAL", "FEASIBLE"):
            raise RuntimeError(f"solver did not find a usable solution for {paper_id} (status={status_name})")

        top1 = 0
        for i, item in enumerate(items):
            gid = group_ids[assignment[i]]
            groups_out[gid].append({"paper": item[0], "unit_id": item[1], "tag": tag_by_item[item]})
            r = item_rank[item][gid]
            total_rank_sum += r
            if r == 1:
                top1 += 1
        total_top1 += top1
        print(f"  {top1}/{N} paragraphs ({100 * top1 / N:.1f}%) got their #1-preferred group.")

        this_paper_sizes: dict[str, int] = {}
        for i in assignment.values():
            gid = group_ids[i]
            this_paper_sizes[gid] = this_paper_sizes.get(gid, 0) + 1
        print(f"  contributed to {len(this_paper_sizes)}/{K} groups (target {per_paper_target_size} each)\n")

    print(f"combined: {total_top1}/{total_paragraphs} paragraphs ({100 * total_top1 / total_paragraphs:.1f}%) got their #1-preferred group.")
    print(f"average assigned-group rank across all papers: {total_rank_sum / total_paragraphs:.2f} of {K}")
    print("\ncombined group sizes:")
    for gid in group_ids:
        print(f"  {gid}: {len(groups_out[gid])} members -- {question_by_group[gid]!r}")

    output = {
        "parameters": {
            "alpha": ALPHA, "beta": BETA,
            "penalty_mode": penalty_mode,
            "lambda": lambda_override,
            "global_target_size": global_target_size,
            "per_paper_target_size": per_paper_target_size,
            "num_papers": len(paper_ids_in_order),
        },
        "solver_status_by_paper": per_paper_status,
        "groups": [
            {"group_id": gid, "overarching_question": question_by_group[gid], "members": groups_out[gid]}
            for gid in group_ids
        ],
    }
    out_path = OUTPUT_DIR / output_filename
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nwrote {out_path}")


def main() -> None:
    run_per_paper("milp_reassignment_per_paper.json", penalty_mode="linear")


if __name__ == "__main__":
    main()
