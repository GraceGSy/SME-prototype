"""CLI for graph construction from prepared documents; never runs extraction."""

import argparse
import json
from pathlib import Path
from typing import Any

from .input_data import load_manifest
from .runs import DEFAULT_CONFIG, add_papers, retry_graph, start_graph


def validate_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load and summarize canonical inputs without making model calls."""

    manifest, papers = load_manifest(manifest_path.resolve())
    return {
        "schema_version": manifest.schema_version,
        "max_granularity": manifest.max_granularity,
        "paper_order": [paper.paper_id for paper in papers],
        "papers": [
            {
                "paper_id": paper.paper_id,
                "sections": len(paper.sections),
                "top_level_sections": sum(section.kind == "section" for section in paper.sections),
                "subsections": sum(section.kind == "subsection" for section in paper.sections),
                "paragraphs": sum(len(section.paragraphs) for section in paper.sections),
                "section_questions_required": manifest.max_granularity != "paragraph",
                "missing_section_questions": (
                    sum(not section.question for section in paper.sections)
                    if manifest.max_granularity != "paragraph"
                    else 0
                ),
                "missing_paragraph_questions": sum(
                    not paragraph.question
                    for section in paper.sections
                    for paragraph in section.paragraphs
                ),
            }
            for paper in papers
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="Start a new graph with at least two prepared papers")
    start.add_argument("manifest", type=Path)
    start.add_argument("run_dir", type=Path)
    start.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    start.add_argument("--provider", choices=["anthropic", "openai"])
    start.add_argument("--model", help="Model name; supply together with --provider")
    add = commands.add_parser("add", help="Append prepared papers in manifest order")
    add.add_argument("manifest", type=Path)
    add.add_argument("run_dir", type=Path)
    retry = commands.add_parser("retry", help="Retry saved inputs, reusing successful judgments")
    retry.add_argument("run_dir", type=Path)
    retry.add_argument("--paper-index", type=int)
    retry.add_argument("--stage")
    validate = commands.add_parser("validate", help="Validate prepared inputs without model calls")
    validate.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if args.command == "start":
        result = start_graph(
            args.manifest, args.run_dir, args.config, provider=args.provider, model=args.model
        )
    elif args.command == "add":
        result = add_papers(args.manifest, args.run_dir)
    elif args.command == "retry":
        result = retry_graph(args.run_dir, paper_index=args.paper_index, stage_id=args.stage)
    else:
        result = validate_manifest(args.manifest)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
