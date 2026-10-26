"""Compare completed revisions by source membership, not generated graph IDs."""

from __future__ import annotations

import argparse
import html
import json
import re
from itertools import combinations
from pathlib import Path

from ..comparison_metrics import membership_metrics, project_groups, question_similarity
from ..files import read_json, write_json


def load_revision(path: Path) -> dict:
    """Read old runs without requiring their policy to match the current code."""
    path = path.resolve()
    state = None
    if (path / "run.json").is_file():
        state = read_json(path / "run.json")
        revision = state.get("current_revision")
        if not isinstance(revision, str) or not re.fullmatch(r"revision-\d{4,}", revision):
            raise ValueError(f"No completed revision in {path}")
        path = path / "revisions" / revision
    elif path.parent.name == "revisions" and (path.parent.parent / "run.json").is_file():
        state = read_json(path.parent.parent / "run.json")
    if (path / "failure.json").exists() or not (path / "summary.json").is_file():
        raise ValueError(f"Not a completed graph revision: {path}")
    summary = read_json(path / "summary.json")
    config = (
        read_json(path / "config.json")
        if (path / "config.json").is_file()
        else (state["config"] if state else {})
    )
    dataset = path / "dataset"
    manifest = read_json(dataset / "manifest.json")
    snapshot = read_json(dataset / "final_snapshot.json")
    if (
        summary.get("schema_version") != 1
        or snapshot.get("schema_version") != 1
        or snapshot.get("mode") != "final_snapshot"
    ):
        raise ValueError("Unsupported summary or viewer snapshot contract")
    sources = {"section": {}, "paragraph": {}}
    papers = {}
    for entry in manifest:
        paper_id = entry["paper_id"]
        if paper_id in papers:
            raise ValueError("Duplicate source paper in exported manifest")
        file = (dataset / entry["file"]).resolve()
        if not file.is_relative_to(dataset.resolve()):
            raise ValueError("Source file must stay inside its dataset")
        paper = read_json(file)
        if paper["paper_id"] != paper_id:
            raise ValueError("Source paper ID differs from manifest")
        papers[paper_id] = paper["title"]
        for level, field in (("section", "sections"), ("paragraph", "paragraphs")):
            for unit in paper[field]:
                key = f"{paper_id}:{unit['id']}"
                if key in sources[level]:
                    raise ValueError(f"Duplicate source unit: {key}")
                sources[level][key] = {**unit, "paper": paper_id}
    groups = {
        "section": snapshot["section_groups"],
        "paragraph": [*snapshot["groups"], *snapshot["singletons"]],
    }
    for level, nodes in groups.items():
        assigned = set()
        node_ids = set()
        for node in nodes:
            members = [f"{member['paper']}:{member['unit_id']}" for member in node["members"]]
            if not members or len(set(members)) != len(members):
                raise ValueError("Empty group or duplicate members in a group")
            if node["group_id"] in node_ids or assigned.intersection(members):
                raise ValueError("Duplicate node or source membership")
            node_ids.add(node["group_id"])
            assigned.update(members)
            node["source_members"] = sorted(members)
        if assigned != set(sources[level]):
            raise ValueError(f"Incomplete or unknown {level} source memberships")
    return {
        "path": str(path),
        "summary": summary,
        "papers": papers,
        "sources": sources,
        "groups": groups,
        "settings": {
            "model": config.get("model"),
            "jev": config.get("jev"),
            "policy_sha256": state.get("policy_sha256") if state else None,
            "config_source": "revision/config.json"
            if (path / "config.json").is_file()
            else "run.json (historical fallback)",
        },
    }


def _source_identity(unit: dict, level: str) -> dict:
    fields = (
        ("id", "text", "title", "unit_type", "parent_id")
        if level == "section"
        else (
            "id",
            "text",
            "title",
            "section_id",
            "family_id",
        )
    )
    return {field: unit.get(field) for field in fields}


