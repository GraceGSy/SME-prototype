"""Run stage-1 extraction over the example papers in SME/ and save each
resulting graph as JSON in SME/pipeline/output/.

Usage:
    python3 cli.py                     # run on the default example papers
    python3 cli.py my_paper.pdf ...    # run on specific PDF paths
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from extract_graph import extract_graph
from pdf_text import extract_pdf_text

SME_DIR = Path(__file__).resolve().parent.parent
PAPERS_DIR = SME_DIR / "papers"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

DEFAULT_PAPERS = [
    PAPERS_DIR / "examplore_chi18.pdf",
    PAPERS_DIR / "mesotext.pdf",
    PAPERS_DIR / "paralib_uist22.pdf",
]


def run_one(pdf_path: Path) -> None:
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
    paths = [Path(p) for p in sys.argv[1:]] or DEFAULT_PAPERS
    for path in paths:
        if not path.exists():
            print(f"skipping {path}: not found", file=sys.stderr)
            continue
        run_one(path)
    OUTPUT_DIR.mkdir(exist_ok=True)
    write_manifest()


if __name__ == "__main__":
    main()
