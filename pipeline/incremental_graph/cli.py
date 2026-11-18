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
                "paragraphs": sum(len(section.paragraphs) for section in paper.sections),
                "section_role_statements_required": manifest.max_granularity != "paragraph",
                "missing_section_role_statements": (
                    sum(not section.role_statement for section in paper.sections)
                    if manifest.max_granularity != "paragraph"
                    else 0
                ),
                "missing_paragraph_role_statements": sum(
                    not paragraph.role_statement
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
    start.add_argument("--jev", action="store_true", help="Use Jev for all match selection")
    start.add_argument("--jev-model", help="Pinned Jev version, for example jev-1.14.0")
    start.add_argument("--jev-max-calls", type=int, help="Maximum Jev HTTP calls per process")
    start.add_argument(
        "--jev-long-context",
        action="store_true",
        help="Resend size-rejected Jev requests with TypeSafe's long-context header (262k)",
    )
    start.add_argument("--max-api-responses", type=int, help="Generative provider response guard")
    start.add_argument(
        "--cache-from",
        type=Path,
        help="Copy an existing run's cache; reuse only exact matching request fingerprints",
    )
    start.add_argument(
        "--section-fan-in",
        action="store_true",
        help="Experimental: admit one-way sections beside a reciprocal same-paper core",
    )
    add = commands.add_parser("add", help="Append prepared papers in manifest order")
    add.add_argument("manifest", type=Path)
    add.add_argument("run_dir", type=Path)
    retry = commands.add_parser("retry", help="Retry saved inputs, reusing successful judgments")
    retry.add_argument("run_dir", type=Path)
    retry.add_argument("--paper-index", type=int)
    retry.add_argument("--stage")
    retry.add_argument(
        "--config", type=Path, help="Same scientific config with updated execution limits"
    )
    retry.add_argument("--jev-max-calls", type=int, help="Maximum Jev HTTP calls for this attempt")
    retry.add_argument("--max-api-responses", type=int, help="Generative provider response guard")
    for command in (start, retry):
        command.add_argument(
            "--sections-only",
            action="store_true",
            help="Finish section matching for every paper without starting paragraph stages",
        )
    validate = commands.add_parser("validate", help="Validate prepared inputs without model calls")
    validate.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if args.command == "start":
        result = start_graph(
            args.manifest,
            args.run_dir,
            args.config,
            provider=args.provider,
            model=args.model,
            jev=args.jev,
            jev_model=args.jev_model,
            jev_max_calls=args.jev_max_calls,
            max_api_responses=args.max_api_responses,
            cache_from=args.cache_from,
            sections_only=args.sections_only,
            section_fan_in=args.section_fan_in,
            jev_long_context_retry=args.jev_long_context,
        )
    elif args.command == "add":
        result = add_papers(args.manifest, args.run_dir)
    elif args.command == "retry":
        result = retry_graph(
            args.run_dir,
            paper_index=args.paper_index,
            stage_id=args.stage,
            sections_only=args.sections_only,
            config_path=args.config,
            jev_max_calls=args.jev_max_calls,
            max_api_responses=args.max_api_responses,
        )
    else:
        result = validate_manifest(args.manifest)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
