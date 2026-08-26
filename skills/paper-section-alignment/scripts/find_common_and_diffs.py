#!/usr/bin/env python3
"""
Compares a paper1->paper2 section mapping against an independently-derived
paper2->paper1 section mapping, and classifies every pairing into three
buckets:

  - common-section-structure.json   pairings both directions agree on
                                     (matched on paper1_section_number +
                                     paper2_section_number)
  - alignable-section-diffs.json    pairings found in only one direction,
                                     where both papers still name an actual
                                     section (neither number is null)
  - non-alignable-section-diffs.json pairings found in only one direction,
                                     where one paper's section is null --
                                     i.e. that paper has no counterpart at
                                     all, not just an unconfirmed one

Matching is done on section NUMBER, not name. Two independent reasoning
passes may annotate the same section with slightly different text (e.g.
one pass appends a subsection reference and the other doesn't) even when
they mean the same section, so number is the more reliable join key.

Usage:
    python3 find_common_and_diffs.py p1-p2-section-mapping.json p2-p1-section-mapping.json [output_dir]
"""

import json
import sys
from pathlib import Path


def load_mapping(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array of mapping entries")
    return data


def norm(value):
    """Normalize a value for comparison: None/empty-ish stays None, else stripped string."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def number_key(entry: dict) -> tuple:
    return (norm(entry.get("paper1_section_number")), norm(entry.get("paper2_section_number")))


def is_non_alignable(entry: dict) -> bool:
    """True if either side of the pairing has no section at all (null number)."""
    p1_num = norm(entry.get("paper1_section_number"))
    p2_num = norm(entry.get("paper2_section_number"))
    return p1_num is None or p2_num is None


def classify(p1_p2: list[dict], p2_p1: list[dict]):
    p1_p2_keys = {number_key(e) for e in p1_p2}
    p2_p1_keys = {number_key(e) for e in p2_p1}

    common_keys = p1_p2_keys & p2_p1_keys

    common = [e for e in p1_p2 if number_key(e) in common_keys]

    # Diffs: everything from either direction that isn't in the common set.
    # Prefer the p1->p2 phrasing when a key happens to appear in both diff
    # sources (shouldn't normally happen once common_keys is removed, but
    # guard against duplicate/near-duplicate entries within a single file).
    seen_diff_keys = set()
    alignable = []
    non_alignable = []

    for source in (p1_p2, p2_p1):
        for entry in source:
            key = number_key(entry)
            if key in common_keys:
                continue
            if key in seen_diff_keys:
                continue
            seen_diff_keys.add(key)
            if is_non_alignable(entry):
                non_alignable.append(entry)
            else:
                alignable.append(entry)

    return common, alignable, non_alignable


def write_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    p1_p2_path = Path(sys.argv[1])
    p2_p1_path = Path(sys.argv[2])
    output_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else p1_p2_path.parent

    p1_p2 = load_mapping(p1_p2_path)
    p2_p1 = load_mapping(p2_p1_path)

    common, alignable, non_alignable = classify(p1_p2, p2_p1)

    write_json(output_dir / "common-section-structure.json", common)
    write_json(output_dir / "alignable-section-diffs.json", alignable)
    write_json(output_dir / "non-alignable-section-diffs.json", non_alignable)

    total = len(p1_p2) + len(p2_p1)
    print(f"paper1->paper2 pairings: {len(p1_p2)}")
    print(f"paper2->paper1 pairings: {len(p2_p1)}")
    print(f"Bidirectional (common) matches: {len(common)}")
    for e in common:
        print(f"  [common]        {e.get('paper1_section_name')} ({e.get('paper1_section_number')})  <->  {e.get('paper2_section_name')} ({e.get('paper2_section_number')})")
    print(f"Alignable diffs (both sides named, unconfirmed): {len(alignable)}")
    for e in alignable:
        print(f"  [alignable]     {e.get('paper1_section_name')} ({e.get('paper1_section_number')})  <->  {e.get('paper2_section_name')} ({e.get('paper2_section_number')})")
    print(f"Non-alignable diffs (no counterpart at all): {len(non_alignable)}")
    for e in non_alignable:
        print(f"  [non-alignable] {e.get('paper1_section_name')} ({e.get('paper1_section_number')})  <->  {e.get('paper2_section_name')} ({e.get('paper2_section_number')})")

    print(f"\nWrote common-section-structure.json, alignable-section-diffs.json, non-alignable-section-diffs.json to {output_dir}")


if __name__ == "__main__":
    main()
