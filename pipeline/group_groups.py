"""Groups paragraph-groups (each with a top-level "contribution" question)
into higher-level super-groups: if group A is linked to group B (via
bidirectional_group_matches.json), they belong in the same super-group --
transitive, same connected-components approach as group_matches.py, just
applied one level up (groups of groups instead of groups of quotes).

Pure local computation over already-saved bidirectional_group_matches.json
plus quote_groups.json (for overarching_question lookup) -- no Claude API
calls.

Usage:
    python3 group_groups.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"

# Same rationale as group_matches.py's SIMILARITY_THRESHOLDS: transitive
# grouping on a dense-enough link graph collapses into one giant blob, so
# filtering to only the stronger links before grouping keeps groups tight.
SIMILARITY_THRESHOLD = 0.33


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


def group_links(links: list[dict], questions: dict[str, str]) -> list[dict]:
    dsu = _DSU()
    for link in links:
        dsu.union(link["group_a"], link["group_b"])

    members_by_root: dict = {}
    links_by_root: dict = {}
    for link in links:
        root = dsu.find(link["group_a"])
        members_by_root.setdefault(root, set()).update((link["group_a"], link["group_b"]))
        links_by_root.setdefault(root, []).append(link)

    groups = []
    for root, member_ids in members_by_root.items():
        members = [
            {"group_id": gid, "overarching_question": questions.get(gid, "")}
            for gid in sorted(member_ids)
        ]
        groups.append({"members": members, "links": links_by_root[root]})

    groups.sort(key=lambda g: -len(g["members"]))
    for i, g in enumerate(groups, start=1):
        g["super_group_id"] = f"super_group_{i}"

    return [{"super_group_id": g["super_group_id"], "members": g["members"], "links": g["links"]} for g in groups]


def main() -> None:
    quote_groups = json.loads((OUTPUT_DIR / "quote_groups.json").read_text())
    questions = {g["group_id"]: g.get("overarching_question", "") for g in quote_groups.get("paragraphs", [])}

    all_links = json.loads((OUTPUT_DIR / "bidirectional_group_matches.json").read_text())
    links = [l for l in all_links if l["similarity"] >= SIMILARITY_THRESHOLD]
    groups = group_links(links, questions)

    sizes = [len(g["members"]) for g in groups]
    print(f"{len(all_links)} links -> {len(links)} above {SIMILARITY_THRESHOLD} -> {len(groups)} super-groups (sizes: {sizes})")

    out_path = OUTPUT_DIR / "group_of_groups.json"
    out_path.write_text(json.dumps(groups, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
