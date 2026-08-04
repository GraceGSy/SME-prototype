"""Fills in each section's real body text by locally slicing the raw
extracted PDF text between consecutive section headings -- no LLM call, so
the viewer shows the paper's actual words, not a model paraphrase.

Usage:
    python3 attach_section_text.py
"""
from __future__ import annotations

import json

from pdf_text import extract_pdf_text
from pipeline_paths import output_dir, papers_dir
from section_schema import SectionedPaper
from text_locate import slice_by_markers

PAPERS_DIR = papers_dir()
OUTPUT_DIR = output_dir()

MISSING_PLACEHOLDER = "(could not automatically locate this section's text -- likely a column-layout edge case in PDF extraction)"


def attach_text(sectioned: SectionedPaper, raw_text: str) -> tuple[SectionedPaper, list[str]]:
    slices = slice_by_markers(raw_text, [sec.title for sec in sectioned.sections])

    new_sections = []
    missing = []
    for sec, sliced in zip(sectioned.sections, slices):
        if sliced is None:
            missing.append(sec.title)
            new_sections.append(sec.model_copy(update={"text": MISSING_PLACEHOLDER}))
        else:
            new_sections.append(sec.model_copy(update={"text": sliced}))

    return sectioned.model_copy(update={"sections": new_sections}), missing


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    for m in manifest:
        paper_id = m["paper_id"]
        pdf_path = PAPERS_DIR / f"{paper_id}.pdf"
        raw_text = extract_pdf_text(str(pdf_path))

        path = OUTPUT_DIR / m["file"]
        sectioned = SectionedPaper.model_validate(json.loads(path.read_text()))
        updated, missing = attach_text(sectioned, raw_text)
        path.write_text(json.dumps(updated.model_dump(), indent=2))

        ok = len(updated.sections) - len(missing)
        print(f"[{paper_id}] attached text to {ok}/{len(updated.sections)} sections" + (f"; could not locate: {missing}" if missing else ""))


if __name__ == "__main__":
    main()
