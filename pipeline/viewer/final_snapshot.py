"""Normalize pseudo-section questions and merged mappings for the static viewer."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any


SNAPSHOT_FILE = "final_snapshot.json"
OMITTED_SECTION_PATTERN = re.compile(
    r"\b(?:appendix|appendices|bibliography|citations?|references?)\b",
    re.IGNORECASE,
)


class SnapshotBuildError(ValueError):
    """Raised when the source files cannot be normalized without guessing."""


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SnapshotBuildError(f"Could not read {path}: {error}") from error


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotBuildError(message)


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def stable_id(prefix: str, *parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:12]}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_omitted_section(role: str, section_name: str) -> bool:
    return bool(OMITTED_SECTION_PATTERN.search(f"{role} {section_name}"))


def load_paper_metadata(metadata_dir: Path) -> tuple[list[dict[str, str]], dict[str, list[str]]]:
    manifest = read_json(metadata_dir / "manifest.json")
    require(isinstance(manifest, list) and manifest, "Metadata manifest must be a non-empty list")
    section_titles: dict[str, list[str]] = {}
    normalized_manifest: list[dict[str, str]] = []
    for entry in manifest:
        paper_id = str(entry.get("paper_id", ""))
        filename = str(entry.get("file", ""))
        title = str(entry.get("title", ""))
        require(bool(paper_id and filename and title), "Metadata manifest entries need paper_id, title, and file")
        paper = read_json(metadata_dir / filename)
        section_titles[paper_id] = [str(section.get("title", "")) for section in paper.get("sections", [])]
        normalized_manifest.append({"paper_id": paper_id, "title": title, "file": f"{paper_id}.json"})
    return normalized_manifest, section_titles


def load_raw_units(zip_path: Path) -> tuple[dict[str, dict[str, Any]], int]:
    units: dict[str, dict[str, Any]] = {}
    omitted_count = 0
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as error:
        raise SnapshotBuildError(f"Could not open {zip_path}: {error}") from error

    with archive:
        for entry_name in sorted(name for name in archive.namelist() if name.lower().endswith(".json")):
            try:
                payload = json.loads(archive.read(entry_name).decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SnapshotBuildError(f"Invalid JSON in {entry_name}: {error}") from error
            require(isinstance(payload, list), f"{entry_name} must contain a list")
            for item in payload:
                source_id = str(item.get("section_number", ""))
                parts = source_id.split("::")
                require(len(parts) >= 3 and all(parts[:2]), f"Invalid section_number: {source_id!r}")
                paper_id, role = parts[0], parts[1].lower()
                section_name = str(item.get("section_name", ""))
                if is_omitted_section(role, section_name):
                    omitted_count += 1
                    continue
                paragraphs = item.get("paragraphs", [])
                require(
                    isinstance(paragraphs, list) and len(paragraphs) == 1,
                    f"{source_id} must contain exactly one paragraph chunk",
                )
                paragraph = paragraphs[0]
                text = str(paragraph.get("text", "")).strip()
                question = str(item.get("question_this_section_answers", "")).strip()
                require(bool(text), f"{source_id} has no paragraph text")
                require(bool(question), f"{source_id} has no complete question")
                require(source_id not in units, f"Duplicate section_number: {source_id}")
                try:
                    local_index = int(parts[-1])
                except ValueError:
                    local_index = int(paragraph.get("paragraph_number", 0) or 0)
                units[source_id] = {
                    "source_id": source_id,
                    "paper_id": paper_id,
                    "role": role,
                    "local_index": local_index,
                    "paragraph_number": paragraph.get("paragraph_number"),
                    "section_name": section_name,
                    "question": question,
                    "text": text,
                    "source_file": entry_name,
                }
    require(bool(units), "The pseudo-section archive contains no usable paragraph chunks")
    return units, omitted_count


def load_structure(
    structure_path: Path,
    raw_units: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    rows = read_json(structure_path)
    require(isinstance(rows, list) and rows, "Merged structure must contain a non-empty row list")
    groups: list[dict[str, Any]] = []
    section_metadata: dict[tuple[str, str], dict[str, Any]] = {}

    for row_position, row in enumerate(rows):
        role = str(row.get("role_slug", ""))
        section_match = row.get("section_level_match") or {}
        for paper_id, paper_value in (section_match.get("papers") or {}).items():
            section_metadata[(paper_id, role)] = {
                "title": str(paper_value.get("section_name", "")),
                "number": paper_value.get("section_number"),
                "question": str(section_match.get("question_the_sections_answer", "")).strip(),
                "status": str(section_match.get("pairing_status", "")),
                "ancestor_questions": section_match.get("ancestor_questions") or [],
                "row_position": row_position,
                "row_source": str(row.get("row_source", "")),
            }

        for bucket, mapping_groups in row.items():
            if not bucket.startswith("paragraph_level_") or not isinstance(mapping_groups, list):
                continue
            for group_index, group in enumerate(mapping_groups):
                source_ids: list[str] = []
                for paper_value in (group.get("papers") or {}).values():
                    source_id = str(paper_value.get("section_number", ""))
                    if source_id in raw_units:
                        source_ids.append(source_id)
                if not source_ids:
                    continue
                groups.append({
                    "role": role,
                    "row_position": row_position,
                    "row_source": str(row.get("row_source", "")),
                    "group_index": group_index,
                    "source_ids": source_ids,
                    "question": str(group.get("question_the_sections_answer") or "").strip(),
                    "status": str(group.get("pairing_status") or group.get("diff_type") or ""),
                    "basis": str(group.get("basis") or ""),
                    "ancestor_questions": group.get("ancestor_questions") or [],
                })
    require(bool(groups), "Merged structure contains no usable paragraph mappings")
    return groups, section_metadata


def deduplicate_units(
    raw_units: dict[str, dict[str, Any]],
    raw_groups: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str], int]:
    shared_source_ids: set[str] = set()
    for group in raw_groups:
        papers = {raw_units[source_id]["paper_id"] for source_id in group["source_ids"]}
        if len(papers) >= 2:
            shared_source_ids.update(group["source_ids"])

    duplicate_sets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for unit in raw_units.values():
        duplicate_sets[(unit["paper_id"], unit["text"].strip())].append(unit)

    canonical_units: dict[str, dict[str, Any]] = {}
    alias_to_canonical: dict[str, str] = {}
    duplicate_count = 0
    for duplicates in duplicate_sets.values():
        ordered = sorted(
            duplicates,
            key=lambda unit: (unit["source_id"] not in shared_source_ids, unit["source_id"]),
        )
        canonical = dict(ordered[0])
        aliases = sorted(unit["source_id"] for unit in ordered)
        canonical["source_ids"] = aliases
        canonical["source_files"] = sorted({unit["source_file"] for unit in ordered})
        canonical["source_questions"] = sorted({unit["question"] for unit in ordered})
        canonical_units[canonical["source_id"]] = canonical
        for unit in ordered:
            alias_to_canonical[unit["source_id"]] = canonical["source_id"]
        duplicate_count += len(ordered) - 1
    return canonical_units, alias_to_canonical, duplicate_count


def normalize_group_records(
    raw_groups: list[dict[str, Any]],
    raw_units: dict[str, dict[str, Any]],
    alias_to_canonical: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized: list[dict[str, Any]] = []
    signatures: set[tuple[str, tuple[str, ...]]] = set()
    for raw_group in raw_groups:
        canonical_ids = sorted({alias_to_canonical[source_id] for source_id in raw_group["source_ids"]})
        question = raw_group["question"] or raw_units[canonical_ids[0]]["question"]
        signature = (question, tuple(canonical_ids))
        if signature in signatures:
            continue
        signatures.add(signature)
        papers = {raw_units[source_id]["paper_id"] for source_id in canonical_ids}
        kind = "shared" if len(papers) >= 2 else "singleton"
        normalized.append({
            "kind": kind,
            "question": question,
            "canonical_source_ids": canonical_ids,
            "provenance": {
                "role_slug": raw_group["role"],
                "row_position": raw_group["row_position"],
                "row_source": raw_group["row_source"],
                "group_index": raw_group["group_index"],
                "status": raw_group["status"],
                "basis": raw_group["basis"],
                "ancestor_questions": raw_group["ancestor_questions"],
            },
        })

    shared = [record for record in normalized if record["kind"] == "shared"]
    shared_unit_ids = {
        source_id
        for record in shared
        for source_id in record["canonical_source_ids"]
    }
    singleton_by_unit: dict[str, dict[str, Any]] = {}
    for record in normalized:
        if record["kind"] != "singleton":
            continue
        source_id = record["canonical_source_ids"][0]
        if source_id in shared_unit_ids:
            continue
        singleton_by_unit.setdefault(source_id, record)

    for source_id, unit in raw_units.items():
        if source_id in shared_unit_ids or source_id in singleton_by_unit:
            continue
        singleton_by_unit[source_id] = {
            "kind": "singleton",
            "question": unit["question"],
            "canonical_source_ids": [source_id],
            "provenance": {"status": "unmapped-singleton"},
        }
    return shared, list(singleton_by_unit.values())


def section_sort_key(
    paper_id: str,
    role: str,
    metadata: dict[str, Any],
    existing_titles: dict[str, list[str]],
) -> tuple[float, int, str]:
    title = str(metadata.get("title", ""))
    normalized = normalized_title(title)
    title_order = {
        normalized_title(value): index
        for index, value in enumerate(existing_titles.get(paper_id, []))
    }
    if normalized in title_order:
        return float(title_order[normalized]), int(metadata.get("row_position", 0)), role
    if role == "abstract":
        return -1.0, 0, role
    if role == "acknowledgments":
        return 10_000.0, 0, role
    number = str(metadata.get("number") or "")
    match = re.match(r"\s*(\d+(?:\.\d+)?)", number)
    if match:
        return float(match.group(1)), int(metadata.get("row_position", 0)), role
    return 5_000.0 + int(metadata.get("row_position", 0)), 0, role


def build_papers(
    manifest: list[dict[str, str]],
    existing_titles: dict[str, list[str]],
    canonical_units: dict[str, dict[str, Any]],
    section_metadata: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]], dict[str, str], dict[tuple[str, str], str]]:
    paper_order = {entry["paper_id"]: index for index, entry in enumerate(manifest)}
    present_papers = {unit["paper_id"] for unit in canonical_units.values()}
    output_manifest = [entry for entry in manifest if entry["paper_id"] in present_papers]
    require(
        {entry["paper_id"] for entry in output_manifest} == present_papers,
        "Paper metadata does not cover every paper in the pseudo-section archive",
    )

    sections_by_paper_role: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for unit in canonical_units.values():
        sections_by_paper_role[(unit["paper_id"], unit["role"])].append(unit)

    papers: dict[str, dict[str, Any]] = {}
    canonical_to_unit_id: dict[str, str] = {}
    section_id_by_paper_role: dict[tuple[str, str], str] = {}
    for manifest_entry in output_manifest:
        paper_id = manifest_entry["paper_id"]
        role_entries = []
        for (candidate_paper, role), units in sections_by_paper_role.items():
            if candidate_paper != paper_id:
                continue
            metadata = section_metadata.get((paper_id, role), {})
            role_entries.append((section_sort_key(paper_id, role, metadata, existing_titles), role, units, metadata))
        role_entries.sort(key=lambda item: item[0])

        sections: list[dict[str, Any]] = []
        paragraphs: list[dict[str, Any]] = []
        paragraph_order = 0
        for _, role, role_units, metadata in role_entries:
            section_id = stable_id("s", paper_id, role)
            section_id_by_paper_role[(paper_id, role)] = section_id
            ordered_units = sorted(role_units, key=lambda unit: (unit["local_index"], unit["source_id"]))
            section_title = str(metadata.get("title") or role.replace("-", " ").title())
            section_question = str(metadata.get("question") or "")
            sections.append({
                "id": section_id,
                "title": section_title,
                "tag": section_question,
                "text": "\n\n".join(unit["text"] for unit in ordered_units),
                "prev_relation": "",
                "next_relation": "",
                "section_id": "",
                "role_slug": role,
                "section_group_ids": [],
            })
            for unit in ordered_units:
                unit_id = stable_id("p", unit["source_id"])
                canonical_to_unit_id[unit["source_id"]] = unit_id
                paragraphs.append({
                    "id": unit_id,
                    "title": "",
                    "tag": unit["question"],
                    "text": unit["text"],
                    "prev_relation": "",
                    "next_relation": "",
                    "section_id": section_id,
                    "order": paragraph_order,
                    "role_slug": role,
                    "group_ids": [],
                    "singleton_id": None,
                    "source_ids": unit["source_ids"],
                    "source_files": unit["source_files"],
                    "source_questions": unit["source_questions"],
                    "paragraph_number": unit["paragraph_number"],
                })
                paragraph_order += 1
        papers[paper_id] = {
            "paper_id": paper_id,
            "title": manifest_entry["title"],
            "sections": sections,
            "paragraphs": paragraphs,
            "paper_order": paper_order[paper_id],
        }
    return output_manifest, papers, canonical_to_unit_id, section_id_by_paper_role


def group_member(
    canonical_source_id: str,
    canonical_units: dict[str, dict[str, Any]],
    canonical_to_unit_id: dict[str, str],
) -> dict[str, Any]:
    unit = canonical_units[canonical_source_id]
    return {
        "paper": unit["paper_id"],
        "unit_id": canonical_to_unit_id[canonical_source_id],
        "tag": unit["question"],
        "source_ids": unit["source_ids"],
    }


def materialize_groups(
    shared_records: list[dict[str, Any]],
    singleton_records: list[dict[str, Any]],
    canonical_units: dict[str, dict[str, Any]],
    canonical_to_unit_id: dict[str, str],
    papers: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paragraph_by_key = {
        f"{paper_id}:{paragraph['id']}": paragraph
        for paper_id, paper in papers.items()
        for paragraph in paper["paragraphs"]
    }
    shared_groups: list[dict[str, Any]] = []
    for record in shared_records:
        members = [
            group_member(source_id, canonical_units, canonical_to_unit_id)
            for source_id in record["canonical_source_ids"]
        ]
        member_keys = sorted(f"{member['paper']}:{member['unit_id']}" for member in members)
        group_id = stable_id("group", record["question"], *member_keys)
        group = {
            "group_id": group_id,
            "overarching_question": record["question"],
            "members": members,
            "representative_members": members,
            "kind": "shared",
            "provenance": record["provenance"],
        }
        shared_groups.append(group)
        for member in members:
            paragraph_by_key[f"{member['paper']}:{member['unit_id']}"]["group_ids"].append(group_id)

    paper_order = {paper_id: paper["paper_order"] for paper_id, paper in papers.items()}
    unit_order = {
        f"{paper_id}:{paragraph['id']}": paragraph["order"]
        for paper_id, paper in papers.items()
        for paragraph in paper["paragraphs"]
    }
    singleton_groups: list[dict[str, Any]] = []
    for record in singleton_records:
        source_id = record["canonical_source_ids"][0]
        member = group_member(source_id, canonical_units, canonical_to_unit_id)
        member_key = f"{member['paper']}:{member['unit_id']}"
        singleton_id = stable_id("singleton", record["question"], member_key)
        singleton_groups.append({
            "group_id": singleton_id,
            "overarching_question": record["question"],
            "members": [member],
            "representative_members": [member],
            "kind": "singleton",
            "provenance": record["provenance"],
        })
        paragraph_by_key[member_key]["singleton_id"] = singleton_id

    shared_groups.sort(key=lambda group: (-len(group["members"]), group["overarching_question"], group["group_id"]))
    singleton_groups.sort(key=lambda group: (
        paper_order[group["members"][0]["paper"]],
        unit_order[f"{group['members'][0]['paper']}:{group['members'][0]['unit_id']}"],
    ))
    return shared_groups, singleton_groups


def materialize_section_groups(
    structure_path: Path,
    section_id_by_paper_role: dict[tuple[str, str], str],
    papers: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = read_json(structure_path)
    sections_by_key = {
        (paper_id, section["id"]): section
        for paper_id, paper in papers.items()
        for section in paper["sections"]
    }
    order_by_key = {
        (paper_id, section["id"]): index
        for paper_id, paper in papers.items()
        for index, section in enumerate(paper["sections"])
    }
    groups: list[dict[str, Any]] = []
    for row_position, row in enumerate(rows):
        role = str(row.get("role_slug", ""))
        match = row.get("section_level_match") or {}
        question = str(match.get("question_the_sections_answer") or "").strip()
        if not question or is_omitted_section(role, question):
            continue
        members = []
        for paper_id in (match.get("papers") or {}):
            section_id = section_id_by_paper_role.get((paper_id, role))
            if not section_id:
                continue
            members.append({"paper": paper_id, "unit_id": section_id, "section_id": section_id})
        if len({member["paper"] for member in members}) < 2:
            continue
        member_keys = sorted(f"{member['paper']}:{member['section_id']}" for member in members)
        group_id = stable_id("section", question, *member_keys)
        group = {
            "group_id": group_id,
            "overarching_question": question,
            "members": members,
            "kind": "section",
            "status": str(match.get("pairing_status") or ""),
            "ancestor_questions": match.get("ancestor_questions") or [],
            "role_slug": role,
            "row_position": row_position,
            "row_source": str(row.get("row_source") or ""),
        }
        groups.append(group)
        for member in members:
            sections_by_key[(member["paper"], member["section_id"])]["section_group_ids"].append(group_id)

    groups.sort(key=lambda group: (
        sum(order_by_key[(member["paper"], member["section_id"])] for member in group["members"])
        / len(group["members"]),
        group["row_position"],
    ))
    return groups


def build_dataset(
    zip_path: Path,
    structure_path: Path,
    metadata_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    require(not output_dir.exists() or not any(output_dir.iterdir()), f"Output directory must be empty: {output_dir}")
    manifest, existing_titles = load_paper_metadata(metadata_dir)
    raw_units, omitted_count = load_raw_units(zip_path)
    raw_groups, section_metadata = load_structure(structure_path, raw_units)
    canonical_units, alias_to_canonical, duplicate_count = deduplicate_units(raw_units, raw_groups)
    shared_records, singleton_records = normalize_group_records(raw_groups, canonical_units, alias_to_canonical)
    output_manifest, papers, canonical_to_unit_id, section_ids = build_papers(
        manifest,
        existing_titles,
        canonical_units,
        section_metadata,
    )
    shared_groups, singleton_groups = materialize_groups(
        shared_records,
        singleton_records,
        canonical_units,
        canonical_to_unit_id,
        papers,
    )
    section_groups = materialize_section_groups(structure_path, section_ids, papers)
    multi_membership_count = sum(
        1
        for paper in papers.values()
        for paragraph in paper["paragraphs"]
        if len(paragraph["group_ids"]) > 1
    )
    unclassified = [
        f"{paper_id}:{paragraph['id']}"
        for paper_id, paper in papers.items()
        for paragraph in paper["paragraphs"]
        if not paragraph["group_ids"] and not paragraph["singleton_id"]
    ]
    require(not unclassified, f"Paragraph chunks have no shared or singleton question: {unclassified[:3]}")

    stats = {
        "raw_paragraph_chunks": len(raw_units),
        "paragraph_chunks": sum(len(paper["paragraphs"]) for paper in papers.values()),
        "exact_duplicates_removed": duplicate_count,
        "omitted_reference_or_appendix_chunks": omitted_count,
        "shared_question_groups": len(shared_groups),
        "shared_paragraph_chunks": sum(
            1
            for paper in papers.values()
            for paragraph in paper["paragraphs"]
            if paragraph["group_ids"]
        ),
        "singleton_questions": len(singleton_groups),
        "multi_group_paragraph_chunks": multi_membership_count,
        "section_question_groups": len(section_groups),
    }
    snapshot = {
        "schema_version": 1,
        "mode": "final_snapshot",
        "groups": shared_groups,
        "singletons": singleton_groups,
        "section_groups": section_groups,
        "stats": stats,
        "source": {
            "pseudo_sections_zip": {"name": zip_path.name, "sha256": file_sha256(zip_path)},
            "merged_structure": {"name": structure_path.name, "sha256": file_sha256(structure_path)},
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "manifest.json", output_manifest)
    write_json(output_dir / "bidirectional_matches.json", {"sections": [], "paragraphs": []})
    write_json(output_dir / SNAPSHOT_FILE, snapshot)
    for entry in output_manifest:
        paper = dict(papers[entry["paper_id"]])
        paper.pop("paper_order", None)
        write_json(output_dir / entry["file"], paper)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pseudo_sections_zip", type=Path)
    parser.add_argument("merged_structure", type=Path)
    parser.add_argument("metadata_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    stats = build_dataset(
        args.pseudo_sections_zip.resolve(),
        args.merged_structure.resolve(),
        args.metadata_dir.resolve(),
        args.output_dir.resolve(),
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
