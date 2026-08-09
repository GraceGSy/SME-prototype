"""Re-assigns paragraphs ("items", each identified by its own tag/question)
to groups ("groups", the 21 candidate overarching_questions used to build
the two ranking matrices) via a balanced, two-sided-preference MILP, as an
alternative to refine_paragraph_groups.py's independent per-paragraph
best-fit assignment.

This does NOT overwrite refine_paragraph_groups.py's output or any other
existing file -- results are written to their own new file,
output/sections/milp_reassignment.json.

Mapping from the write-up's generic "N items / K groups" problem onto this
project's data:
  - N items = all 236 paragraphs across all papers (each identified by
    (paper, unit_id), described by its own tag/"question").
  - K groups = the 21 group_ids from quote_groups.json -- the same ones
    used to build both ranking matrices in compute_ranking_matrices.py --
    each labeled by its overarching_question.
  - item_rank[i][k] comes directly from Matrix 1 (paragraph_question_
    ranking.json): paragraph i's own best->worst ranking of all K
    candidate questions.
  - group_rank[k][i] is built from Matrix 2 (question_paragraph_ranking.
    json), which ranks each PAPER's paragraphs separately for a given
    question rather than one combined 1..N ranking. To get the single
    complete 1..N ranking the write-up's formulation calls for, each
    group's three per-paper rankings are concatenated in a fixed paper
    order (the order papers appear in manifest.json) into one list, and an
    item's global rank is its 1-indexed position in that concatenation.
    This is a deliberate modeling choice, not something already computed
    elsewhere -- it means "group k's rank of item i" only really compares
    same-paper items directly; cross-paper ordering is just concatenation
    order, not a re-judged preference.

Steps 1-5 of the write-up are implemented as given: normalize both rank
matrices to [0, 1], build a combined cost c[i][k] = alpha*norm_item_rank +
beta*norm_group_rank, linearize the group-size-imbalance penalty via
auxiliary d[k] >= |s[k] - target_size[k]| variables, and solve the resulting
MILP with OR-Tools CP-SAT.

Pure local computation over already-saved JSON -- no Claude API calls.

Usage:
    python3 reassign_via_milp.py
"""
from __future__ import annotations

import json
from pathlib import Path

from ortools.sat.python import cp_model

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"

# Tuning parameters (see write-up) -- equal weight on both sides' preference,
# a modest balance penalty as a starting point (raise LAMBDA_ to tighten
# group sizes at the expense of preference quality, lower it to let fit
# dominate).
ALPHA = 1.0
BETA = 1.0
LAMBDA = 0.5
SCALE = 1000  # CP-SAT needs integer costs; this is the write-up's suggested scale
SOLVER_TIME_LIMIT_SECONDS = 60


def load_papers(manifest: list[dict]) -> dict:
    from section_schema import SectionedPaper
    return {
        m["paper_id"]: SectionedPaper.model_validate(json.loads((OUTPUT_DIR / m["file"]).read_text()))
        for m in manifest
    }


def build_item_rank(items: list[tuple[str, str]], matrix1: dict, group_ids: list[str]) -> dict:
    """(paper, unit_id) -> {group_id: 1-indexed rank of that group, 1=best}."""
    K = len(group_ids)
    item_rank = {}
    for paper_id, unit_id in items:
        ranking = matrix1.get(f"{paper_id}:{unit_id}", [])
        item_rank[(paper_id, unit_id)] = {
            gid: (ranking.index(gid) + 1) if gid in ranking else K + 1
            for gid in group_ids
        }
    return item_rank


def build_group_rank(paper_ids_in_order: list[str], matrix2: dict, group_ids: list[str]) -> dict:
    """group_id -> ordered list of (paper, unit_id), best->worst, formed by
    concatenating each paper's own Matrix-2 ranking (see module docstring)."""
    group_rank_lists = {}
    for gid in group_ids:
        per_paper = matrix2.get(gid, {})
        combined = []
        for paper_id in paper_ids_in_order:
            combined.extend((paper_id, unit_id) for unit_id in per_paper.get(paper_id, []))
        group_rank_lists[gid] = combined
    return group_rank_lists


def rank_of(group_rank_list: list[tuple[str, str]], item: tuple[str, str], fallback: int) -> int:
    try:
        return group_rank_list.index(item) + 1
    except ValueError:
        return fallback


def build_cost_matrix(items, group_ids, item_rank, group_rank_lists):
    N, K = len(items), len(group_ids)
    cost = {}
    for i, item in enumerate(items):
        for k, gid in enumerate(group_ids):
            norm_item = (item_rank[item][gid] - 1) / (K - 1) if K > 1 else 0.0
            g_rank = rank_of(group_rank_lists[gid], item, fallback=N + 1)
            norm_group = (g_rank - 1) / (N - 1) if N > 1 else 0.0
            cost[(i, k)] = ALPHA * norm_item + BETA * norm_group
    return cost


