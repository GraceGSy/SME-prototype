"""Groups linked quotes (sections/paragraphs) into connected components: if
quote A is linked to quote B (via bidirectional_matches.json), they belong in
the same group -- and this is transitive: if A-B and B-C are both links, A,
B, and C all end up in one group even without a direct A-C link.

Pure local computation over the already-saved bidirectional_matches.json plus
each paper's own JSON (for title/tag lookup) -- no Claude API calls.

Usage:
    python3 group_matches.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pipeline_paths import output_dir
from section_schema import GRANULARITIES, SectionedPaper

OUTPUT_DIR = output_dir()


class _DSU:
    def __init__(self):
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[rx] = ry


def _load_paper(path: Path) -> SectionedPaper:
    return SectionedPaper.model_validate(json.loads(path.read_text()))


def _unit_lookup(
    papers: dict[str, SectionedPaper], granularity: str
) -> dict[tuple[str, str], dict]:
    """(paper_id, unit_id) -> {"title":..., "tag":...} for every unit at this granularity."""
    lookup = {}
    for paper_id, paper in papers.items():
        for unit in getattr(paper, granularity):
            lookup[(paper_id, unit.id)] = {
                "title": unit.title,
                "tag": unit.tag,
                "parent_section_id": unit.parent_section_id,
            }
    return lookup


def group_links(links: list[dict], units: dict[tuple[str, str], dict]) -> list[dict]:
    dsu = _DSU()
    for link in links:
        a_key = (link["paper_a"], link["section_a"])
        b_key = (link["paper_b"], link["section_b"])
        dsu.union(a_key, b_key)

    members_by_root: dict = {}
    links_by_root: dict = {}
    for link in links:
        a_key = (link["paper_a"], link["section_a"])
        b_key = (link["paper_b"], link["section_b"])
        root = dsu.find(a_key)
        members_by_root.setdefault(root, set()).update((a_key, b_key))
        links_by_root.setdefault(root, []).append(link)

    groups = []
    for root, member_keys in members_by_root.items():
        members = [
            {"paper": p, "unit_id": u, **units.get((p, u), {"title": "", "tag": ""})}
            for p, u in sorted(member_keys)
        ]
        groups.append({"members": members, "links": links_by_root[root]})

    groups.sort(key=lambda g: -len(g["members"]))
    for i, g in enumerate(groups, start=1):
        g["group_id"] = f"group_{i}"
    # group_id first for readability
    return [
        {"group_id": g["group_id"], "members": g["members"], "links": g["links"]}
        for g in groups
    ]


# Grouping is transitive (A-B + B-C merges A, B, and C even with no direct A-C
# link), so on a dense-enough link graph connected components collapse into one
# giant blob. Filtering to only the stronger links before grouping keeps groups
# meaningfully tight. Paragraphs need a higher bar than sections since they're
# shorter, more numerous, and more prone to generic-question false ties.
SIMILARITY_THRESHOLDS = {
    "sections": float(os.environ.get("SME_SECTION_GROUP_THRESHOLD", "0.33")),
    "paragraphs": float(os.environ.get("SME_PARAGRAPH_GROUP_THRESHOLD", "0.45")),
}


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    papers = {m["paper_id"]: _load_paper(OUTPUT_DIR / m["file"]) for m in manifest}
    bidirectional = json.loads((OUTPUT_DIR / "bidirectional_matches.json").read_text())

    output: dict[str, list[dict]] = {}
    for granularity in GRANULARITIES:
        units = _unit_lookup(papers, granularity)
        threshold = SIMILARITY_THRESHOLDS.get(granularity, 0.0)
        all_links = bidirectional.get(granularity, [])
        links = [l for l in all_links if l["similarity"] >= threshold]
        groups = group_links(links, units)
        output[granularity] = groups
        sizes = [len(g["members"]) for g in groups]
        print(
            f"[{granularity}] {len(all_links)} links -> {len(links)} above {threshold} -> {len(groups)} groups (sizes: {sizes})"
        )

    out_path = OUTPUT_DIR / "quote_groups.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
