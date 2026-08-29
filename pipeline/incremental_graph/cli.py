"""Command-line entrypoint for incremental question-group graph runs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .configuration import PromptRepository, load_pipeline_config
from .input_data import load_manifest
from .journal import write_json
from .llm import AnthropicJudgmentProvider
from .runner import IncrementalGraphRunner


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PACKAGE_DIR / "configs" / "incremental-v1.yaml"


def run_revision(
    manifest_path: Path,
    run_dir: Path,
    config_path: Path,
    *,
    force_paper_index: int | None = None,
    force_stage_id: str | None = None,
) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    config_path = config_path.resolve()
    run_dir = run_dir.resolve()
    _, papers = load_manifest(manifest_path)
    config = load_pipeline_config(config_path)
    if force_paper_index is not None and not 1 <= force_paper_index <= len(papers):
        raise ValueError(f"paper index must be between 1 and {len(papers)}")
    stage_ids = {stage.id for stage in config.stages}
    if force_stage_id is not None and force_stage_id not in stage_ids:
        raise ValueError(f"unknown stage {force_stage_id!r}; choose one of {sorted(stage_ids)}")

    revisions_dir = run_dir / "revisions"
    revisions_dir.mkdir(parents=True, exist_ok=True)
    revision_number = _next_revision(revisions_dir)
    revision_dir = revisions_dir / f"revision-{revision_number:04d}"
    prompts = PromptRepository(config.prompt_root, config.context_root)
    judge = AnthropicJudgmentProvider(
        prompts,
        config.model,
        run_dir / "cache",
        config.skill_root,
    )
    runner = IncrementalGraphRunner(
        config,
        judge,
        revision_dir,
        force_paper_index=force_paper_index,
        force_stage_id=force_stage_id,
    )
    try:
        summary = runner.run(papers)
    except Exception as error:
        write_json(revision_dir / "failure.json", {"type": type(error).__name__, "message": str(error)})
        raise

    metadata = {
        "schema_version": 1,
        "manifest_path": str(manifest_path),
        "config_path": str(config_path),
        "current_revision": revision_number,
        "current_revision_dir": str(revision_dir),
    }
    write_json(run_dir / "run.json", metadata)
    return summary


def retry_revision(run_dir: Path, paper_index: int, stage_id: str) -> dict[str, Any]:
    metadata_path = run_dir.resolve() / "run.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return run_revision(
        Path(metadata["manifest_path"]),
        run_dir,
        Path(metadata["config_path"]),
        force_paper_index=paper_index,
        force_stage_id=stage_id,
    )


def current_categories(run_dir: Path) -> dict[str, Any]:
    metadata = json.loads((run_dir.resolve() / "run.json").read_text(encoding="utf-8"))
    path = Path(metadata["current_revision_dir"]) / "dataset" / "graph_categories.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load and summarize canonical inputs without making model calls."""

    manifest, papers = load_manifest(manifest_path.resolve())
    return {
        "schema_version": manifest.schema_version,
        "paper_order": [paper.paper_id for paper in papers],
        "papers": [
            {
                "paper_id": paper.paper_id,
                "sections": len(paper.sections),
                "top_level_sections": sum(section.kind == "section" for section in paper.sections),
                "subsections": sum(section.kind == "subsection" for section in paper.sections),
                "paragraphs": sum(len(section.paragraphs) for section in paper.sections),
                "missing_section_questions": sum(not section.question for section in paper.sections),
                "missing_paragraph_questions": sum(
                    not paragraph.question
                    for section in paper.sections
                    for paragraph in section.paragraphs
                ),
            }
            for paper in papers
        ],
    }


def _next_revision(revisions_dir: Path) -> int:
    numbers = []
    for path in revisions_dir.iterdir():
        match = re.fullmatch(r"revision-(\d+)", path.name)
        if path.is_dir() and match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run all papers in manifest order as a new revision")
    run_parser.add_argument("manifest", type=Path)
    run_parser.add_argument("run_dir", type=Path)
    run_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    retry_parser = subparsers.add_parser("retry", help="Retry one stage and replay the ordered corpus")
    retry_parser.add_argument("run_dir", type=Path)
    retry_parser.add_argument("--paper-index", type=int, required=True)
    retry_parser.add_argument("--stage", required=True)

    categories_parser = subparsers.add_parser("categories", help="Print current deterministic graph categories")
    categories_parser.add_argument("run_dir", type=Path)

    validate_parser = subparsers.add_parser("validate", help="Validate and summarize a paper manifest")
    validate_parser.add_argument("manifest", type=Path)

    args = parser.parse_args()
    if args.command == "run":
        summary = run_revision(args.manifest, args.run_dir, args.config)
        print(json.dumps(summary, indent=2))
    elif args.command == "retry":
        summary = retry_revision(args.run_dir, args.paper_index, args.stage)
        print(json.dumps(summary, indent=2))
    elif args.command == "categories":
        print(json.dumps(current_categories(args.run_dir), indent=2))
    else:
        print(json.dumps(validate_manifest(args.manifest), indent=2))


if __name__ == "__main__":
    main()
