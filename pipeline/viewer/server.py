"""Read-only localhost viewer for completed run revisions; no packaging or API calls."""

import argparse
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from ..incremental_graph.export import _viewer_group, _viewer_paper
from ..incremental_graph.input_data import load_manifest
from .package import VIEWER_ASSETS, DatasetValidationError, validate_dataset

VIEWER = Path(__file__).parent


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class RunCatalog:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)

    def label(self, run: str) -> str:
        metadata = self.root / run / "viewer.json"
        if not metadata.exists():
            return run
        if not metadata.resolve().is_relative_to(self.root):
            raise ValueError("Viewer metadata must stay inside the runs directory")
        value = read_json(metadata)
        if (
            not isinstance(value, dict)
            or set(value) != {"label"}
            or not isinstance(value["label"], str)
            or not value["label"]
            or value["label"] != value["label"].strip()
        ):
            raise ValueError("viewer.json requires exactly one nonempty, unpadded label")
        return value["label"]

    def entries(self, *, include_checkpoints=False):
        entries = []
        for run in self.root.iterdir():
            if not run.is_dir() or not re.fullmatch(r"[A-Za-z0-9_-]+", run.name):
                continue
            if not run.resolve().is_relative_to(self.root):
                continue
            state = read_json(run / "run.json") if (run / "run.json").is_file() else None
            current = state.get("current_revision") if state is not None else None
            revisions = []
            checkpoints = []
            modified = 0
            for revision in (run / "revisions").glob("revision-*"):
                if not re.fullmatch(r"revision-[0-9]{4,}", revision.name):
                    continue
                if (
                    not revision.resolve().is_relative_to(run.resolve())
                    or (revision / "failure.json").exists()
                ):
                    continue
                summary = revision / "summary.json"
                if include_checkpoints and (revision / "section-checkpoint.json").is_file():
                    checkpoints.append(revision.name)
                    summary = revision / "section-checkpoint.json"
                elif (
                    not summary.is_file()
                    or not (revision / "dataset").is_dir()
                    or (
                        state is not None
                        and (
                            not current
                            or int(revision.name.split("-")[1]) > int(current.split("-")[1])
                        )
                    )
                ):
                    continue
                revisions.append(revision.name)
                modified = max(modified, summary.stat().st_mtime_ns)
            if revisions:
                revisions.sort(key=lambda name: int(name.split("-")[1]))
                entry = {
                    "id": run.name,
                    "label": self.label(run.name),
                    "revisions": revisions,
                    "modified": modified,
                }
                if checkpoints:
                    entry["sectionRevisions"] = sorted(checkpoints)
                entries.append(entry)
        entries.sort(key=lambda entry: entry["modified"], reverse=True)
        for entry in entries:
            del entry["modified"]
        return entries

    def section_map(self, run, revision):
        if not any(
            e["id"] == run and revision in e.get("sectionRevisions", [])
            for e in self.entries(include_checkpoints=True)
        ):
            raise ValueError("No saved section checkpoint for this revision")
        root = self.root / run
        checkpoint = read_json(root / "revisions" / revision / "section-checkpoint.json")
        _, papers = load_manifest(root / "inputs" / revision / "manifest.yaml")
        if checkpoint["completed_phase"] != "structural" or checkpoint["paper_order"] != [
            p.paper_id for p in papers
        ]:
            raise ValueError("Section checkpoint disagrees with frozen inputs")
        sections = {(p.paper_id, s.id): s for p in papers for s in p.sections}
        return {
            "papers": [_viewer_paper(p, include_paragraphs=False) for p in papers],
            "groups": [
                _viewer_group(gid, node, sections, {})
                for gid, node in checkpoint["section_groups"].items()
            ],
        }

    def dataset(self, run, revision):
        if not any(e["id"] == run and revision in e["revisions"] for e in self.entries()):
            raise ValueError("Unknown or unfinished run revision")
        path = (self.root / run / "revisions" / revision / "dataset").resolve(strict=True)
        if not path.is_relative_to(self.root):
            raise ValueError("Dataset must stay inside the runs directory")
        return path


def handler_for(catalog):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                path = urlsplit(self.path).path
                if path == "/trace" or path.startswith("/trace/"):
                    return self.serve_trace(path)
                if path == "/local.json":
                    return self.send_json(catalog.entries(include_checkpoints=True))
                assets = {"/": VIEWER / "index.html", "/index.html": VIEWER / "index.html"}
                assets.update(
                    {"/" + target: VIEWER / source for source, target in VIEWER_ASSETS.items()}
                )
                if path in assets:
                    return self.send_file(assets[path])
                match = re.fullmatch(
                    r"/runs/([A-Za-z0-9_-]+)/(revision-[0-9]{4,})/([A-Za-z0-9_.-]+\.json)", path
                )
                if not match:
                    return self.send_error(404)
                run, revision, filename = match.groups()
                if filename == "section-map.json":
                    return self.send_json(catalog.section_map(run, revision))
                dataset = catalog.dataset(run, revision)
                if filename == "dataset.json":
                    return self.send_json(validate_dataset(dataset, run, catalog.label(run)))
                allowed = {"manifest.json", "final_snapshot.json"}
                allowed.update(entry["file"] for entry in read_json(dataset / "manifest.json"))
                file = (dataset / filename).resolve()
                if filename not in allowed or not file.is_relative_to(dataset):
                    return self.send_error(404)
                self.send_file(file)
            except (ValueError, OSError, DatasetValidationError) as error:
                self.send_error(400, str(error))

        def serve_trace(self, path):
            from . import trace

            if self.headers.get("Host", "").split(":")[0] not in {"localhost", "127.0.0.1"}:
                return self.send_error(403)
            if path in {"/trace", "/trace/"}:
                return self.send_file(VIEWER / "trace.html")
            if path == "/trace/runs":
                return self.send_json(trace.revisions(catalog.root))
            match = re.fullmatch(
                r"/trace/([A-Za-z0-9_-]+)/(revision-[0-9]{4,})"
                r"(?:/((?:attempt|event)-[0-9]+|receipt-[a-f0-9]{20}))?",
                path,
            )
            if not match:
                return self.send_error(404)
            run, rev, key = match.groups()
            try:
                data = trace.load(catalog.root, run, rev)
                if not key:
                    return self.send_json(data.index())
                detail = {"attempt": data.decision, "event": data.event, "receipt": data.receipt}
                return self.send_json(detail[key.split("-")[0]](key))
            except KeyError:
                return self.send_error(404, "Unknown trace record")

        def send_json(self, value):
            self.send_bytes(json.dumps(value).encode("utf-8"), "application/json")

        def send_file(self, path):
            self.send_bytes(
                path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            )

        def send_bytes(self, content, mime):
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="?", default=Path("runs"))
    parser.add_argument("--port", type=int, default=8073)
    args = parser.parse_args()
    if not (VIEWER / "dist/app.js").is_file():
        parser.error("Build the viewer once first: npm run build:viewer")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(RunCatalog(args.runs)))
    print(f"Viewer: http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
