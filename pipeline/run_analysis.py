"""Run the complete Question Atlas analysis as one reproducible job."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from env_utils import load_dotenv_upwards

PIPELINE_DIR = Path(__file__).resolve().parent
REPO_DIR = PIPELINE_DIR.parent
ACTIVE_SOURCE_FILES = [
    "analysis_server.py",
    "run_analysis.py",
    "extract_sections.py",
    "attach_section_text.py",
    "extract_fine_grained.py",
    "relabel_section_context.py",
    "relabel_full_paper.py",
    "match_tags.py",
    "prune_bidirectional.py",
    "group_matches.py",
    "summarize_groups.py",
    "match_groups.py",
    "prune_group_bidirectional.py",
    "group_groups.py",
    "summarize_super_groups.py",
    "question_matching.py",
    "question_synthesis.py",
    "refine_epochs.py",
    "align_graphs.py",
    "cache_utils.py",
    "env_utils.py",
    "pdf_text.py",
    "pipeline_paths.py",
    "requirements.txt",
    "section_schema.py",
    "text_locate.py",
    "viz/tag_matches_viewer.html",
]

REUSE_SCOPES = ("fresh", "paragraph_corpus", "pre_epoch")
PARAGRAPH_CONTEXTS = ("section", "fixed_section", "full_paper")
ASSIGNMENT_CONTEXTS = (
    "question_only",
    "representative_group_paragraphs",
    "all_group_paragraphs",
)
PRE_EPOCH_ARTIFACTS = (
    "tag_matches.json",
    "bidirectional_matches.json",
    "quote_groups.json",
    "group_matches.json",
    "bidirectional_group_matches.json",
    "group_of_groups.json",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_paper_id(path: Path, used: set[str]) -> str:
    stem = re.sub(r"^[0-9a-f]{32}--", "", path.stem, flags=re.IGNORECASE)
    base = re.sub(r"[^a-zA-Z0-9_.-]+", "_", stem).strip("._-") or "paper"
    candidate = base[:100]
    suffix = 2
    while candidate in used:
        trailer = f"_{suffix}"
        candidate = base[: 100 - len(trailer)] + trailer
        suffix += 1
    used.add(candidate)
    return candidate


def stage_input_papers(
    paths: list[Path], output: Path, display_names: dict[str, str] | None = None
) -> tuple[list[Path], list[dict]]:
    input_dir = output / "input_papers"
    input_dir.mkdir(parents=True, exist_ok=True)
    staged = []
    metadata = []
    used: set[str] = set()
    display_names = display_names or {}
    for source in paths:
        original_filename = display_names.get(str(source.resolve()), source.name)
        paper_id = safe_paper_id(Path(original_filename), used)
        destination = input_dir / f"{paper_id}.pdf"
        shutil.copy2(source, destination)
        digest = file_sha256(destination)
        staged.append(destination)
        metadata.append(
            {
                "paper_id": paper_id,
                "original_filename": original_filename,
                "source_path": str(source),
                "stored_path": str(destination),
                "size_bytes": destination.stat().st_size,
                "sha256": digest,
            }
        )
    return staged, metadata


def _bundle_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(file_sha256(path).encode("ascii"))
    return digest.hexdigest()


def reuse_source_artifacts(
    source_dir: Path,
    output: Path,
    scope: str,
    paper_metadata: list[dict],
) -> dict:
    """Copy a controlled upstream state while verifying exact PDF identity."""
    source_dir = source_dir.resolve()
    if scope not in REUSE_SCOPES or scope == "fresh":
        raise ValueError(f"Unsupported source reuse scope: {scope!r}")
    metadata_path = source_dir / "analysis_run.json"
    manifest_path = source_dir / "manifest.json"
    if not metadata_path.is_file() or not manifest_path.is_file():
        raise ValueError("Source run lacks analysis_run.json or manifest.json")
    source_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if source_metadata.get("status") != "complete":
        raise ValueError("Source run is not complete")

    expected = {
        item["paper_id"]: item["sha256"] for item in source_metadata.get("papers", [])
    }
    received = {item["paper_id"]: item["sha256"] for item in paper_metadata}
    if expected != received:
        raise ValueError(
            "Selected PDFs do not exactly match the source run's paper ids and SHA-256 hashes"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("Source run manifest is empty or invalid")
    filenames = ["manifest.json"]
    paragraph_count = 0
    paragraph_ids: list[str] = []
    for entry in manifest:
        filename = str(entry.get("file", ""))
        if not filename or Path(filename).name != filename:
            raise ValueError(f"Unsafe source artifact name: {filename!r}")
        paper_path = source_dir / filename
        if not paper_path.is_file():
            raise ValueError(f"Source run lacks paper artifact {filename!r}")
        paper = json.loads(paper_path.read_text(encoding="utf-8"))
        paragraphs = paper.get("paragraphs", [])
        if not paragraphs:
            raise ValueError(f"Source paper artifact {filename!r} has no paragraphs")
        paragraph_count += len(paragraphs)
        paragraph_ids.extend(
            f"{paper.get('paper_id')}:{paragraph.get('id')}" for paragraph in paragraphs
        )
        filenames.append(filename)
    if scope == "pre_epoch":
        filenames.extend(PRE_EPOCH_ARTIFACTS)

    copied: list[Path] = []
    for filename in dict.fromkeys(filenames):
        source = source_dir / filename
        if not source.is_file():
            raise ValueError(f"Source run lacks required {scope} artifact {filename!r}")
        destination = output / filename
        shutil.copy2(source, destination)
        copied.append(destination)
    return {
        "source_run_id": source_metadata.get("run_id", source_dir.name),
        "reuse_scope": scope,
        "source_directory": str(source_dir),
        "copied_files": [path.name for path in copied],
        "copied_bundle_sha256": _bundle_sha256(copied),
        "paragraph_count": paragraph_count,
        "paragraph_ids_sha256": hashlib.sha256(
            "\n".join(paragraph_ids).encode("utf-8")
        ).hexdigest(),
    }


def git_provenance() -> dict:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_DIR,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=REPO_DIR,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return {"commit": commit, "dirty": bool(status.strip())}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def source_provenance() -> dict:
    files = {}
    for relative in ACTIVE_SOURCE_FILES:
        path = PIPELINE_DIR / relative
        if path.is_file():
            files[relative.replace("\\", "/")] = file_sha256(path)
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "git": git_provenance(),
        "source_bundle_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": files,
    }


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def prompt_manifest() -> dict:
    from extract_fine_grained import (
        SYSTEM_PROMPT as paragraph_system,
    )
    from extract_fine_grained import (
        USER_PROMPT_TEMPLATE as paragraph_user,
    )
    from extract_fine_grained import (
        _build_tool as paragraph_tool,
    )
    from extract_sections import (
        SYSTEM_PROMPT as section_system,
    )
    from extract_sections import (
        USER_PROMPT_TEMPLATE as section_user,
    )
    from extract_sections import (
        _build_tool as section_tool,
    )
    from question_matching import SYSTEM_PROMPT as question_match_system
    from question_matching import USER_PROMPT_TEMPLATE as question_match_user
    from question_matching import _tool as question_match_tool
    from question_synthesis import SYSTEM_PROMPT as synthesis_system
    from question_synthesis import USER_PROMPT_TEMPLATE as synthesis_user
    from question_synthesis import _tool as synthesis_tool
    from refine_epochs import (
        ASSIGNMENT_SYSTEM_PROMPT,
        ASSIGNMENT_USER_PROMPT_TEMPLATE,
        EVIDENCE_ASSIGNMENT_SYSTEM_PROMPT,
        EVIDENCE_ASSIGNMENT_USER_PROMPT_TEMPLATE,
        REPRESENTATIVE_ASSIGNMENT_SYSTEM_PROMPT,
        REPRESENTATIVE_ASSIGNMENT_USER_PROMPT_TEMPLATE,
        _assignment_tool,
    )
    from relabel_full_paper import SYSTEM_PROMPT as full_paper_system
    from relabel_full_paper import USER_PROMPT_TEMPLATE as full_paper_user
    from relabel_full_paper import _tool as full_paper_tool
    from relabel_section_context import SYSTEM_PROMPT as fixed_section_system
    from relabel_section_context import USER_PROMPT_TEMPLATE as fixed_section_user
    from relabel_section_context import _tool as fixed_section_tool

    manifest = {
        "section_extraction": {
            "system": section_system,
            "user_template": section_user,
            "tool": section_tool(),
        },
        "paragraph_extraction": {
            "system": paragraph_system,
            "user_template": paragraph_user,
            "tool": paragraph_tool(),
        },
        "full_paper_paragraph_relabeling": {
            "system": full_paper_system,
            "user_template": full_paper_user,
            "tool_template": full_paper_tool(["<fixed_paragraph_id>"]),
        },
        "fixed_section_paragraph_relabeling": {
            "system": fixed_section_system,
            "user_template": fixed_section_user,
            "tool_template": fixed_section_tool(["<fixed_paragraph_id>"]),
        },
        "question_synthesis": {
            "system": synthesis_system,
            "user_template": synthesis_user,
            "tool": synthesis_tool(),
        },
        "group_question_matching": {
            "system": question_match_system,
            "user_template": question_match_user,
            "tool_template": question_match_tool(
                ["<source_group_id>", "<candidate_group_id>"], 1
            ),
        },
        "epoch_assignment": {
            "system": ASSIGNMENT_SYSTEM_PROMPT,
            "user_template": ASSIGNMENT_USER_PROMPT_TEMPLATE,
            "tool_template": _assignment_tool(
                ["<paper_id>:<paragraph_id>"], ["<current_group_id>"]
            ),
        },
        "epoch_assignment_all_group_paragraphs": {
            "system": EVIDENCE_ASSIGNMENT_SYSTEM_PROMPT,
            "user_template": EVIDENCE_ASSIGNMENT_USER_PROMPT_TEMPLATE,
            "tool_template": _assignment_tool(
                ["<paper_id>:<paragraph_id>"], ["<current_group_id>"]
            ),
        },
        "epoch_assignment_representative_group_paragraphs": {
            "system": REPRESENTATIVE_ASSIGNMENT_SYSTEM_PROMPT,
            "user_template": REPRESENTATIVE_ASSIGNMENT_USER_PROMPT_TEMPLATE,
            "tool_template": _assignment_tool(
                ["<paper_id>:<paragraph_id>"], ["<current_group_id>"]
            ),
        },
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return {"sha256": hashlib.sha256(canonical).hexdigest(), "prompts": manifest}


def stage(
    stage_id: str, label: str, script: str, args: list[str], env: dict[str, str]
) -> None:
    print("@@STAGE " + json.dumps({"id": stage_id, "label": label}), flush=True)
    subprocess.run(
        [sys.executable, str(PIPELINE_DIR / script), *args],
        cwd=PIPELINE_DIR,
        env=env,
        check=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "papers",
        nargs="*",
        help="PDF paths; defaults to every PDF in the papers directory",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-id", default="manual")
    parser.add_argument(
        "--model", default=os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
    )
    parser.add_argument("--max-epochs", type=int, default=3)
    parser.add_argument("--section-weight", type=float, default=0.15)
    parser.add_argument("--question-stability-threshold", type=float, default=0.97)
    parser.add_argument("--section-context-max-chars", type=int, default=0)
    parser.add_argument("--paragraph-chunk-chars", type=int, default=50_000)
    parser.add_argument("--assignment-batch-chars", type=int, default=80_000)
    parser.add_argument("--representative-per-paper", type=int, default=2)
    parser.add_argument("--representative-max-per-group", type=int, default=6)
    parser.add_argument("--match-top-k", type=int, default=3)
    parser.add_argument("--section-group-threshold", type=float, default=0.33)
    parser.add_argument("--paragraph-group-threshold", type=float, default=0.45)
    parser.add_argument("--supergroup-threshold", type=float, default=0.33)
    parser.add_argument("--experiment-label", default="")
    parser.add_argument(
        "--paragraph-context", choices=PARAGRAPH_CONTEXTS, default="section"
    )
    parser.add_argument(
        "--assignment-context",
        choices=ASSIGNMENT_CONTEXTS,
        default="question_only",
    )
    parser.add_argument("--reuse-scope", choices=REUSE_SCOPES, default="fresh")
    parser.add_argument("--source-run-dir")
    args = parser.parse_args()

    if args.max_epochs < 0:
        parser.error("--max-epochs must be non-negative")
    for name in (
        "section_weight",
        "question_stability_threshold",
        "section_group_threshold",
        "paragraph_group_threshold",
        "supergroup_threshold",
    ):
        if not 0 <= getattr(args, name) <= 1:
            parser.error(f"--{name.replace('_', '-')} must be between 0 and 1")
    if args.section_context_max_chars < 0 or args.paragraph_chunk_chars < 0:
        parser.error("context and chunk character limits must be non-negative")
    if args.assignment_batch_chars < 10_000:
        parser.error("--assignment-batch-chars must be at least 10,000")
    if args.representative_per_paper < 1:
        parser.error("--representative-per-paper must be positive")
    if args.representative_max_per_group < 1:
        parser.error("--representative-max-per-group must be positive")
    if args.match_top_k < 1:
        parser.error("--match-top-k must be positive")
    if args.reuse_scope == "fresh" and args.source_run_dir:
        parser.error("--source-run-dir requires a non-fresh --reuse-scope")
    if args.reuse_scope != "fresh" and not args.source_run_dir:
        parser.error("a non-fresh --reuse-scope requires --source-run-dir")
    if args.reuse_scope == "pre_epoch" and args.paragraph_context != "section":
        parser.error("pre_epoch reuse cannot relabel paragraphs; use section context")
    return args


def main() -> None:
    args = parse_args()
    load_dotenv_upwards(REPO_DIR)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set and no ancestor .env supplied it"
        )

    papers = [Path(value).resolve() for value in args.papers]
    if not papers:
        papers = sorted((REPO_DIR / "papers").glob("*.pdf"))
    if len(papers) < 2:
        raise SystemExit("Select at least two PDF inputs for cross-paper comparison")
    missing = [str(path) for path in papers if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing input PDFs: {missing}")

    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        input_display_names = json.loads(os.environ.get("SME_INPUT_NAMES_JSON", "{}"))
    except json.JSONDecodeError as exc:
        raise SystemExit("SME_INPUT_NAMES_JSON must be valid JSON") from exc
    if not isinstance(input_display_names, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in input_display_names.items()
    ):
        raise SystemExit(
            "SME_INPUT_NAMES_JSON must map source paths to display filenames"
        )
    staged_papers, paper_metadata = stage_input_papers(
        papers, output, input_display_names
    )
    source_corpus = None
    if args.reuse_scope != "fresh":
        source_corpus = reuse_source_artifacts(
            Path(args.source_run_dir), output, args.reuse_scope, paper_metadata
        )

    runtime_settings = {
        "experiment_label": args.experiment_label.strip(),
        "model": args.model,
        "max_epochs": args.max_epochs,
        "section_weight": args.section_weight,
        "question_stability_threshold": args.question_stability_threshold,
        "section_context_max_chars": args.section_context_max_chars,
        "paragraph_chunk_chars": args.paragraph_chunk_chars,
        "assignment_batch_chars": args.assignment_batch_chars,
        "representative_per_paper": args.representative_per_paper,
        "representative_max_per_group": args.representative_max_per_group,
        "match_top_k": args.match_top_k,
        "section_group_threshold": args.section_group_threshold,
        "paragraph_group_threshold": args.paragraph_group_threshold,
        "supergroup_threshold": args.supergroup_threshold,
        "paragraph_context": args.paragraph_context,
        "assignment_context": args.assignment_context,
        "reuse_scope": args.reuse_scope,
        "source_run_id": source_corpus["source_run_id"] if source_corpus else None,
    }
    env = os.environ.copy()
    env.update(
        {
            "SME_OUTPUT_DIR": str(output),
            "SME_PAPERS_DIR": str(output / "input_papers"),
            "SME_RUN_ID": args.run_id,
            "SME_EXTRACT_MODEL": args.model,
            "SME_SECTION_CONTEXT_MAX_CHARS": str(args.section_context_max_chars),
            "SME_PARAGRAPH_CHUNK_CHARS": str(args.paragraph_chunk_chars),
            "SME_ASSIGNMENT_BATCH_CHARS": str(args.assignment_batch_chars),
            "SME_REPRESENTATIVE_PER_PAPER": str(args.representative_per_paper),
            "SME_REPRESENTATIVE_MAX_PER_GROUP": str(
                args.representative_max_per_group
            ),
            "SME_MATCH_TOP_K": str(args.match_top_k),
            "SME_SECTION_GROUP_THRESHOLD": str(args.section_group_threshold),
            "SME_PARAGRAPH_GROUP_THRESHOLD": str(args.paragraph_group_threshold),
            "SME_SUPERGROUP_THRESHOLD": str(args.supergroup_threshold),
            "SME_PARAGRAPH_CONTEXT": args.paragraph_context,
            "SME_ASSIGNMENT_CONTEXT": args.assignment_context,
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
        }
    )
    os.environ.update(
        {key: value for key, value in env.items() if key.startswith("SME_")}
    )

    prompts = prompt_manifest()
    (output / "prompt_manifest.json").write_text(
        json.dumps(prompts, indent=2), encoding="utf-8"
    )
    metadata = {
        "schema_version": 5,
        "run_id": args.run_id,
        "status": "running",
        "started_at": utc_now(),
        "completed_at": None,
        "model": args.model,
        "papers": paper_metadata,
        "config": runtime_settings,
        "runtime": {
            "python": sys.version.split()[0],
            "anthropic": package_version("anthropic"),
            "pdfplumber": package_version("pdfplumber"),
            "pydantic": package_version("pydantic"),
            "platform": platform.platform(),
            "python_utf8": True,
        },
        "source_provenance": source_provenance(),
        "source_corpus": source_corpus,
        "prompt_manifest": {
            "file": "prompt_manifest.json",
            "sha256": prompts["sha256"],
        },
        "error": None,
    }
    metadata_path = output / "analysis_run.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    try:
        if args.reuse_scope == "fresh":
            stage(
                "sections",
                "Extracting section questions",
                "extract_sections.py",
                [str(path) for path in staged_papers],
                env,
            )
            stage(
                "section_text",
                "Attaching complete section text",
                "attach_section_text.py",
                [],
                env,
            )
            stage(
                "paragraphs",
                "Extracting paragraph questions and provenance",
                "extract_fine_grained.py",
                [],
                env,
            )
        else:
            print(
                "@@STAGE "
                + json.dumps(
                    {
                        "id": "reuse",
                        "label": f"Reusing {args.reuse_scope} from {source_corpus['source_run_id']}",
                    }
                ),
                flush=True,
            )

        if args.paragraph_context == "fixed_section":
            stage(
                "fixed_section_context",
                "Relabeling fixed paragraphs with complete-section context",
                "relabel_section_context.py",
                [],
                env,
            )
        elif args.paragraph_context == "full_paper":
            stage(
                "full_paper_context",
                "Relabeling fixed paragraphs with complete-paper context",
                "relabel_full_paper.py",
                [],
                env,
            )

        if args.reuse_scope != "pre_epoch":
            stage(
                "candidates",
                "Computing cross-paper question candidates",
                "match_tags.py",
                [],
                env,
            )
            stage(
                "reciprocal",
                "Keeping reciprocal candidates",
                "prune_bidirectional.py",
                [],
                env,
            )
            stage(
                "paragraph_groups",
                "Building initial paragraph groups",
                "group_matches.py",
                [],
                env,
            )
            stage(
                "group_questions",
                "Synthesizing group questions from complete paragraphs",
                "summarize_groups.py",
                [],
                env,
            )
            stage(
                "group_candidates",
                "Matching initial group questions",
                "match_groups.py",
                [],
                env,
            )
            stage(
                "group_reciprocal",
                "Keeping reciprocal group matches",
                "prune_group_bidirectional.py",
                [],
                env,
            )
            stage(
                "supergroups",
                "Building initial supergroups",
                "group_groups.py",
                [],
                env,
            )
            stage(
                "supergroup_questions",
                "Synthesizing supergroup questions from complete paragraphs",
                "summarize_super_groups.py",
                [],
                env,
            )
        stage(
            "epochs",
            "Running Claude assignment and question-refinement epochs",
            "refine_epochs.py",
            [
                "--max-epochs",
                str(args.max_epochs),
                "--section-weight",
                str(args.section_weight),
                "--merge-lexical-threshold",
                str(args.supergroup_threshold),
                "--question-stability-threshold",
                str(args.question_stability_threshold),
                "--match-top-k",
                str(args.match_top_k),
                "--assignment-context",
                args.assignment_context,
                "--representative-per-paper",
                str(args.representative_per_paper),
                "--representative-max-per-group",
                str(args.representative_max_per_group),
            ],
            env,
        )
        metadata["status"] = "complete"
    except Exception as exc:
        metadata["status"] = "failed"
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        metadata["completed_at"] = utc_now()
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
