"""Synthesize each initial super-group question from its complete paragraphs."""
from __future__ import annotations

import json

from pipeline_paths import output_dir
from question_synthesis import synthesize_question
from section_schema import SectionedPaper

OUTPUT_DIR = output_dir()
CACHE_DIR = OUTPUT_DIR / "_cache" / "super_group_summaries"


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
    path = OUTPUT_DIR / "group_of_groups.json"
    super_groups = json.loads(path.read_text(encoding="utf-8"))
    quote_groups = json.loads((OUTPUT_DIR / "quote_groups.json").read_text(encoding="utf-8"))
    group_by_id = {group["group_id"]: group for group in quote_groups.get("paragraphs", [])}
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    lookup = _paragraph_lookup(manifest)

    print(f"Preparing {len(super_groups)} merged and carried question groups ...")
    for super_group in super_groups:
        member_keys: set[tuple[str, str]] = set()
        previous_questions = []
        for member_group in super_group["members"]:
            group = group_by_id.get(member_group["group_id"])
            if not group:
                continue
            previous_questions.append(group.get("overarching_question", ""))
            member_keys.update(
                (member["paper"], member["unit_id"]) for member in group["members"]
            )
        paragraphs = [lookup[key] for key in sorted(member_keys) if key in lookup]
        if not super_group.get("is_merged", len(super_group["members"]) > 1):
            question = previous_questions[0] if previous_questions else ""
            super_group["overarching_question"] = question
            super_group["synthesis_provenance"] = {
                "overarching_question": question,
                "type": "singleton_carryover",
                "input_group_ids": [
                    member["group_id"] for member in super_group["members"]
                ],
                "input_paragraph_ids": [
                    f"{paragraph['paper']}:{paragraph['unit_id']}"
                    for paragraph in paragraphs
                ],
            }
            print(
                f"  {super_group['super_group_id']} carried forward unchanged "
                f"({len(paragraphs)} complete paragraphs)"
            )
            continue
        synthesis = synthesize_question(
            super_group["super_group_id"],
            paragraphs,
            CACHE_DIR,
            previous_questions=previous_questions,
        )
        super_group["overarching_question"] = synthesis["overarching_question"]
        super_group["synthesis_provenance"] = synthesis
        print(
            f"  {super_group['super_group_id']} merged "
            f"({len(paragraphs)} complete paragraphs): "
            f"{super_group['overarching_question']!r}"
        )

    path.write_text(json.dumps(super_groups, indent=2), encoding="utf-8")
    print(f"\nupdated {path}")


if __name__ == "__main__":
    main()
