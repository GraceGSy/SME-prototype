#!/usr/bin/env python3
"""
Iterates over p1-p2-section-mapping.json, which maps top-level sections of
abstractexplorer.pdf ("p1") to their closest corresponding section in
corpusstudio.pdf ("p2"), and writes p1-p2-section-mapping-enumerated.json,
an identical copy with an added "enumerate" field (0-indexed) on each item.

Usage:
    python3 iterate_section_mapping.py
    python3 iterate_section_mapping.py path/to/other-mapping.json
"""

import json
import sys
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "p1-p2-section-mapping.json"


def load_mapping(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def iterate_mapping(mapping: list[dict]) -> None:
    for i, item in enumerate(mapping, start=1):
        ae_section = item.get("abstractexplorer_section", "?")
        cs_section = item.get("corpusstudio_section", "?")
        basis = item.get("basis", "")

        print(f"[{i}] {ae_section}")
        print(f"    -> {cs_section}")
        if basis:
            print(f"    basis: {basis}")
        print()


def enumerate_mapping(mapping: list[dict]) -> list[dict]:
    enumerated = []
    for i, item in enumerate(mapping):
        new_item = dict(item)
        new_item["enumerate"] = i
        enumerated.append(new_item)
    return enumerated


def write_enumerated(mapping: list[dict], source_path: Path) -> Path:
    out_path = source_path.parent / f"{source_path.stem}-enumerated.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return out_path


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    mapping = load_mapping(path)
    iterate_mapping(mapping)
    print(f"Total mapped section pairs: {len(mapping)}")

    enumerated = enumerate_mapping(mapping)
    out_path = write_enumerated(enumerated, path)
    print(f"Wrote enumerated mapping to: {out_path}")


if __name__ == "__main__":
    main()
