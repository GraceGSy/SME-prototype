"""Prunes group_matches.json (the directional top-3 candidate file from
match_groups.py) down to only bidirectional (mutual) matches: a link between
group A and group B is kept only if B appears in A's candidate list AND A
appears in B's candidate list.

Pure local computation over already-saved JSON -- no Claude API calls.

Usage:
    python3 prune_group_bidirectional.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"


def find_bidirectional(entries: list[dict]) -> list[dict]:
    index = {e["group_id"]: e for e in entries}
    seen_pairs: set[frozenset] = set()
    bidirectional = []

    for entry in entries:
        a_id = entry["group_id"]
        for m in entry["matches"]:
            b_id = m["group_id"]
            b_entry = index.get(b_id)
            if b_entry is None:
                continue
            is_mutual = any(mm["group_id"] == a_id for mm in b_entry["matches"])
            if not is_mutual:
                continue
            pair_key = frozenset((a_id, b_id))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            bidirectional.append({
                "group_a": a_id, "question_a": entry["overarching_question"],
                "group_b": b_id, "question_b": m["overarching_question"],
                "similarity": m["similarity"],
            })
    return bidirectional


def main() -> None:
    entries = json.loads((OUTPUT_DIR / "group_matches.json").read_text())
    bidirectional = find_bidirectional(entries)
    total_candidates = sum(len(e["matches"]) for e in entries)
    print(f"{len(entries)} groups, {total_candidates} candidates -> {len(bidirectional)} bidirectional links")

    out_path = OUTPUT_DIR / "bidirectional_group_matches.json"
    out_path.write_text(json.dumps(bidirectional, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
