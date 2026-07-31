"""Matches top-level "contribution" questions -- each paragraph group's
overarching_question (see summarize_groups.py) -- against each other: for
every group, find the 3 other groups whose overarching_question is most
similar, each with a similarity score in [0, 1].

Unlike match_tags.py there's no "other paper" dimension to iterate over here:
each group already spans multiple papers, so this simply finds the group's
top 3 most similar OTHER groups overall. Directional and NOT reciprocity-
filtered (see prune_group_bidirectional.py for that) -- saved as an interim
candidate file, not a final result.

Similarity is computed the same way as elsewhere in this project:
text_similarity() (lexical Jaccard + character-ratio blend) on the
overarching_question strings.

Pure local computation over already-saved quote_groups.json -- no Claude API
calls.

Usage:
    python3 match_groups.py
"""
from __future__ import annotations

import json
from pathlib import Path

from align_graphs import text_similarity

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"
TOP_K = 3


def match_groups(groups: list[dict], k: int = TOP_K) -> list[dict]:
    entries = []
    for group in groups:
        scored = [
            (other, text_similarity(group["overarching_question"], other["overarching_question"]))
            for other in groups
            if other["group_id"] != group["group_id"]
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        matches = [
            {
                "group_id": other["group_id"],
                "overarching_question": other["overarching_question"],
                "similarity": round(score, 3),
            }
            for other, score in scored[:k]
        ]
        entries.append({
            "group_id": group["group_id"],
            "overarching_question": group["overarching_question"],
            "matches": matches,
        })
    return entries


def main() -> None:
    path = OUTPUT_DIR / "quote_groups.json"
    data = json.loads(path.read_text())
    groups = data.get("paragraphs", [])

    entries = match_groups(groups)
    total_matches = sum(len(e["matches"]) for e in entries)
    print(f"{len(entries)} groups, {total_matches} candidate matches (top {TOP_K} each)")

    out_path = OUTPUT_DIR / "group_matches.json"
    out_path.write_text(json.dumps(entries, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
