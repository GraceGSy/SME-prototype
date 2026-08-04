"""Ask Claude for directional conceptual matches between group questions.

Deterministic lexical similarity is attached to every Claude-selected match.
Reciprocity and the lexical threshold are applied by later stages.

Usage:
    python3 match_groups.py
"""
from __future__ import annotations

import json
import os

from pipeline_paths import output_dir
from question_matching import DEFAULT_MODEL, directional_question_matches

OUTPUT_DIR = output_dir()
TOP_K = int(os.environ.get("SME_MATCH_TOP_K", "3"))
CACHE_DIR = OUTPUT_DIR / "_cache" / "group_question_matches"


def match_groups(
    groups: list[dict],
    k: int = TOP_K,
    *,
    model: str = DEFAULT_MODEL,
    client=None,
    cache_dir=None,
) -> list[dict]:
    return directional_question_matches(
        groups,
        cache_dir or CACHE_DIR,
        label="initial_groups",
        top_k=k,
        model=model,
        client=client,
    )


def main() -> None:
    path = OUTPUT_DIR / "quote_groups.json"
    data = json.loads(path.read_text())
    groups = data.get("paragraphs", [])

    entries = match_groups(groups)
    total_matches = sum(len(e["matches"]) for e in entries)
    print(
        f"{len(entries)} groups, {total_matches} Claude-selected directional "
        f"matches (maximum {TOP_K} each)"
    )

    out_path = OUTPUT_DIR / "group_matches.json"
    out_path.write_text(json.dumps(entries, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
