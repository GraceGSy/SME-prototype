"""Normalize nested paragraph-question mappings into a final viewer snapshot."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from .final_snapshot import (
    SnapshotBuildError,
    compact,
    file_sha256,
    is_omitted_section,
    read_json,
    require,
    stable_id,
    write_json,
)


SNAPSHOT_FILE = "final_snapshot.json"
PAPER_FILE_MARKER = "-sections-with-paragraphs-and-questions-no-appendices"
ANNOTATED_SECTION_SUFFIX = re.compile(r"\s*\(paragraphs\s+\d+[^)]*\)\s*$", re.IGNORECASE)


def normalized_section_name(value: str) -> str:
    """Normalize display-only annotations while preserving section identity."""

    return compact(ANNOTATED_SECTION_SUFFIX.sub("", value)).casefold()


def paragraph_question(paragraph: dict[str, Any]) -> str:
    """Return an explicit paragraph-level question, never a section question."""

    for key in ("question_this_paragraph_answers", "paragraph_question", "question", "tag"):
        question = compact(str(paragraph.get(key) or ""))
        if question:
            return question
    return ""


def find_paper_file(paper_dir: Path, paper_id: str) -> Path:
    prefix = f"{paper_id}{PAPER_FILE_MARKER}"
    matches = sorted(
        path
        for path in paper_dir.glob("*.json")
        if path.stem.casefold().startswith(prefix.casefold())
    )
    require(len(matches) == 1, f"Expected one SME 2 paper file for {paper_id}, found {len(matches)}")
    return matches[0]


def load_papers(
    paper_dir: Path,
    metadata_dir: Path,
) -> tuple[
    list[dict[str, str]],
    dict[str, dict[str, Any]],
    dict[tuple[str, str, int], tuple[str, str]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, str]],
]:
    metadata_manifest = read_json(metadata_dir / "manifest.json")
    require(isinstance(metadata_manifest, list) and metadata_manifest, "Metadata manifest must be a non-empty list")

    manifest: list[dict[str, str]] = []
    papers: dict[str, dict[str, Any]] = {}
    reference_lookup: dict[tuple[str, str, int], tuple[str, str]] = {}
    paragraph_lookup: dict[str, dict[str, Any]] = {}
    source_files: dict[str, dict[str, str]] = {}

    for paper_order, metadata in enumerate(metadata_manifest):
        paper_id = str(metadata.get("paper_id") or "")
        title = str(metadata.get("title") or "")
        require(bool(paper_id and title), "Metadata manifest entries need paper_id and title")
        source_path = find_paper_file(paper_dir, paper_id)
        raw_sections = read_json(source_path)
        require(isinstance(raw_sections, list), f"{source_path.name} must contain a section list")

        sections: list[dict[str, Any]] = []
        paragraphs: list[dict[str, Any]] = []
        paragraph_order = 0
        for section_position, raw_section in enumerate(raw_sections):
            section_name = compact(str(raw_section.get("section_name") or ""))
            if is_omitted_section("", section_name):
                continue
            raw_paragraphs = raw_section.get("paragraphs") or []
            require(isinstance(raw_paragraphs, list), f"{source_path.name}:{section_name} has no paragraph list")
            if not raw_paragraphs:
                continue

            section_id = stable_id("s", paper_id, str(section_position), section_name)
            section_paragraphs: list[str] = []
            seen_numbers: set[int] = set()
            for fallback_number, raw_paragraph in enumerate(raw_paragraphs):
                try:
                    paragraph_number = int(raw_paragraph.get("paragraph_number", fallback_number))
                except (TypeError, ValueError) as error:
                    raise SnapshotBuildError(
                        f"{source_path.name}:{section_name} has an invalid paragraph number"
                    ) from error
                require(
                    paragraph_number not in seen_numbers,
                    f"{source_path.name}:{section_name} repeats paragraph {paragraph_number}",
                )
                seen_numbers.add(paragraph_number)
                text = str(raw_paragraph.get("text") or "").strip()
                require(bool(text), f"{source_path.name}:{section_name}:{paragraph_number} has no text")

                unit_id = stable_id("p", paper_id, section_name, str(paragraph_number))
                key = f"{paper_id}:{unit_id}"
                question = paragraph_question(raw_paragraph)
                paragraph = {
                    "id": unit_id,
                    "title": "",
                    "tag": "",
                    "text": text,
                    "prev_relation": "",
                    "next_relation": "",
                    "section_id": section_id,
                    "order": paragraph_order,
                    "paragraph_number": paragraph_number,
                    "group_ids": [],
                    "singleton_ids": [],
                    "source_paragraph_question": question,
                }
                paragraphs.append(paragraph)
                paragraph_lookup[key] = paragraph
                reference_key = (paper_id, normalized_section_name(section_name), paragraph_number)
                require(reference_key not in reference_lookup, f"Duplicate paragraph reference {reference_key}")
                reference_lookup[reference_key] = (paper_id, unit_id)
                section_paragraphs.append(text)
                paragraph_order += 1

            sections.append({
                "id": section_id,
                "title": section_name,
                "tag": compact(str(raw_section.get("question_this_section_answers") or "")),
                "text": "\n\n".join(section_paragraphs),
                "prev_relation": "",
                "next_relation": "",
                "section_id": "",
            })

        filename = f"{paper_id}.json"
        manifest.append({"paper_id": paper_id, "title": title, "file": filename})
        papers[paper_id] = {
            "paper_id": paper_id,
            "title": title,
            "sections": sections,
            "paragraphs": paragraphs,
            "paper_order": paper_order,
        }
        source_files[paper_id] = {"name": source_path.name, "sha256": file_sha256(source_path)}

    return manifest, papers, reference_lookup, paragraph_lookup, source_files


def parse_mapping_reference(section_number: str) -> tuple[str, str, int]:
    match = re.fullmatch(r"([^:]+)::(.+)::(\d+)", section_number)
    require(bool(match), f"Invalid paragraph mapping reference: {section_number!r}")
    assert match is not None
    return match.group(1), normalized_section_name(match.group(2)), int(match.group(3))


def load_question_mappings(
    structure_path: Path,
    reference_lookup: dict[tuple[str, str, int], tuple[str, str]],
    paragraph_lookup: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    rows = read_json(structure_path)
    require(isinstance(rows, list) and rows, "Nested structure must contain a non-empty row list")

    questions: dict[str, dict[str, Any]] = {}
    raw_entries = 0
    raw_memberships = 0
    text_mismatches = 0

    for row_position, row in enumerate(rows):
        role = str(row.get("role_slug") or "")
        for bucket, mapping_groups in row.items():
            if not bucket.startswith("paragraph_level_") or not isinstance(mapping_groups, list):
                continue
            for group_position, raw_group in enumerate(mapping_groups):
                raw_entries += 1
                question = compact(str(raw_group.get("question_the_sections_answer") or ""))
                require(bool(question), f"Row {row_position} {bucket} group {group_position} has no question")
                record = questions.setdefault(question, {"members": set(), "provenance": []})
                record["provenance"].append({
                    "role_slug": role,
                    "row_position": row_position,
                    "row_source": str(row.get("row_source") or ""),
                    "group_position": group_position,
                    "status": str(raw_group.get("pairing_status") or raw_group.get("diff_type") or ""),
                    "basis": str(raw_group.get("basis") or ""),
                    "ancestor_questions": raw_group.get("ancestor_questions") or [],
                })

                for outer_paper_id, paper_value in (raw_group.get("papers") or {}).items():
                    reference = parse_mapping_reference(str(paper_value.get("section_number") or ""))
                    require(
                        reference[0] == outer_paper_id,
                        f"Mapping paper {outer_paper_id} disagrees with reference {reference[0]}",
                    )
                    resolved = reference_lookup.get(reference)
                    require(bool(resolved), f"Unknown paragraph mapping reference: {reference}")
                    assert resolved is not None
                    member_key = f"{resolved[0]}:{resolved[1]}"
                    record["members"].add(member_key)
                    raw_memberships += 1

                    embedded = paper_value.get("paragraphs") or []
                    if embedded:
                        embedded_text = compact(str(embedded[0].get("text") or ""))
                        canonical_text = compact(str(paragraph_lookup[member_key]["text"]))
                        if embedded_text and embedded_text != canonical_text:
                            text_mismatches += 1

    require(bool(questions), "Nested structure contains no paragraph question mappings")
    return questions, {
        "mapping_entries": raw_entries,
        "mapping_memberships": raw_memberships,
        "canonical_text_mismatches": text_mismatches,
    }


def add_unmapped_paragraph_questions(
    questions: dict[str, dict[str, Any]],
    paragraph_lookup: dict[str, dict[str, Any]],
) -> int:
    mapped = {member for record in questions.values() for member in record["members"]}
    added = 0
    for member_key, paragraph in paragraph_lookup.items():
        question = paragraph["source_paragraph_question"]
        if member_key in mapped or not question:
            continue
        record = questions.setdefault(question, {"members": set(), "provenance": []})
        record["members"].add(member_key)
        record["provenance"].append({"status": "source-paragraph-question"})
        added += 1
    return added


def materialize_groups(
    questions: dict[str, dict[str, Any]],
    papers: dict[str, dict[str, Any]],
    paragraph_lookup: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paper_order = {paper_id: paper["paper_order"] for paper_id, paper in papers.items()}
    all_groups: list[dict[str, Any]] = []
    for question, record in questions.items():
        member_keys = sorted(
            record["members"],
            key=lambda key: (
                paper_order[key.split(":", 1)[0]],
                paragraph_lookup[key]["order"],
            ),
        )
        represented_papers = {key.split(":", 1)[0] for key in member_keys}
        kind = "shared" if len(represented_papers) >= 2 else "singleton"
        prefix = "group" if kind == "shared" else "singleton"
        group_id = stable_id(prefix, question, *sorted(member_keys))
        members = [
            {
                "paper": key.split(":", 1)[0],
                "unit_id": key.split(":", 1)[1],
                "tag": question,
            }
            for key in member_keys
        ]
        group = {
            "group_id": group_id,
            "overarching_question": question,
            "members": members,
            "representative_members": members,
            "kind": kind,
            "provenance": record["provenance"],
        }
        all_groups.append(group)
        membership_field = "group_ids" if kind == "shared" else "singleton_ids"
        for member_key in member_keys:
            paragraph_lookup[member_key][membership_field].append(group_id)

    metadata = {
        group["group_id"]: {
            "question": group["overarching_question"],
            "kind": group["kind"],
            "paper_count": len({member["paper"] for member in group["members"]}),
            "member_count": len(group["members"]),
        }
        for group in all_groups
    }
    for paragraph in paragraph_lookup.values():
        memberships = paragraph["group_ids"] + paragraph["singleton_ids"]
        ranked = sorted(
            memberships,
            key=lambda group_id: (
                metadata[group_id]["kind"] != "shared",
                -metadata[group_id]["paper_count"],
                -metadata[group_id]["member_count"],
                group_id,
            ),
        )
        paragraph["tag"] = metadata[ranked[0]]["question"] if ranked else ""
        paragraph.pop("source_paragraph_question", None)

    shared = [group for group in all_groups if group["kind"] == "shared"]
    singletons = [group for group in all_groups if group["kind"] == "singleton"]
    shared.sort(key=lambda group: (
        -len({member["paper"] for member in group["members"]}),
        -len(group["members"]),
        group["overarching_question"],
        group["group_id"],
    ))
    singletons.sort(key=lambda group: (
        paper_order[group["members"][0]["paper"]],
        min(paragraph_lookup[f"{member['paper']}:{member['unit_id']}"]["order"] for member in group["members"]),
        group["overarching_question"],
    ))
    return shared, singletons


def build_dataset(
    structure_path: Path,
    paper_dir: Path,
    metadata_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    require(not output_dir.exists() or not any(output_dir.iterdir()), f"Output directory must be empty: {output_dir}")
    manifest, papers, references, paragraphs, source_files = load_papers(paper_dir, metadata_dir)
    questions, mapping_stats = load_question_mappings(structure_path, references, paragraphs)
    fallback_questions = add_unmapped_paragraph_questions(questions, paragraphs)
    shared_groups, singleton_groups = materialize_groups(questions, papers, paragraphs)

    shared_members = {
        f"{member['paper']}:{member['unit_id']}"
        for group in shared_groups
        for member in group["members"]
    }
    singleton_members = {
        f"{member['paper']}:{member['unit_id']}"
        for group in singleton_groups
        for member in group["members"]
    }
    assigned = shared_members | singleton_members
    multi_membership_count = sum(
        len(paragraph["group_ids"]) + len(paragraph["singleton_ids"]) > 1
        for paragraph in paragraphs.values()
    )
    stats = {
        "paragraph_chunks": len(paragraphs),
        **mapping_stats,
        "exact_question_groups": len(shared_groups) + len(singleton_groups),
        "shared_question_groups": len(shared_groups),
        "shared_paragraph_chunks": len(shared_members),
        "singleton_questions": len(singleton_groups),
        "singleton_paragraph_chunks": len(singleton_members),
        "shared_singleton_overlap": len(shared_members & singleton_members),
        "multi_group_paragraph_chunks": multi_membership_count,
        "source_paragraph_questions_used": fallback_questions,
        "unassigned_paragraph_chunks": len(paragraphs) - len(assigned),
        "section_question_groups": 0,
    }
    snapshot = {
        "schema_version": 2,
        "mode": "final_snapshot",
        "groups": shared_groups,
        "singletons": singleton_groups,
        "section_groups": [],
        "stats": stats,
        "source": {
            "nested_structure": {"name": structure_path.name, "sha256": file_sha256(structure_path)},
            "papers": source_files,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "manifest.json", manifest)
    write_json(output_dir / "bidirectional_matches.json", {"sections": [], "paragraphs": []})
    write_json(output_dir / SNAPSHOT_FILE, snapshot)
    for entry in manifest:
        paper = dict(papers[entry["paper_id"]])
        paper.pop("paper_order", None)
        write_json(output_dir / entry["file"], paper)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nested_structure", type=Path)
    parser.add_argument("paper_dir", type=Path)
    parser.add_argument("metadata_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    stats = build_dataset(
        args.nested_structure.resolve(),
        args.paper_dir.resolve(),
        args.metadata_dir.resolve(),
        args.output_dir.resolve(),
    )
    print(stats)


if __name__ == "__main__":
    main()
