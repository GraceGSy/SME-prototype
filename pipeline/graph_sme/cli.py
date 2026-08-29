"""Extract proposition graphs from explicitly supplied PDF files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def run_one(pdf_path: Path) -> None:
    # Keep optional PDF/model dependencies out of argument parsing so --help
    # remains available before the project environment is installed.
    from .extract import extract_graph
    from .pdf_text import extract_pdf_text

    paper_id = pdf_path.stem
    print(f"[{paper_id}] extracting text from {pdf_path.name} ...")
    text = extract_pdf_text(str(pdf_path))
    print(f"[{paper_id}] {len(text):,} chars of text; calling model ...")

    graph = extract_graph(paper_id=paper_id, title_hint=paper_id, text=text)

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"{paper_id}.json"
    out_path.write_text(json.dumps(graph.model_dump(), indent=2))

    summary = graph.systematicity_summary()
    print(
        f"[{paper_id}] wrote {out_path} "
        f"({len(graph.entities)} entities, {summary['num_propositions']} propositions, "
        f"max_order={summary['max_order']}, mean_order={summary['mean_order']:.2f})"
    )


def write_manifest() -> None:
    """List every graph currently in output/ so the viewer's dropdown stays in sync."""
    entries = []
    for path in sorted(OUTPUT_DIR.glob("*.json")):
        if path.name == "manifest.json":
            continue
        data = json.loads(path.read_text())
        entries.append({"paper_id": data["paper_id"], "title": data["title"], "file": path.name})
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(entries, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, nargs="+", help="PDF files to extract")
    args = parser.parse_args()
    for path in args.pdf:
        if not path.exists():
            parser.error(f"PDF not found: {path}")
        run_one(path)
    OUTPUT_DIR.mkdir(exist_ok=True)
    write_manifest()


if __name__ == "__main__":
    main()