def solve(
    items,
    group_ids,
    cost,
    target_size: int | None = None,
    penalty_mode: str = "linear",
    lambda_override: float | None = None,
) -> tuple[dict, str, float]:
    """penalty_mode:
      - "linear" (default, as in the write-up): d[k] >= |s[k] - target_size|,
        objective += lambda * sum(d) -- an L1 (absolute-deviation) penalty.
      - "quadratic": objective += lambda * sum((s[k] - target_size)^2) -- an
        L2 penalty that punishes large deviations disproportionately more
        than small ones. CP-SAT has no native quadratic objective, but since
        s[k] and the deviation are bounded integers, (s[k]-target)^2 can be
        modeled exactly via an auxiliary variable tied to it with
        AddMultiplicationEquality.
      - "none": no size-balance term at all -- pure preference-cost
        minimization, group sizes are whatever the assignment falls out to.
    """
    N, K = len(items), len(group_ids)
    if target_size is None:
        target_size = round(N / K)
    lam = LAMBDA if lambda_override is None else lambda_override

    model = cp_model.CpModel()
    x = {(i, k): model.NewBoolVar(f"x_{i}_{k}") for i in range(N) for k in range(K)}

    for i in range(N):
        model.Add(sum(x[i, k] for k in range(K)) == 1)

    penalty_terms = []
    if penalty_mode != "none":
        s = [model.NewIntVar(0, N, f"s_{k}") for k in range(K)]
        for k in range(K):
            model.Add(s[k] == sum(x[i, k] for i in range(N)))

        if penalty_mode == "linear":
            d = [model.NewIntVar(0, N, f"d_{k}") for k in range(K)]
            for k in range(K):
                model.Add(d[k] >= s[k] - target_size)
                model.Add(d[k] >= target_size - s[k])
            penalty_terms = d
        elif penalty_mode == "quadratic":
            diff = [model.NewIntVar(-N, N, f"diff_{k}") for k in range(K)]
            sq = [model.NewIntVar(0, N * N, f"sq_{k}") for k in range(K)]
            for k in range(K):
                model.Add(diff[k] == s[k] - target_size)
                model.AddMultiplicationEquality(sq[k], [diff[k], diff[k]])
            penalty_terms = sq
        else:
            raise ValueError(f"unknown penalty_mode {penalty_mode!r}")

    objective_terms = [int(round(cost[(i, k)] * SCALE)) * x[i, k] for i in range(N) for k in range(K)]
    if penalty_terms:
        objective_terms.append(int(round(lam * SCALE)) * sum(penalty_terms))
    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_SECONDS
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    assignment = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for i in range(N):
            for k in range(K):
                if solver.Value(x[i, k]):
                    assignment[i] = k
                    break

    return assignment, status_name, solver.ObjectiveValue() if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else float("nan")


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    paper_ids_in_order = [m["paper_id"] for m in manifest]
    papers = load_papers(manifest)

    quote_groups = json.loads((OUTPUT_DIR / "quote_groups.json").read_text())
    groups_meta = quote_groups.get("paragraphs", [])
    if not groups_meta or not all(g.get("overarching_question") for g in groups_meta):
        raise RuntimeError("quote_groups.json has no paragraph groups with an overarching_question -- run summarize_groups.py first")
    group_ids = [g["group_id"] for g in groups_meta]
    question_by_group = {g["group_id"]: g["overarching_question"] for g in groups_meta}

    matrix1 = json.loads((OUTPUT_DIR / "paragraph_question_ranking.json").read_text())
    matrix2 = json.loads((OUTPUT_DIR / "question_paragraph_ranking.json").read_text())

    items: list[tuple[str, str]] = []
    tag_by_item = {}
    for paper_id in paper_ids_in_order:
        for p in papers[paper_id].paragraphs:
            items.append((paper_id, p.id))
            tag_by_item[(paper_id, p.id)] = p.tag

    N, K = len(items), len(group_ids)
    print(f"N (paragraphs) = {N}, K (groups) = {K}, target group size ~= {N / K:.2f}")

    item_rank = build_item_rank(items, matrix1, group_ids)
    group_rank_lists = build_group_rank(paper_ids_in_order, matrix2, group_ids)
    cost = build_cost_matrix(items, group_ids, item_rank, group_rank_lists)

    assignment, status_name, objective = solve(items, group_ids, cost)
    print(f"solver status: {status_name}, objective: {objective:.1f}")
    if status_name not in ("OPTIMAL", "FEASIBLE"):
        raise RuntimeError(f"solver did not find a usable solution (status={status_name})")

    groups_out: dict[str, list[dict]] = {gid: [] for gid in group_ids}
    top1_count = 0
    assigned_ranks = []
    for i, item in enumerate(items):
        gid = group_ids[assignment[i]]
        groups_out[gid].append({"paper": item[0], "unit_id": item[1], "tag": tag_by_item[item]})
        r = item_rank[item][gid]
        assigned_ranks.append(r)
        if r == 1:
            top1_count += 1

    target_size = round(N / K)
    print(f"\ngroup sizes (target {target_size}):")
    for gid in group_ids:
        print(f"  {gid}: {len(groups_out[gid])} members -- {question_by_group[gid]!r}")

    print(f"\n{top1_count}/{N} paragraphs ({100 * top1_count / N:.1f}%) got their #1-preferred group.")
    print(f"average assigned-group rank (from the paragraph's own preference list): {sum(assigned_ranks) / N:.2f} of {K}")

    output = {
        "parameters": {"alpha": ALPHA, "beta": BETA, "lambda": LAMBDA, "target_size": target_size},
        "solver_status": status_name,
        "objective": objective,
        "groups": [
            {"group_id": gid, "overarching_question": question_by_group[gid], "members": groups_out[gid]}
            for gid in group_ids
        ],
    }
    out_path = OUTPUT_DIR / "milp_reassignment.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
