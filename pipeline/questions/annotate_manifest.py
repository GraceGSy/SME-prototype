"""Annotate every paper JSON listed in an incremental-graph manifest.

Expected manifest shape:

    papers:
      - paper_id: corpusstudio
        title: CorpusStudio
        file: /absolute/or/relative/path.json

Relative `file` paths are resolved against the manifest's directory.

Usage:
    python -m pipeline.questions.annotate_manifest path/to/manifest.yaml
    python -m pipeline.questions.annotate_manifest path/to/manifest.yaml --force
    python -m pipeline.questions.annotate_manifest path/to/manifest.yaml --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from .annotate import (
    DEFAULT_CACHE_DIR,
    DEFAULT_MODEL,
    annotate_file,
    make_ask_fn,
)


def load_manifest_files(path: Path) -> list[tuple[str, str, Path]]:
    path = Path(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "papers" not in payload:
        raise ValueError(f"{path} must be a mapping with a 'papers' list")
    entries: list[tuple[str, str, Path]] = []
    for item in payload["papers"]:
        paper_id = str(item.get("paper_id") or "")
        title = str(item.get("title") or paper_id)
        raw_file = item.get("file")
        if not paper_id or not raw_file:
            raise ValueError(f"{path} has a papers entry missing paper_id or file: {item!r}")
        json_path = (path.parent / raw_file).resolve()
        entries.append((paper_id, title, json_path))
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="manifest.yaml listing paper JSON files")
    parser.add_argument("--force", action="store_true", help="recompute even if the field is already present")
    parser.add_argument("--dry-run", action="store_true", help="print serialized payloads without calling the API or writing")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"manifest not found: {args.manifest}", file=sys.stderr)
        raise SystemExit(1)

    entries = load_manifest_files(args.manifest)
    ask_fn = None
    if not args.dry_run:
        from anthropic import Anthropic

        ask_fn = make_ask_fn(Anthropic(), args.model, Path(args.cache_dir))

    failures: list[str] = []
    for index, (paper_id, title, json_path) in enumerate(entries, start=1):
        print(f"\n=== [{index}/{len(entries)}] {paper_id}: {title} ===")
        if not json_path.exists():
            print(f"skipping {json_path}: not found", file=sys.stderr)
            failures.append(paper_id)
            continue
        try:
            annotate_file(
                json_path,
                force=args.force,
                dry_run=args.dry_run,
                ask_fn=ask_fn,
                model=args.model,
                cache_dir=args.cache_dir,
            )
        except SystemExit as error:
            if error.code in (0, None):
                raise
            print(f"{paper_id}: annotate_file exited {error.code}", file=sys.stderr)
            failures.append(paper_id)

    print(f"\nfinished {len(entries)} papers; failed={len(failures)}")
    if failures:
        print("failed paper_ids: " + ", ".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
