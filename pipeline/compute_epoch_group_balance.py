"""Computes the group-balance metric for each epoch produced by any of the
refine_with_epoch_*.py variants, using the same simple formula as
compute_group_balance.py's iteration version: balance is the percentage of
papers with at least one paragraph in the group (from that epoch's E-step
membership), each paper counting at most once regardless of how many of its
paragraphs are assigned.

Balance = (papers represented) / (total papers) * 100, sorted highest
first, written to epoch<N>/group_balance.json alongside that epoch's
estep/mstep files. Pure local computation over already-saved JSON -- no
Claude API calls.

Works against any epoch-refinement run directory that has the
epoch<N>/{estep,mstep}.json shape -- e.g. refine_with_epoch_matrices.py's
epoch_matrix_refinement/ (the default), refine_with_epoch_random_seed.py's
epoch_random_seed_refinement/, or refine_with_epoch_matrix1_reassign.py's
epoch_matrix1_reassign_refinement/ -- pass the directory name as an
argument. The number of epochs is auto-detected from however many
epoch<N> subdirectories actually exist, so this works unmodified whether a
run did 3 epochs or 5.

Usage:
    python3 compute_epoch_group_balance.py [run_dir_name]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"
RUN_DIR_NAME = sys.argv[1] if len(sys.argv) > 1 else "epoch_matrix_refinement"
RUN_DIR = OUTPUT_DIR / RUN_DIR_NAME


def compute_epoch_balance(epoch_dir: Path, paper_ids: list[str]) -> list[dict]:
    estep = json.loads((epoch_dir / "estep.json").read_text())
    mstep = json.loads((epoch_dir / "mstep.json").read_text())
    question_by_group = {g["group_id"]: g["overarching_question"] for g in mstep["groups"]}

    scored = []
    for group in estep["groups"]:
        gid = group["group_id"]
        represented_papers = {member["paper"] for member in group["members"]}
        paper_count = sum(paper_id in represented_papers for paper_id in paper_ids)

        scored.append({
            "group_id": gid,
            "overarching_question": question_by_group.get(gid, ""),
            "group_balance": round(paper_count / len(paper_ids) * 100, 1) if paper_ids else 0.0,
            "member_count": len(group["members"]),
        })

    scored.sort(key=lambda group: -group["group_balance"])
    return scored


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    paper_ids = [m["paper_id"] for m in manifest]

    epoch = 1
    while True:
        epoch_dir = RUN_DIR / f"epoch{epoch}"
        if not (epoch_dir / "estep.json").exists() or not (epoch_dir / "mstep.json").exists():
            break

        scored = compute_epoch_balance(epoch_dir, paper_ids)
        out_path = epoch_dir / "group_balance.json"
        out_path.write_text(json.dumps(scored, indent=2) + "\n")

        print(f"Epoch {epoch}: group balance ({len(paper_ids)} papers represented)")
        for group in scored:
            print(
                f"  {group['group_balance']:5.1f}%  {group['group_id']} "
                f"({group['member_count']} members): {group['overarching_question']!r}"
            )
        print(f"wrote {out_path}\n")
        epoch += 1

    if epoch == 1:
        print(f"No epoch<N>/estep.json+mstep.json found under {RUN_DIR}")


if __name__ == "__main__":
    main()
