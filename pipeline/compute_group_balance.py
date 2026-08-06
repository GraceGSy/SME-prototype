"""Computes the "group-balance" metric for every saved refinement iteration.

Each iteration assigns every paragraph to the QI-Prime (the group's
overarching question) that it answers best. For each group, balance is the
percentage of papers with at least one paragraph assigned to that QI-Prime.
Multiple paragraphs from the same paper still count only once.

Groups are sorted by this metric, highest first.

Pure local computation over already-saved JSON -- no Claude API calls.

Usage:
    python3 compute_group_balance.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"
ITERATION_FILE_RE = re.compile(r"paragraph_groups_iter(\d+)\.json")


def compute_balance(group: dict, paper_ids: list[str]) -> float:
    represented_papers = {member["paper"] for member in group["members"]}
    paper_count = sum(paper_id in represented_papers for paper_id in paper_ids)
    return round(paper_count / len(paper_ids) * 100, 1) if paper_ids else 0.0


def score_groups(groups: list[dict], paper_ids: list[str]) -> list[dict]:
    scored = []
    for group in groups:
        scored.append({
            "group_id": group["group_id"],
            "overarching_question": group["overarching_question"],
            "group_balance": compute_balance(group, paper_ids),
            "member_count": len(group["members"]),
        })
    scored.sort(key=lambda group: -group["group_balance"])
    return scored


def iteration_state_paths(output_dir: Path) -> list[tuple[int, Path]]:
    states = []
    for path in output_dir.glob("paragraph_groups_iter*.json"):
        match = ITERATION_FILE_RE.fullmatch(path.name)
        if match:
            states.append((int(match.group(1)), path))
    return sorted(states)


def compute_all_balances(output_dir: Path = OUTPUT_DIR) -> dict[int, list[dict]]:
    manifest = json.loads((output_dir / "manifest.json").read_text())
    paper_ids = [m["paper_id"] for m in manifest]
    states = iteration_state_paths(output_dir)
    if not states:
        raise FileNotFoundError(f"No paragraph_groups_iter<N>.json files found in {output_dir}")

    results = {}
    for iteration, state_path in states:
        state = json.loads(state_path.read_text())
        scored = score_groups(state["groups"], paper_ids)
        out_path = output_dir / f"group_balance_iter{iteration}.json"
        out_path.write_text(json.dumps(scored, indent=2) + "\n")
        results[iteration] = scored
    return results


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    paper_count = len(manifest)
    results = compute_all_balances()

    for iteration, scored in results.items():
        print(
            f"Iteration {iteration}: group balance (% of {paper_count} papers "
            "represented by at least one assigned paragraph)"
        )
        for group in scored:
            print(
                f"  {group['group_balance']:5.1f}%  {group['group_id']} "
                f"({group['member_count']} members): {group['overarching_question']!r}"
            )
        print(f"wrote {OUTPUT_DIR / f'group_balance_iter{iteration}.json'}\n")


if __name__ == "__main__":
    main()
