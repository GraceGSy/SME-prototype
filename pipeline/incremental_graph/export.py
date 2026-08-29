"""Write deterministic graph, category, and Question Atlas viewer artifacts."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .graph import QuestionGraph
from .journal import write_json
from .models import Paper


CLASSIFICATIONS = (
    "common_structure",
    "alignable_difference",
    "non_alignable_difference",
)


def export_revision(dataset_dir: Path, graph: QuestionGraph, papers: list[Paper]) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    section_lookup = {
        (paper.paper_id, section.id): section
        for paper in papers
        for section in paper.sections
    }
    paragraph_lookup = {
        (paper.paper_id, paragraph.id): (section, paragraph)
        for paper in papers
        for section in paper.sections
        for paragraph in section.paragraphs
    }

    manifest = []
    for paper in papers:
        filename = f"{paper.paper_id}.json"
        manifest.append({"paper_id": paper.paper_id, "title": paper.title, "file": filename})
        write_json(dataset_dir / filename, _viewer_paper(paper))
    write_json(dataset_dir / "manifest.json", manifest)
    write_json(dataset_dir / "bidirectional_matches.json", {"sections": [], "paragraphs": []})

    paragraph_groups: list[dict[str, Any]] = []
    paragraph_singletons: list[dict[str, Any]] = []
    section_groups: list[dict[str, Any]] = []
    categories: dict[str, dict[str, list[str]]] = {
        "section": defaultdict(list),
        "paragraph": defaultdict(list),
    }
    for node_id, data in graph.nodes():
        categories[data["level"]][data["classification"]].append(node_id)
        group = _viewer_group(node_id, data, section_lookup, paragraph_lookup)
        if data["level"] == "section":
            section_groups.append(group)
        elif group["paper_coverage"] == 1:
            paragraph_singletons.append(group)
        else:
            paragraph_groups.append(group)

    normalized_categories = {
        level: {classification: sorted(values.get(classification, [])) for classification in CLASSIFICATIONS}
        for level, values in categories.items()
    }
    serialized_graph = graph.serialize()
    write_json(dataset_dir / "graph.json", serialized_graph)
    write_json(dataset_dir / "graph_categories.json", {
        "schema_version": 1,
        "paper_count": len(papers),
        "categories": normalized_categories,
    })
    write_json(dataset_dir / "graph-replay.json", graph.replay_payload())
    write_json(dataset_dir / "final_snapshot.json", {
        "schema_version": 2,
        "mode": "final_snapshot",
        "groups": paragraph_groups,
        "singletons": paragraph_singletons,
        "section_groups": section_groups,
        "stats": {
            "common_structures": sum(
                len(values.get("common_structure", [])) for values in normalized_categories.values()
            ),
            "alignable_differences": sum(
                len(values.get("alignable_difference", [])) for values in normalized_categories.values()
            ),
            "non_alignable_differences": sum(
                len(values.get("non_alignable_difference", [])) for values in normalized_categories.values()
            ),
            "section_question_groups": len(section_groups),
            "paragraph_question_groups": len(paragraph_groups) + len(paragraph_singletons),
        },
    })


def _viewer_paper(paper: Paper) -> dict[str, Any]:
    return {
        "paper_id": paper.paper_id,
        "title": paper.title,
        "sections": [
            {
                "id": section.id,
                "title": section.label,
                "tag": section.question,
                "text": section.text,
                "unit_type": section.kind,
                "parent_id": section.parent_id,
                "ordinal": section.ordinal,
                "prev_relation": "",
                "next_relation": "",
            }
            for section in paper.sections
        ],
        "paragraphs": [
            {
                "id": paragraph.id,
                "title": paragraph.label,
                "tag": paragraph.question,
                "text": paragraph.text,
                "section_id": section.id,
                "family_id": section.family_id,
                "ordinal": paragraph.ordinal,
                "prev_relation": "",
                "next_relation": "",
            }
            for section in paper.sections
            for paragraph in section.paragraphs
        ],
    }


def _viewer_group(
    node_id: str,
    data: dict[str, Any],
    section_lookup: dict[tuple[str, str], Any],
    paragraph_lookup: dict[tuple[str, str], tuple[Any, Any]],
) -> dict[str, Any]:
    members = []
    for member in data["members"]:
        paper_id = member["paper_id"]
        unit_id = member["unit_id"]
        if data["level"] == "section":
            section = section_lookup[(paper_id, unit_id)]
            members.append({
                "paper": paper_id,
                "unit_id": unit_id,
                "section_id": unit_id,
                "tag": section.question,
                "unit_type": section.kind,
                "ordinal": section.ordinal,
            })
        else:
            section, paragraph = paragraph_lookup[(paper_id, unit_id)]
            members.append({
                "paper": paper_id,
                "unit_id": unit_id,
                "section_id": section.id,
                "tag": paragraph.question,
                "unit_type": "paragraph",
                "ordinal": paragraph.ordinal,
            })
    return {
        "group_id": node_id,
        "overarching_question": data.get("generated_question") or node_id,
        "classification": data["classification"],
        "parent_group_id": data.get("parent_id"),
        "members": members,
        "representative_members": members,
        "paper_coverage": len({member["paper"] for member in members}),
    }
