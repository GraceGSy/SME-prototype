"""Computes the "group-balance" metric for each paragraph group produced at
the end of refinement iteration 1 (paragraph_groups_iter1.json).

Iteration 1 assigns every paragraph to the QI-Prime (the group's overarching
question) that it answers best. For each group, balance is the percentage of
papers with at least one paragraph assigned to that QI-Prime. Multiple
paragraphs from the same paper still count only once.

Groups are sorted by this metric, highest first.

Pure local computation over already-saved JSON -- no Claude API calls.

Usage:
    python3 compute_group_balance.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"


def compute_balance(group: dict, paper_ids: list[str]) -> float:
    represented_papers = {member["paper"] for member in group["members"]}
    paper_count = sum(paper_id in represented_papers for paper_id in paper_ids)
    return round(paper_count / len(paper_ids) * 100, 1) if paper_ids else 0.0


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    paper_ids = [m["paper_id"] for m in manifest]

    iter1 = json.loads((OUTPUT_DIR / "paragraph_groups_iter1.json").read_text())
    groups = iter1["groups"]

    scored = []
    for group in groups:
        balance = compute_balance(group, paper_ids)
        scored.append({
            "group_id": group["group_id"],
            "overarching_question": group["overarching_question"],
            "group_balance": balance,
            "member_count": len(group["members"]),
        })

    scored.sort(key=lambda g: -g["group_balance"])

    print(
        f"Group-balance metric (% of {len(paper_ids)} papers represented by "
        "at least one assigned paragraph), iteration 1 groups:"
    )
    for g in scored:
        print(f"  {g['group_balance']:5.1f}%  {g['group_id']} ({g['member_count']} members): {g['overarching_question']!r}")

    out_path = OUTPUT_DIR / "group_balance_iter1.json"
    out_path.write_text(json.dumps(scored, indent=2) + "\n")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
