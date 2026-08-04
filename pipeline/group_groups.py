"""Merge reciprocal, lexically qualified question groups into components.

Every input group appears in the output. Groups without a qualifying merge
edge are carried forward as singletons rather than silently disappearing.

Usage:
    python3 group_groups.py
"""

from __future__ import annotations

import json
import os

from pipeline_paths import output_dir
from question_matching import eligible_merge_links

OUTPUT_DIR = output_dir()

# Same rationale as group_matches.py's SIMILARITY_THRESHOLDS: transitive
# grouping on a dense-enough link graph collapses into one giant blob, so
# filtering to only the stronger links before grouping keeps groups tight.
SIMILARITY_THRESHOLD = float(os.environ.get("SME_SUPERGROUP_THRESHOLD", "0.33"))


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


def group_links(groups: list[dict], links: list[dict]) -> list[dict]:
    group_ids = [group["group_id"] for group in groups]
    questions = {
        group["group_id"]: group.get("question")
        or group.get("overarching_question", "")
        for group in groups
    }
    dsu = _DSU()
    for group_id in group_ids:
        dsu.find(group_id)
    for link in links:
        dsu.union(link["group_a"], link["group_b"])

    members_by_root: dict[str, list[str]] = {}
    links_by_root: dict[str, list[dict]] = {}
    for group_id in group_ids:
        root = dsu.find(group_id)
        members_by_root.setdefault(root, []).append(group_id)
    for link in links:
        root = dsu.find(link["group_a"])
        links_by_root.setdefault(root, []).append(link)

    components = []
    merge_number = 1
    for member_ids in members_by_root.values():
        merged = len(member_ids) > 1
        component_id = f"super_group_{merge_number}" if merged else member_ids[0]
        if merged:
            merge_number += 1
        members = [
            {"group_id": gid, "overarching_question": questions.get(gid, "")}
            for gid in member_ids
        ]
        root = dsu.find(member_ids[0])
        components.append(
            {
                "super_group_id": component_id,
                "is_merged": merged,
                "parent_group_ids": list(member_ids),
                "members": members,
                "links": links_by_root.get(root, []),
            }
        )
    return components


def main() -> None:
    quote_groups = json.loads((OUTPUT_DIR / "quote_groups.json").read_text())
    paragraph_groups = quote_groups.get("paragraphs", [])

    all_links = json.loads(
        (OUTPUT_DIR / "bidirectional_group_matches.json").read_text()
    )
    links = eligible_merge_links(all_links, SIMILARITY_THRESHOLD)
    groups = group_links(paragraph_groups, links)

    sizes = [len(g["members"]) for g in groups]
    merged_count = sum(group["is_merged"] for group in groups)
    print(
        f"{len(all_links)} reciprocal Claude links -> {len(links)} at lexical "
        f"threshold {SIMILARITY_THRESHOLD} -> {len(groups)} active groups "
        f"({merged_count} merged, sizes: {sizes})"
    )

    out_path = OUTPUT_DIR / "group_of_groups.json"
    out_path.write_text(json.dumps(groups, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
