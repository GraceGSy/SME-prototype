"""Alternative 1: same per-paper MILP as reassign_via_milp_per_paper.py, but
with NO group-size-balance penalty at all -- pure preference-cost
minimization (item_rank + group_rank only). Group sizes are whatever falls
out of the assignment; nothing in the objective or constraints pushes them
toward the ~4-per-group target.

Does NOT overwrite reassign_via_milp_per_paper.py's output or anything else
-- written to its own new file,
output/sections/milp_reassignment_per_paper_no_penalty.json.

Pure local computation over already-saved JSON -- no Claude API calls.

Usage:
    python3 reassign_via_milp_per_paper_no_penalty.py
"""
from __future__ import annotations

from reassign_via_milp_per_paper import run_per_paper


def main() -> None:
    run_per_paper("milp_reassignment_per_paper_no_penalty.json", penalty_mode="none")


if __name__ == "__main__":
    main()
