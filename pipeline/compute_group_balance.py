"""Computes the "group-balance" metric for each paragraph group produced at
the end of refinement iteration 1 (paragraph_groups_iter1.json):

For each paper, check whether that paper's own top-ranked paragraph for this
group's question -- rank 1 in question_paragraph_ranking.json (Matrix 2),
looked up by this group's group_id -- is a member of this group. Each paper
whose rank-1 paragraph is present counts toward the group's balance metric,
expressed as a percentage of all papers (count / total papers * 100) -- so a
group where every paper's single best-fitting paragraph for the question
ended up together scores 100%, while a group missing one or more papers' top
pick scores lower.

Groups are sorted by this metric, highest first.

Pure local computation over already-saved JSON -- no Claude API calls.

Usage:
    python3 compute_group_balance.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"


def compute_balance(group: dict, matrix2: dict, paper_ids: list[str]) -> float:
    group_id = group["group_id"]
    member_keys = {(m["paper"], m["unit_id"]) for m in group["members"]}
    rankings = matrix2.get(group_id, {})

    count = 0
    for paper_id in paper_ids:
        ranking = rankings.get(paper_id, [])
        if not ranking:
            continue
        top_unit_id = ranking[0]
        if (paper_id, top_unit_id) in member_keys:
            count += 1
    return round(count / len(paper_ids) * 100, 1) if paper_ids else 0.0


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    paper_ids = [m["paper_id"] for m in manifest]

    iter1 = json.loads((OUTPUT_DIR / "paragraph_groups_iter1.json").read_text())
    groups = iter1["groups"]

    matrix2 = json.loads((OUTPUT_DIR / "question_paragraph_ranking.json").read_text())

    scored = []
    for group in groups:
        balance = compute_balance(group, matrix2, paper_ids)
        scored.append({
            "group_id": group["group_id"],
            "overarching_question": group["overarching_question"],
            "group_balance": balance,
            "member_count": len(group["members"]),
        })

    scored.sort(key=lambda g: -g["group_balance"])

    print(f"Group-balance metric (% of {len(paper_ids)} papers whose top-ranked paragraph is in the group), iteration 1 groups:")
    for g in scored:
        print(f"  {g['group_balance']:5.1f}%  {g['group_id']} ({g['member_count']} members): {g['overarching_question']!r}")

    out_path = OUTPUT_DIR / "group_balance_iter1.json"
    out_path.write_text(json.dumps(scored, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
