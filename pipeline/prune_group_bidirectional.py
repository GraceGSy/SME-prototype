"""Keep only reciprocal Claude judgments from group_matches.json.

Usage:
    python3 prune_group_bidirectional.py
"""
from __future__ import annotations

import json

from pipeline_paths import output_dir
from question_matching import reciprocal_question_links

OUTPUT_DIR = output_dir()


def find_bidirectional(entries: list[dict]) -> list[dict]:
    return reciprocal_question_links(entries)


def main() -> None:
    entries = json.loads((OUTPUT_DIR / "group_matches.json").read_text())
    bidirectional = find_bidirectional(entries)
    total_candidates = sum(len(e["matches"]) for e in entries)
    print(
        f"{len(entries)} groups, {total_candidates} Claude judgments -> "
        f"{len(bidirectional)} reciprocal links"
    )

    out_path = OUTPUT_DIR / "bidirectional_group_matches.json"
    out_path.write_text(json.dumps(bidirectional, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
