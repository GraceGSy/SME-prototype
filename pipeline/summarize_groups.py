"""Synthesize each paragraph-group question from complete source paragraphs."""
from __future__ import annotations

import json

from pipeline_paths import output_dir
from question_synthesis import synthesize_question
from section_schema import SectionedPaper

OUTPUT_DIR = output_dir()
CACHE_DIR = OUTPUT_DIR / "_cache" / "group_summaries"


def _paragraph_lookup(manifest: list[dict]) -> dict[tuple[str, str], dict]:
    lookup: dict[tuple[str, str], dict] = {}
    for entry in manifest:
        paper = SectionedPaper.model_validate(
            json.loads((OUTPUT_DIR / entry["file"]).read_text(encoding="utf-8"))
        )
        section_titles = {section.id: section.title for section in paper.sections}
        for paragraph in paper.paragraphs:
            lookup[(paper.paper_id, paragraph.id)] = {
                "paper": paper.paper_id,
                "unit_id": paragraph.id,
                "parent_section_id": paragraph.parent_section_id,
                "section_title": section_titles.get(paragraph.parent_section_id, ""),
                "tag": paragraph.tag,
                "text": paragraph.text,
            }
    return lookup


def main() -> None:
    path = OUTPUT_DIR / "quote_groups.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    lookup = _paragraph_lookup(manifest)

    groups = data.get("paragraphs", [])
    print(f"Summarizing {len(groups)} paragraph groups from complete paragraphs ...")
    for group in groups:
        paragraphs = [
            lookup[(member["paper"], member["unit_id"])]
            for member in group["members"]
            if (member["paper"], member["unit_id"]) in lookup
        ]
        synthesis = synthesize_question(group["group_id"], paragraphs, CACHE_DIR)
        group["overarching_question"] = synthesis["overarching_question"]
        group["synthesis_provenance"] = synthesis
        print(
            f"  {group['group_id']} ({len(paragraphs)} complete paragraphs): "
            f"{group['overarching_question']!r}"
        )

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nupdated {path}")


if __name__ == "__main__":
    main()
