"""Compare completed revisions by source membership, not generated graph IDs."""

from __future__ import annotations

import argparse
import html
import json
import re
from itertools import combinations
from pathlib import Path

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
            "model": state["config"].get("model") if state else None,
            "jev": state["config"].get("jev") if state else None,
            "policy_sha256": state.get("policy_sha256") if state else None,
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
    parents = {node["group_id"]: node["source_members"] for node in run["groups"]["section"]}
    memberships = {}
    questions = {}
    for node in run["groups"][level]:
        members = tuple(key for key in node["source_members"] if key in common)
        if not members:
            continue
        parent = node["parent_group_id"]
        if parent is not None and parent not in parents:
            raise ValueError(f"Unknown parent scope: {parent}")
        scope = tuple(parents[parent]) if parent is not None else ()
        for key in members:
            memberships[key] = {"members": members, "scope": scope}
        questions[members] = node["overarching_question"]
    return memberships, questions


def _stats(run: dict, level: str) -> dict:
    nodes = run["groups"][level]
    return {
        "units": len(run["sources"][level]),
        "groups": len(nodes),
        "singleton_groups": sum(len(node["members"]) == 1 for node in nodes),
        "cross_paper_groups": sum(len({m["paper"] for m in node["members"]}) > 1 for node in nodes),
    }


def compare_revisions(left: Path, right: Path) -> dict:
    a, b = load_revision(left), load_revision(right)
    if a["summary"]["max_granularity"] != b["summary"]["max_granularity"]:
        raise ValueError("Runs use different granularities; compare runs with the same projection")
    common_papers = set(a["papers"]) & set(b["papers"])
    if not common_papers:
        raise ValueError("Runs have no source papers in common")
    result = {
        "schema_version": 1,
        "left": {key: a[key] for key in ("path", "summary", "settings")},
        "right": {key: b[key] for key in ("path", "summary", "settings")},
        "common_papers": sorted(common_papers),
        "left_only_papers": sorted(set(a["papers"]) - common_papers),
        "right_only_papers": sorted(set(b["papers"]) - common_papers),
        "levels": {},
    }
    for level in ("section", "paragraph"):
        common = {
            key for key, source in a["sources"][level].items() if source["paper"] in common_papers
        }
        other = {
            key for key, source in b["sources"][level].items() if source["paper"] in common_papers
        }
        if common != other or any(
            _source_identity(a["sources"][level][key], level)
            != _source_identity(b["sources"][level][key], level)
            for key in common
        ):
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
            "changed_units": len(changes),
            "unchanged_pairs": len(old_pairs & new_pairs),
            "added_pairs": sorted(new_pairs - old_pairs),
            "removed_pairs": sorted(old_pairs - new_pairs),
            "pair_jaccard": len(old_pairs & new_pairs) / len(union) if union else None,
            "changes": changes,
            "question_changes": question_changes,
        }
    return result


