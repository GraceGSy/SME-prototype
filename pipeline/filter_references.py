"""Removes each paper's References section (and any of its own paragraphs)
from an already-built hybrid output directory, in place -- the last stage
before running the matching/grouping/epoch pipeline against it.

A section titled exactly "References" (case-insensitive) is dropped from
`sections`, and every paragraph whose `section_id` pointed to it is dropped
from `paragraphs`. Remaining paragraph `id`s are NOT renumbered -- References
is expected to be a paper's last section, so removing it only truncates the
tail of the pa1..paN sequence. (If some paper's References section isn't
last, this leaves a gap in the numbering, which is harmless -- ids only need
to be unique and stable, not contiguous -- but worth knowing.)

A paper with no References section, or one that already has zero paragraphs
(e.g. because the upstream extraction never gave it any prose to begin
with), is left untouched either way.

Usage:
    SME_OUTPUT_DIR=... python3 filter_references.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from section_schema import SectionedPaper

OUTPUT_DIR = Path(os.environ.get("SME_OUTPUT_DIR", str(Path(__file__).resolve().parent / "output" / "sections")))


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    for m in manifest:
        path = OUTPUT_DIR / m["file"]
        data = json.loads(path.read_text())

        ref_ids = {s["id"] for s in data["sections"] if s["title"].strip().lower() == "references"}
        if not ref_ids:
            print(f"[{m['paper_id']}] no References section -- unchanged")
            continue

        before_sections, before_paragraphs = len(data["sections"]), len(data["paragraphs"])
        data["sections"] = [s for s in data["sections"] if s["id"] not in ref_ids]
        data["paragraphs"] = [p for p in data["paragraphs"] if p["section_id"] not in ref_ids]

        SectionedPaper.model_validate(data)  # fail loudly rather than write something broken
        path.write_text(json.dumps(data, indent=2) + "\n")

        print(f"[{m['paper_id']}] sections {before_sections} -> {len(data['sections'])}, "
              f"paragraphs {before_paragraphs} -> {len(data['paragraphs'])}")


if __name__ == "__main__":
    main()