def _assignments(run: dict, level: str, common: set[str]) -> tuple[dict, dict]:
    memberships = {}
    questions = {}
    for group in project_groups(run, level, common):
        members = tuple(group["members"])
        scope = tuple(group["scope"])
        for key in members:
            memberships[key] = {"members": members, "scope": scope}
        questions[members] = group["question"]
    return memberships, questions


def _stats(run: dict, level: str) -> dict:
    nodes = run["groups"][level]
    return {
        "units": len(run["sources"][level]),
        "groups": len(nodes),
        "singleton_groups": sum(len(node["members"]) == 1 for node in nodes),
        "cross_paper_groups": sum(len({m["paper"] for m in node["members"]}) > 1 for node in nodes),
    }


def compare_revisions(left: Path, right: Path, *, shared_sources: bool = False) -> dict:
    a, b = load_revision(left), load_revision(right)
    granularity_changed = a["summary"]["max_granularity"] != b["summary"]["max_granularity"]
    if granularity_changed and not shared_sources:
        raise ValueError("Runs use different granularities; compare runs with the same projection")
    common_papers = set(a["papers"]) & set(b["papers"])
    if not common_papers:
        raise ValueError("Runs have no source papers in common")
    result = {
        "schema_version": 2,
        "comparison_mode": "shared-sources" if shared_sources else "strict",
        "warnings": ["Agreement and coverage are not accuracy; neither run is ground truth."],
        "left": {key: a[key] for key in ("path", "summary", "settings")},
        "right": {key: b[key] for key in ("path", "summary", "settings")},
        "common_papers": sorted(common_papers),
        "paper_titles": {key: a["papers"][key] for key in sorted(common_papers)},
        "left_only_papers": sorted(set(a["papers"]) - common_papers),
        "right_only_papers": sorted(set(b["papers"]) - common_papers),
        "levels": {},
    }
    if granularity_changed:
        result["warnings"].append(
            "Granularity differs. Only identical shared source IDs/text are compared; source scopes may differ."
        )
    if a["summary"]["paper_order"] != b["summary"]["paper_order"]:
        result["warnings"].append(
            "Corpus membership or insertion order differs. Extra papers can affect matches and group questions even after projection."
        )
    if any(
        a["settings"][field] != b["settings"][field] for field in ("model", "jev", "policy_sha256")
    ):
        result["warnings"].append(
            "Model/policy metadata differ. These runs are not a controlled Jev-versus-LLM experiment."
        )
    if any("historical" in run["settings"]["config_source"] for run in (a, b)):
        result["warnings"].append(
            "An older revision has no config snapshot; its settings come from run.json and may describe a later attempt."
        )
    for level in ("section", "paragraph"):
        left_units = {
            key for key, source in a["sources"][level].items() if source["paper"] in common_papers
        }
        right_units = {
            key for key, source in b["sources"][level].items() if source["paper"] in common_papers
        }
        common = left_units & right_units
        if not common:
            raise ValueError(f"No shared {level} source IDs")
        metadata_changes = sorted(
            key
            for key in common
            if _source_identity(a["sources"][level][key], level)
            != _source_identity(b["sources"][level][key], level)
        )
        text_changes = [
            key
            for key in common
            if a["sources"][level][key]["text"] != b["sources"][level][key]["text"]
        ]
        if text_changes or (not shared_sources and (left_units != right_units or metadata_changes)):
            raise ValueError(
                f"Shared {level} source content or boundaries differ; memberships are not directly comparable"
            )
        before, old_questions = _assignments(a, level, common)
        after, new_questions = _assignments(b, level, common)
        old_pairs = {
            pair for value in before.values() for pair in combinations(value["members"], 2)
        }
        new_pairs = {pair for value in after.values() for pair in combinations(value["members"], 2)}
        union = old_pairs | new_pairs
        changes = []
        for key in sorted(common):
            # Scope signatures use source IDs; node-ID churn never looks like a change.
            if before[key] != after[key]:
                changes.append(
                    {
                        "unit": key,
                        "source": a["sources"][level][key],
                        "left": before[key],
                        "right": after[key],
                        "left_question": old_questions[before[key]["members"]],
                        "right_question": new_questions[after[key]["members"]],
                    }
                )
        question_changes = [
            {"members": members, "left": old_questions[members], "right": new_questions[members]}
            for members in sorted(old_questions.keys() & new_questions.keys())
            if old_questions[members] != new_questions[members]
        ]
        result["levels"][level] = {
            "left_stats": _stats(a, level),
            "right_stats": _stats(b, level),
            "common_units": len(common),
            "source_projection": {
                "left_units_in_shared_papers": len(left_units),
                "right_units_in_shared_papers": len(right_units),
                "left_excluded_units": sorted(left_units - common),
                "right_excluded_units": sorted(right_units - common),
                "metadata_changed_units": metadata_changes,
            },
            "changed_units": len(changes),
            "membership_changed_units": sum(
                before[key]["members"] != after[key]["members"] for key in common
            ),
            "scope_changed_units": sum(
                before[key]["scope"] != after[key]["scope"] for key in common
            ),
            "scope_only_changed_units": sum(
                before[key]["members"] == after[key]["members"]
                and before[key]["scope"] != after[key]["scope"]
                for key in common
            ),
            "unchanged_pairs": len(old_pairs & new_pairs),
            "added_pairs": sorted(new_pairs - old_pairs),
            "removed_pairs": sorted(old_pairs - new_pairs),
            "pair_jaccard": len(old_pairs & new_pairs) / len(union) if union else None,
            "changes": changes,
            "question_changes": question_changes,
            "sources": {key: a["sources"][level][key] for key in sorted(common)},
            "assignments": {
                side: {
                    key: {**assignments[key], "question": questions[assignments[key]["members"]]}
                    for key in sorted(common)
                }
                for side, assignments, questions in (
                    ("left", before, old_questions),
                    ("right", after, new_questions),
                )
            },
            "metrics": membership_metrics(
                project_groups(a, level, common),
                project_groups(b, level, common),
                {key: a["sources"][level][key] for key in sorted(common)},
            ),
            "unit_questions": question_similarity(
                [
                    {
                        "unit": key,
                        "left": a["sources"][level][key].get("tag", ""),
                        "right": b["sources"][level][key].get("tag", ""),
                    }
                    for key in sorted(common)
                ]
            ),
        }
    return result


