"""Computes the group-balance metric for each epoch (1-3) produced by
refine_with_epoch_matrices.py, using that epoch's own saved Matrix 2
(question_paragraph_ranking) rather than group membership alone.

compute_group_balance.py's iteration version credits a paper simply for
having any paragraph in the group, because refine_paragraph_groups.py's
E-step already assigns each paragraph via a single direct best-fit choice,
so membership itself IS the best-fit decision. The epoch process's E-step
(assign_paragraph(), reused from that same script) works the same way --
but each epoch ALSO computes a fresh Matrix 2 against its own surviving
candidates, which the direct-choice E-step does not consult. That makes it
possible (and meaningful) to check the two signals against each other: a
paper is credited for a group only if the SAME paragraph both (a) was
E-step-assigned to the group, and (b) is that paper's #1-ranked paragraph
for the group's question in that epoch's own Matrix 2.

Balance = (papers credited) / (total papers) * 100, sorted highest first,
written to epoch<N>/group_balance.json alongside that epoch's estep/matrix/
mstep files. Pure local computation over already-saved JSON -- no Claude
API calls.

Usage:
    python3 compute_epoch_group_balance.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"
RUN_DIR = OUTPUT_DIR / "epoch_matrix_refinement"
N_EPOCHS = 3


def compute_epoch_balance(epoch_dir: Path, paper_ids: list[str]) -> list[dict]:
    estep = json.loads((epoch_dir / "estep.json").read_text())
    matrix2 = json.loads((epoch_dir / "matrix2.json").read_text())
    mstep = json.loads((epoch_dir / "mstep.json").read_text())
    question_by_group = {g["group_id"]: g["overarching_question"] for g in mstep["groups"]}

    scored = []
    for group in estep["groups"]:
        gid = group["group_id"]
        members_by_paper: dict[str, set[str]] = {}
        for member in group["members"]:
            members_by_paper.setdefault(member["paper"], set()).add(member["unit_id"])

        ranking_by_paper = matrix2.get(gid, {})
        represented = 0
        for paper_id in paper_ids:
            ranking = ranking_by_paper.get(paper_id)
            if not ranking:
                continue
            top_unit_id = ranking[0]
            if top_unit_id in members_by_paper.get(paper_id, set()):
                represented += 1

        scored.append({
            "group_id": gid,
            "overarching_question": question_by_group.get(gid, ""),
            "group_balance": round(represented / len(paper_ids) * 100, 1) if paper_ids else 0.0,
            "member_count": len(group["members"]),
        })

    scored.sort(key=lambda group: -group["group_balance"])
    return scored


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    paper_ids = [m["paper_id"] for m in manifest]

    for epoch in range(1, N_EPOCHS + 1):
        epoch_dir = RUN_DIR / f"epoch{epoch}"
        if not (epoch_dir / "estep.json").exists() or not (epoch_dir / "matrix2.json").exists():
            print(f"Epoch {epoch}: missing estep.json/matrix2.json, skipping")
            continue

        scored = compute_epoch_balance(epoch_dir, paper_ids)
        out_path = epoch_dir / "group_balance.json"
        out_path.write_text(json.dumps(scored, indent=2) + "\n")

        print(f"Epoch {epoch}: group balance ({len(paper_ids)} papers represented, matrix-checked)")
        for group in scored:
            print(
                f"  {group['group_balance']:5.1f}%  {group['group_id']} "
                f"({group['member_count']} members): {group['overarching_question']!r}"
            )
        print(f"wrote {out_path}\n")


if __name__ == "__main__":
    main()
