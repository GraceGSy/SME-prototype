"""Alternative 2: same per-paper MILP as reassign_via_milp_per_paper.py, but
with a QUADRATIC group-size-balance penalty -- lambda * sum((s[k] -
target)^2) -- instead of the linear (L1, absolute-deviation) penalty. This
punishes large size deviations disproportionately more than small ones,
per the write-up's note on quadratic penalties. OR-Tools CP-SAT has no
native quadratic objective, but since group sizes and their deviation from
target are bounded integers, (s[k]-target)^2 is modeled exactly via
AddMultiplicationEquality (see reassign_via_milp.solve()'s "quadratic"
penalty_mode).

Does NOT overwrite reassign_via_milp_per_paper.py's output or anything else
-- written to its own new file,
output/sections/milp_reassignment_per_paper_quadratic.json.

Pure local computation over already-saved JSON -- no Claude API calls.

Usage:
    python3 reassign_via_milp_per_paper_quadratic.py
"""
from __future__ import annotations

from reassign_via_milp_per_paper import run_per_paper


def main() -> None:
    run_per_paper("milp_reassignment_per_paper_quadratic.json", penalty_mode="quadratic")


if __name__ == "__main__":
    main()
