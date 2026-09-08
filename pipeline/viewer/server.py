"""Read-only localhost viewer for completed run revisions; no packaging or API calls."""

import argparse
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .package import VIEWER_ASSETS, DatasetValidationError, validate_dataset

VIEWER = Path(__file__).parent


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class RunCatalog:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)

    def entries(self):
        entries = []
        for run in self.root.iterdir():
            if not run.is_dir() or not re.fullmatch(r"[A-Za-z0-9_-]+", run.name):
                continue
            if not run.resolve().is_relative_to(self.root):
                continue
            state = read_json(run / "run.json") if (run / "run.json").is_file() else None
            current = state.get("current_revision") if state is not None else None
            if state is not None and current is None:
                continue
            revisions = []
            modified = 0
            for summary in sorted((run / "revisions").glob("revision-*/summary.json")):
                revision = summary.parent
                if not re.fullmatch(r"revision-[0-9]{4,}", revision.name):
                    continue
                if current and int(revision.name.split("-")[1]) > int(current.split("-")[1]):
                    continue
                if (revision / "failure.json").exists() or not (revision / "dataset").is_dir():
                    continue
                if not revision.resolve().is_relative_to(self.root):
                    continue
                revisions.append(revision.name)
                modified = max(modified, summary.stat().st_mtime_ns)
            if revisions:
                revisions.sort(key=lambda name: int(name.split("-")[1]))
                entries.append({"id": run.name, "revisions": revisions, "modified": modified})
        entries.sort(key=lambda entry: entry["modified"], reverse=True)
        return [{"id": entry["id"], "revisions": entry["revisions"]} for entry in entries]

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
                if path == "/local.json":
                    return self.send_json(catalog.entries())
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
                dataset = catalog.dataset(run, revision)
                if filename == "dataset.json":
                    return self.send_json(validate_dataset(dataset, run, f"{run} / {revision}"))
                allowed = {"manifest.json", "final_snapshot.json", "graph-replay.json"}
                allowed.update(entry["file"] for entry in read_json(dataset / "manifest.json"))
                file = (dataset / filename).resolve()
                if filename not in allowed or not file.is_relative_to(dataset):
                    return self.send_error(404)
                self.send_file(file)
            except (ValueError, OSError, DatasetValidationError) as error:
                self.send_error(400, str(error))

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