def render_html(report: dict) -> str:
    def escape(value):
        return html.escape(str(value), quote=True)

    parts = [
        """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMELTER run comparison</title>
<style>
body{font:12pt 'Times New Roman',serif;color:#000;background:#fff;max-width:1100px;margin:1in auto;padding:0 1rem}
h1,h2,h3{font-size:12pt}table{border-collapse:collapse;width:100%;margin:1rem 0}
td,th{border:1px solid #000;padding:.5rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}details{border:1px solid #000;margin:.8rem 0;padding:.6rem}
blockquote{margin:1rem 0;white-space:pre-wrap}summary{cursor:pointer} @media(max-width:600px){body{margin:1rem auto}td,th{padding:.25rem}}
</style><h1>SMELTER run comparison</h1>
<p>Left is the baseline; right is the comparison. Memberships use source IDs, not graph node IDs.
Agreement is not accuracy: neither run is treated as ground truth. Pair changes use only shared papers
with identical source text and boundaries. Full-run counts include all papers. Paragraph scope changes
also appear below, including added papers in a parent group.</p>"""
    ]
    parts.append(
        "<p><strong>Changed shared-source assignments: "
        + "; ".join(
            f"{data['changed_units']} / {data['common_units']} {level} units"
            for level, data in report["levels"].items()
        )
        + ".</strong></p>"
    )
    parts.append("<table><tr><th></th><th>Left</th><th>Right</th></tr>")
    for label, values in (
        ("Revision", [report[side]["path"] for side in ("left", "right")]),
        (
            "Paper order",
            [", ".join(report[side]["summary"]["paper_order"]) for side in ("left", "right")],
        ),
        (
            "Only in this run",
            [", ".join(report[side + "_only_papers"]) or "None" for side in ("left", "right")],
        ),
        (
            "Generative model",
            [
                " / ".join(
                    str((report[side]["settings"]["model"] or {}).get(field, "Unknown"))
                    for field in ("provider", "name")
                )
                for side in ("left", "right")
            ],
        ),
        (
            "Jev model",
            [
                (report[side]["settings"]["jev"] or {}).get("model", "Not enabled")
                for side in ("left", "right")
            ],
        ),
    ):
        parts.append(
            f"<tr><th>{escape(label)}</th><td><pre>{escape(values[0])}</pre></td><td><pre>{escape(values[1])}</pre></td></tr>"
        )
    parts.append("</table>")
    parts.append(
        "<details><summary>Full model and policy settings</summary><pre>"
        + escape(
            json.dumps({side: report[side]["settings"] for side in ("left", "right")}, indent=2)
        )
        + "</pre></details>"
    )
    for level, data in report["levels"].items():
        score = (
            "Not applicable (no pairs in either run)"
            if data["pair_jaccard"] is None
            else f"{data['pair_jaccard']:.3f}"
        )
        parts.append(
            f"<h2>{escape(level.title())} comparison</h2><p>{data['changed_units']} of {data['common_units']} shared units changed membership or scope. "
            f"Added co-member pairs: {len(data['added_pairs'])}; removed: {len(data['removed_pairs'])}; "
            f"unchanged: {data['unchanged_pairs']}. Pair Jaccard: {score}.</p>"
        )
        parts.append("<table><tr><th>Full-run count</th><th>Left</th><th>Right</th></tr>")
        for field, value in data["left_stats"].items():
            parts.append(
                f"<tr><th>{escape(field.replace('_', ' '))}</th><td>{value}</td><td>{data['right_stats'][field]}</td></tr>"
            )
        parts.append("</table>")
        for change in data["changes"]:
            parts.append(
                f"<details><summary>{escape(change['unit'])} {escape(change['source']['title'])}</summary>"
                f"<blockquote>{escape(change['source']['text'])}</blockquote><table><tr><th>Left</th><th>Right</th></tr><tr>"
            )
            for side in ("left", "right"):
                assignment = change[side]
                parts.append(
                    f"<td><p>{escape(change[side + '_question'])}</p><p>Members: {escape(', '.join(assignment['members']))}</p>"
                    f"<p>Parent scope: {escape(', '.join(assignment['scope'])) or 'None'}</p></td>"
                )
            parts.append("</tr></table></details>")
        parts.append(
            f"<h3>Question changes with unchanged shared-paper membership: {len(data['question_changes'])}</h3>"
        )
        for change in data["question_changes"]:
            parts.append(
                f"<details><summary>{escape(', '.join(change['members']))}</summary><p>Left: {escape(change['left'])}</p>"
                f"<p>Right: {escape(change['right'])}</p></details>"
            )
    parts.append(
        "<p>The adjacent comparison.json contains all pair additions/removals and the report data. No API calls were made to compare these runs.</p></html>"
    )
    return "\n".join(parts)


def write_comparison(left: Path, right: Path, output: Path) -> dict:
    report = compare_revisions(left, right)
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
    args = parser.parse_args()
    print(json.dumps(write_comparison(args.left, args.right, args.output), indent=2))


if __name__ == "__main__":
    main()
