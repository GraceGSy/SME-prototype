"""Create content-only or whole-section derivatives from canonical documents."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .document import (
    flatten_to_single_section,
    read_json,
    strip_questions,
    validate_document,
    write_json,
)


def prepare_content_corpus(
    manifest_path: Path,
    output_dir: Path,
    *,
    whole_section: bool = False,
) -> int:
    """Strip questions and optionally collapse each document to one section."""

    manifest_path = manifest_path.resolve()
    output_dir = output_dir.resolve()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    papers = manifest.get("papers", [])
    if manifest.get("schema_version") != 1 or not papers:
        raise ValueError("Expected a schema-version 1 manifest with at least one paper")

    output_dir.mkdir(parents=True, exist_ok=True)
    content_papers = []
    for paper in papers:
        filename = Path(paper["file"])
        document = strip_questions(read_json(manifest_path.parent / filename))
        validate_document(document)
        if whole_section:
            document = flatten_to_single_section(document, paper["title"])
        output_name = (
            filename.name
            if filename.name.endswith(".content.json")
            else f"{filename.stem}.content.json"
        )
        write_json(output_dir / output_name, document)
        content_papers.append({**paper, "file": output_name})

    output_manifest = {**manifest, "papers": content_papers}
    if whole_section:
        output_manifest["max_granularity"] = "paragraph"
    (output_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            output_manifest,
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return len(papers)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--whole-section",
        action="store_true",
        help="Flatten each document into one section and select paragraph-first graphing",
    )
    args = parser.parse_args()
    count = prepare_content_corpus(
        args.manifest,
        args.output_dir,
        whole_section=args.whole_section,
    )
    print(f"Prepared {count} content-only documents in {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