def escape(value) -> str:
    return html.escape(str(value), quote=True)


def _percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def _metrics_html(data: dict) -> str:
    metrics = data["metrics"]
    coverage, graph, alignment = (metrics[key] for key in ("coverage", "graph", "group_alignment"))
    parts = [
        "<h3>Coverage on identical shared sources</h3><table><tr><th>Measure</th><th>Baseline</th><th>Comparison</th></tr>"
    ]
    for label, values in (
        (
            "Units matched across papers",
            [
                f"{coverage[side]['matched_units']} / {data['common_units']} ({_percent(coverage[side]['fraction'])})"
                for side in ("left", "right")
            ],
        ),
        ("Shared groups", [coverage[side]["cross_paper_groups"] for side in ("left", "right")]),
        (
            "Cross-paper co-member pairs",
            [coverage[side]["cross_paper_pairs"] for side in ("left", "right")],
        ),
    ):
        parts.append(
            f"<tr><th>{escape(label)}</th><td>{escape(values[0])}</td><td>{escape(values[1])}</td></tr>"
        )
    for paper in coverage["left"]["by_paper"]:
        cells = [coverage[side]["by_paper"][paper] for side in ("left", "right")]
        parts.append(
            f"<tr><th>{escape(paper)} coverage</th>"
            + "".join(
                f"<td>{cell['matched']} / {cell['total']} ({_percent(cell['fraction'])})</td>"
                for cell in cells
            )
            + "</tr>"
        )
    parts.append("</table><h3>Match agreement</h3><table><tr><th>Measure</th><th>Value</th></tr>")
    for label, value in (
        ("Cross-paper pair Jaccard", _percent(graph["pair_jaccard"])),
        ("Cross-paper pair F1 agreement (not accuracy)", _percent(graph["pair_f1_agreement"])),
        ("Baseline pairs retained", _percent(graph["baseline_pair_retention"])),
        ("New-run pairs also in baseline", _percent(graph["new_pair_overlap_with_baseline"])),
        (
            "Mean peer overlap, units matched in either run",
            _percent(graph["mean_peer_jaccard_active_units"]),
        ),
        ("Fixed-source graph edge edits", graph["fixed_identity_edge_edits"]),
        ("Source-identity-preserving graph isomorphism", graph["identity_isomorphic"]),
        ("Units with membership changes", data["membership_changed_units"]),
        ("Units with scope-only changes", data["scope_only_changed_units"]),
        (
            "Units gaining / losing match coverage",
            f"{len(graph['gained_coverage'])} / {len(graph['lost_coverage'])}",
        ),
    ):
        parts.append(f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>")
    parts.append(
        "</table><p>NetworkX compares source-anchored graphs. Edge edits are exact additions/removals with fixed source identities, not an unrestricted graph-edit-distance search.</p>"
    )
    parts.append(
        "<h3>Question wording similarity</h3><p>These are lexical scores, not semantic correctness or answer-quality scores. TF-IDF is fitted only on the displayed comparison pairs. No embeddings or API calls.</p><table><tr><th>Questions</th><th>Compared</th><th>Exact after case/punctuation normalization</th><th>Token Jaccard</th><th>TF-IDF cosine</th></tr>"
    )
    for label, scores in (
        ("Source-unit questions", data["unit_questions"]),
        ("Aligned shared-group questions", alignment["questions"]),
    ):
        parts.append(
            f"<tr><th>{escape(label)}</th><td>{scores['compared']}</td><td>{_percent(scores['normalized_exact_fraction'])}</td><td>{_percent(scores['mean_token_jaccard'])}</td><td>{_percent(scores['mean_tfidf_cosine'])}</td></tr>"
        )
    parts.append("</table>")
    parts.append(
        "<p>Group questions are compared only where groups share source members, including partial overlaps; inspect the alignment below before interpreting a wording score. Missing questions are excluded, not scored as identical.</p>"
    )
    for label, pairs in (
        ("Lost cross-paper pairs", graph["removed_pairs"]),
        ("Added cross-paper pairs", graph["added_pairs"]),
    ):
        parts.append(f"<details><summary>{label}: {len(pairs)} (inspect source passages)</summary>")
        for pair in pairs:
            parts.append(
                f"<details><summary>{escape(' / '.join(pair))}</summary><table><tr><th>Source 1</th><th>Source 2</th></tr><tr>"
            )
            for key in pair:
                source = data["sources"][key]
                parts.append(
                    f"<td><strong>{escape(source['paper'])}: {escape(source.get('title', key))}</strong><blockquote>{escape(source['text'])}</blockquote></td>"
                )
            parts.append("</tr></table></details>")
        parts.append("</details>")
    parts.append(
        f"<h3>NetworkX shared-group alignment</h3><p>{escape(alignment['method'])}. {alignment['aligned_groups']} aligned; {alignment['unmatched_left']} baseline and {alignment['unmatched_right']} comparison groups unaligned. Mean membership Jaccard including unaligned groups as zero: {_percent(alignment['mean_member_jaccard_with_unmatched_zero'])}. Groups overlapping multiple counterparts: {alignment['left_groups_overlapping_multiple_right']} baseline / {alignment['right_groups_overlapping_multiple_left']} comparison.</p>"
    )
    question_rows = iter(alignment["questions"]["rows"])
    for row in alignment["rows"]:
        title = f"Membership Jaccard {_percent(row['member_jaccard'])}: " + " / ".join(
            ", ".join(row[side]["members"]) if row[side] else "Unaligned"
            for side in ("left", "right")
        )
        parts.append(
            f"<details><summary>{escape(title)}</summary><table><tr><th>Baseline group</th><th>Comparison group</th></tr><tr>"
        )
        for side in ("left", "right"):
            group = row[side]
            parts.append(
                "<td>Unaligned</td>"
                if group is None
                else f"<td><p>{escape(group['question'])}</p><pre>{escape(chr(10).join(group['members']))}</pre><p>Original group members: {escape(', '.join(group['full_members']))}</p></td>"
            )
        parts.append("</tr></table>")
        if row["left"] and row["right"]:
            scores = next(question_rows)
            parts.append(
                "<p>Question token Jaccard: "
                f"{_percent(scores['token_jaccard'])}; TF-IDF cosine: {_percent(scores['tfidf_cosine'])}. "
                f"Identical projected membership: {scores['same_membership']}.</p>"
            )
        parts.append("</details>")
    parts.append(
        "<details><summary>Inspect all source-unit questions, least lexical overlap first</summary>"
    )
    for row in sorted(
        data["unit_questions"]["rows"],
        key=lambda row: (
            row["tfidf_cosine"] if row["tfidf_cosine"] is not None else -1,
            row["unit"],
        ),
    ):
        parts.append(
            f"<details><summary>{escape(row['unit'])}: TF-IDF {_percent(row['tfidf_cosine'])}</summary><table><tr><th>Baseline</th><th>Comparison</th></tr><tr><td>{escape(row['left'])}</td><td>{escape(row['right'])}</td></tr></table></details>"
        )
    parts.append("</details>")
    return "\n".join(parts)


def render_html(report: dict) -> str:
    """Embed the offline viewer and data in one portable HTML file."""
    assets = Path(__file__).parents[1] / "comparison_viewer"
    detail = []
    for level, data in report["levels"].items():
        graph = data["metrics"]["graph"]
        detail.append(
            f'<section id="metrics-{level}"><h3>{escape(level.title())} metrics</h3>'
            f"<p>Cross-paper pairs added: {len(graph['added_pairs'])}; "
            f"removed: {len(graph['removed_pairs'])}; retained: {graph['unchanged_pairs']}.</p>"
            + _metrics_html(data)
            + "</section>"
        )
    # Escape HTML delimiters in JSON so source text cannot close the script element.
    payload = (
        json.dumps(report, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    replacements = {
        "STYLE": (assets / "styles.css").read_text(encoding="utf-8"),
        "DATA": payload,
        "SCRIPT": (assets / "app.mjs").read_text(encoding="utf-8"),
        "METRICS": "\n".join(detail),
    }
    return re.sub(
        r"@@(STYLE|DATA|SCRIPT|METRICS)@@",
        lambda match: replacements[match[1]],
        (assets / "index.html").read_text(encoding="utf-8"),
    )


def write_comparison(
    left: Path, right: Path, output: Path, *, shared_sources: bool = False, public: bool = False
) -> dict:
    report = compare_revisions(left, right, shared_sources=shared_sources)
    if public:
        # Publish run identifiers, never the operator's absolute filesystem paths.
        for side in ("left", "right"):
            revision = Path(report[side]["path"])
            report[side]["path"] = "/".join(revision.parts[-3:])
            report[side]["summary"].pop("dataset_dir", None)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "comparison.json", report)
    (output / "index.html").write_text(render_html(report), encoding="utf-8")
    return {
        "report": str((output / "index.html").resolve()),
        "data": str((output / "comparison.json").resolve()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path, help="Baseline run directory or completed revision")
    parser.add_argument("right", type=Path, help="Comparison run directory or completed revision")
    parser.add_argument("output", type=Path, help="New directory for HTML and JSON reports")
    parser.add_argument(
        "--public", action="store_true", help="Omit local filesystem paths for hosting"
    )
    parser.add_argument(
        "--shared-sources",
        action="store_true",
        help="Explicitly project onto identical source IDs/text when granularity or scope metadata differs",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            write_comparison(
                args.left,
                args.right,
                args.output,
                shared_sources=args.shared_sources,
                public=args.public,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
