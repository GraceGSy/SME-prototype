"""Run document preparation, incremental graphing, and viewer packaging once."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from .incremental_graph.cli import DEFAULT_CONFIG as GRAPH_CONFIG
from .incremental_graph.cli import run_revision
from .skill_pipeline.runner import DEFAULT_CONFIG as DOCUMENT_CONFIG
from .skill_pipeline.runner import ROOT, Harness
from .viewer.package import package_dataset, package_study


VIEWER_PATH = ROOT / "pipeline" / "viewer" / "index.html"


def _next_build(directory: Path) -> Path:
    numbers = []
    if directory.is_dir():
        for path in directory.iterdir():
            match = re.fullmatch(r"build-(\d+)", path.name)
            if path.is_dir() and match:
                numbers.append(int(match.group(1)))
    return directory / f"build-{max(numbers, default=0) + 1:04d}"


def _write_graph_manifest(harness: Harness, dataset_name: str, run_root: Path) -> Path:
    dataset = harness.config["datasets"][dataset_name]
    input_dir = run_root / dataset_name / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    question_dir = ROOT / harness.config["output_dir"] / dataset_name
    papers = []
    for document in dataset["documents"]:
        filename = f"{document['id']}.json"
        shutil.copy2(
            question_dir / f"{document['id']}.questions.json",
            input_dir / filename,
        )
        papers.append({
            "paper_id": document["id"],
            "title": document["title"],
            "file": filename,
        })
    manifest_path = input_dir / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "papers": papers},
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return manifest_path


def build_dataset(
    harness: Harness,
    dataset_name: str,
    graph_config: Path,
) -> dict[str, Any]:
    """Build one viewer-ready graph without a manual manifest handoff."""

    study = harness.config["study"]
    run_root = ROOT / study["run_root"]
    harness.questions(dataset_name)
    manifest_path = _write_graph_manifest(harness, dataset_name, run_root)
    graph_run_dir = run_root / dataset_name / "graph"
    summary = run_revision(manifest_path, graph_run_dir, graph_config)
    return {
        "dataset_id": dataset_name,
        "dataset_dir": Path(summary["dataset_dir"]),
        "graph": summary,
    }


def run_study(
    config_path: Path,
    dataset_selection: str,
    graph_config: Path,
    *,
    force_documents: bool = False,
) -> dict[str, Any]:
    harness = Harness(config_path.resolve(), force=force_documents)
    study_config = harness.config["study"]
    configured = list(study_config["datasets"])
    selected = configured if dataset_selection == "all" else [dataset_selection]
    unknown = [name for name in selected if name not in configured]
    if unknown:
        raise ValueError(f"Unknown study dataset: {unknown[0]}")

    results = {
        name: build_dataset(harness, name, graph_config.resolve())
        for name in selected
    }
    site_root = ROOT / study_config["site_dir"]
    if len(results) == 1:
        name = selected[0]
        settings = study_config["datasets"][name]
        output_dir = _next_build(site_root / name)
        descriptor = package_dataset(
            results[name]["dataset_dir"],
            output_dir,
            VIEWER_PATH,
            name,
            settings["label"],
        )
        package = {"output_dir": str(output_dir), "dataset": descriptor}
    else:
        output_dir = _next_build(site_root)
        package_inputs = {
            name: {
                **study_config["datasets"][name],
                "dataset_dir": result["dataset_dir"],
            }
            for name, result in results.items()
        }
        package = {
            "output_dir": str(output_dir),
            **package_study(package_inputs, output_dir, VIEWER_PATH),
        }
    return {"datasets": results, "package": package}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="configured dataset id or all")
    parser.add_argument("--config", type=Path, default=DOCUMENT_CONFIG)
    parser.add_argument("--graph-config", type=Path, default=GRAPH_CONFIG)
    parser.add_argument(
        "--force-documents",
        action="store_true",
        help="rerun completed extraction and section-question calls",
    )
    args = parser.parse_args()
    result = run_study(
        args.config,
        args.dataset,
        args.graph_config,
        force_documents=args.force_documents,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
