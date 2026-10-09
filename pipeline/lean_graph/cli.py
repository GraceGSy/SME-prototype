"""CLI entrypoint.

    python -m pipeline.lean_graph.cli run <manifest.yaml> <graph_dir>

Always processes the full paper list in the manifest, in order, from an empty graph --
see runner.py's docstring for why that's the right model here, not a limitation.
Writes <graph_dir>/graph.json and prints a short summary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .input_data import load_paper
from .judge import Judge
from .runner import run


def load_manifest(path: Path) -> list[tuple[str, str, Path]]:
    path = Path(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = []
    for item in payload["papers"]:
        entries.append((item["paper_id"], item["title"], (path.parent / item["file"]).resolve()))
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("graph_dir", type=Path)
    parser.add_argument("--model", default="claude-sonnet-5")
    args = parser.parse_args()

    entries = load_manifest(args.manifest)
    papers = [load_paper(path, paper_id, title) for paper_id, title, path in entries]

    judge = Judge(cache_path=args.graph_dir / "cache" / "judgments.json", model=args.model)
    graph = run(papers, judge)

    args.graph_dir.mkdir(parents=True, exist_ok=True)
    (args.graph_dir / "graph.json").write_text(json.dumps(graph.to_json(), indent=2), encoding="utf-8")

    print(json.dumps({
        "paper_count": len(papers),
        "paper_order": graph.paper_order,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "graph_file": str((args.graph_dir / "graph.json").resolve()),
    }, indent=2))


if __name__ == "__main__":
    main()
