"""Prunes tag_matches.json (the directional top-3-per-other-paper candidate
file from match_tags.py) down to only bidirectional (mutual) matches: a link
between unit X in paper A and unit Y in paper B is kept only if Y appears in
X's candidate list AND X appears in Y's candidate list.

Pure local computation over already-saved JSON -- no Claude API calls.

Output uses the same field names as the older match_sections.py's links.json
(paper_a/section_a/title_a/tag_a/paper_b/section_b/title_b/tag_b/similarity)
so the existing viewer pattern can be reused with minimal changes.

Usage:
    python3 prune_bidirectional.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from section_schema import GRANULARITIES, SectionedPaper

OUTPUT_DIR = Path(os.environ.get("SME_OUTPUT_DIR", str(Path(__file__).resolve().parent / "output" / "sections")))


def _load_paper(path: Path) -> SectionedPaper:
    return SectionedPaper.model_validate(json.loads(path.read_text()))


def _title_lookup(papers: dict[str, SectionedPaper], granularity: str) -> dict[tuple[str, str], str]:
    lookup = {}
    for paper_id, paper in papers.items():
        for unit in getattr(paper, granularity):
            lookup[(paper_id, unit.id)] = unit.title
    return lookup


def find_bidirectional(entries: list[dict], titles: dict[tuple[str, str], str]) -> list[dict]:
    index = {(e["paper"], e["unit_id"]): e for e in entries}
    seen_pairs: set[frozenset] = set()
    bidirectional = []

    for entry in entries:
        a_key = (entry["paper"], entry["unit_id"])
        for m in entry["matches"]:
            b_key = (m["paper"], m["unit_id"])
            b_entry = index.get(b_key)
            if b_entry is None:
                continue
            is_mutual = any((mm["paper"], mm["unit_id"]) == a_key for mm in b_entry["matches"])
            if not is_mutual:
                continue
            pair_key = frozenset((a_key, b_key))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            bidirectional.append({
                "paper_a": a_key[0], "section_a": a_key[1], "title_a": titles.get(a_key, ""), "tag_a": entry["tag"],
                "paper_b": b_key[0], "section_b": b_key[1], "title_b": titles.get(b_key, ""), "tag_b": m["tag"],
                "similarity": m["similarity"],
            })
    return bidirectional


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    papers = {m["paper_id"]: _load_paper(OUTPUT_DIR / m["file"]) for m in manifest}
    tag_matches = json.loads((OUTPUT_DIR / "tag_matches.json").read_text())

    output: dict[str, list[dict]] = {}
    for granularity in GRANULARITIES:
        titles = _title_lookup(papers, granularity)
        entries = tag_matches.get(granularity, [])
        bidirectional = find_bidirectional(entries, titles)
        output[granularity] = bidirectional
        print(f"[{granularity}] {len(entries)} units, {sum(len(e['matches']) for e in entries)} candidates -> {len(bidirectional)} bidirectional links")

    out_path = OUTPUT_DIR / "bidirectional_matches.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
