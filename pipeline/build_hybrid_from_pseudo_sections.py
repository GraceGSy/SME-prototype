"""Builds <output_dir>/<paper_id>.json from a folder of "stage-0" pseudo-section
files (one per paper): a proper full-paper array of real sections, each
already split into its own real paragraphs, in order.

This is the entry point for the "hybrid" pipeline track, where paragraph
splitting has ALREADY been done externally (e.g. by a Claude Skill run
separately per paper) -- see e.g. SME/papers/papers1/stage-0-pseudo-section-files/
or SME/papers/papers3/stage-0-pseudo-section-files/ for the expected input
shape, one file per paper:

  [
    {
      "section_name": "Introduction",
      "section_number": "1",           # or null for unnumbered sections
      "paragraphs": [
        {"paragraph_number": 1, "text": "..."},
        ...
      ],
      "question_this_section_answers": "..."   # NOT used here -- see below
    },
    ...
  ]

Only structure is built here: sections + paragraphs, with fresh `id`s
("s1", "s2", ...) and `section_id`s assigned in reading order. Both
sections' and paragraphs' `tag` fields are left as "" deliberately --
despite its name, `question_this_section_answers` is NOT copied into
anything here. Tagging is two separate, later steps:
  - section tags: the annotate-section-questions-given-paragraphs skill
    (see tag_hybrid_sections.py, which implements the skill directly)
  - paragraph tags: tag_hybrid_paragraphs.py

Usage:
    python3 build_hybrid_from_pseudo_sections.py SOURCE_DIR [PAPER_ID ...]

SOURCE_DIR: directory containing "<paper_id>-sections-with-paragraphs-and-
    questions-no-appendices.json" files, one per paper. All such files in
    the directory are processed unless specific PAPER_IDs are passed.
Output directory: $SME_OUTPUT_DIR, or output/sections next to this script
    if unset.

If <output_dir>/<paper_id>.json already exists, its `paper_id` and `title`
fields are preserved (only `sections`/`paragraphs` are replaced) -- useful
when an earlier extraction pass already recorded the paper's real title.
Otherwise both default to the paper_id derived from the source filename,
since the source files don't carry a title themselves; hand-edit the
written file's `title` afterward if you want the paper's real title on
record.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

OUTPUT_DIR = Path(os.environ.get("SME_OUTPUT_DIR", str(Path(__file__).resolve().parent / "output" / "sections")))

SOURCE_FILENAME_SUFFIX = "-sections-with-paragraphs-and-questions-no-appendices.json"


def _paper_id_from_filename(path: Path) -> str:
    name = path.name
    if not name.endswith(SOURCE_FILENAME_SUFFIX):
        raise ValueError(f"{name!r} doesn't end with the expected suffix {SOURCE_FILENAME_SUFFIX!r}")
    return name[: -len(SOURCE_FILENAME_SUFFIX)]


def build_paper(paper_id: str, source_sections: list[dict], existing: dict | None) -> dict:
    new_sections = []
    new_paragraphs = []
    para_counter = 1

    for i, src_sec in enumerate(source_sections, start=1):
        section_id = f"s{i}"
        src_paragraphs = sorted(src_sec["paragraphs"], key=lambda p: p["paragraph_number"])

        for p in src_paragraphs:
            para_id = f"pa{para_counter}"
            para_counter += 1
            new_paragraphs.append({
                "id": para_id,
                "title": "",
                "tag": "",
                "text": p["text"],
                "section_id": section_id,
            })

        section_text = "\n\n".join(p["text"] for p in src_paragraphs)
        new_sections.append({
            "id": section_id,
            "title": src_sec["section_name"],
            "tag": "",
            "text": section_text,
            "section_id": "",
        })

    return {
        "paper_id": existing["paper_id"] if existing else paper_id,
        "title": existing["title"] if existing else paper_id,
        "sections": new_sections,
        "paragraphs": new_paragraphs,
    }


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: python3 {Path(__file__).name} SOURCE_DIR [PAPER_ID ...]", file=sys.stderr)
        raise SystemExit(1)

    source_dir = Path(sys.argv[1])
    requested_ids = set(sys.argv[2:])

    source_files = sorted(source_dir.glob(f"*{SOURCE_FILENAME_SUFFIX}"))
    if requested_ids:
        source_files = [f for f in source_files if _paper_id_from_filename(f) in requested_ids]

    if not source_files:
        print(f"No stage-0 pseudo-section files found in {source_dir}", file=sys.stderr)
        raise SystemExit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for source_path in source_files:
        paper_id = _paper_id_from_filename(source_path)
        source_sections = json.loads(source_path.read_text())

        target_path = OUTPUT_DIR / f"{paper_id}.json"
        existing = json.loads(target_path.read_text()) if target_path.exists() else None

        built = build_paper(paper_id, source_sections, existing)
        target_path.write_text(json.dumps(built, indent=2) + "\n")

        manifest.append({"paper_id": built["paper_id"], "title": built["title"], "file": f"{paper_id}.json"})
        print(f"[{paper_id}] {len(built['sections'])} sections, {len(built['paragraphs'])} paragraphs -- wrote {target_path}")

    manifest_path = OUTPUT_DIR / "manifest.json"
    if manifest_path.exists():
        existing_manifest = {m["paper_id"]: m for m in json.loads(manifest_path.read_text())}
        for m in manifest:
            existing_manifest[m["paper_id"]] = m
        manifest = list(existing_manifest.values())
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nwrote {manifest_path} ({len(manifest)} entries)")


if __name__ == "__main__":
    main()
