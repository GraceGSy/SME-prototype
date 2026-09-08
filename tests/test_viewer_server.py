import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from test_viewer_dataset import make_snapshot_dataset, write_json

from pipeline.viewer.server import RunCatalog, handler_for


class ViewerServerTest(unittest.TestCase):
    def test_http_serves_validated_export_but_not_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            revision = root / "example/revisions/revision-0001"
            make_snapshot_dataset(revision / "dataset")
            write_json(revision / "summary.json", {"paper_count": 2})
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(RunCatalog(root)))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/runs/example/revision-0001/dataset.json") as response:
                    self.assertEqual(json.load(response)["paper_count"], 2)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                for path in (
                    "/runs/example/revision-0001/run.json",
                    "/.env",
                    "/runs/example/revision-0002/dataset.json",
                ):
                    with self.assertRaises(HTTPError):
                        urlopen(base + path)
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_latest_ignores_unfinished_revision_and_pins_completed_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "example"
            revision = run / "revisions/revision-0001"
            make_snapshot_dataset(revision / "dataset")
            write_json(revision / "summary.json", {"paper_count": 2})
            write_json(run / "run.json", {"current_revision": "revision-0001"})
            write_json(run / "revisions/revision-0002/failure.json", {"message": "failed"})
            catalog = RunCatalog(root)
            self.assertEqual(catalog.entries()[0]["revisions"], ["revision-0001"])
            path = catalog.dataset("example", "revision-0001")
            self.assertEqual(path, revision / "dataset")
            with self.assertRaises(ValueError):
                catalog.dataset("example", "revision-0002")
            with self.assertRaises(ValueError):
                catalog.dataset("..", "revision-0001")

    def test_unpublished_summary_not_exposed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "example/run.json", {"current_revision": None})
            write_json(root / "example/revisions/revision-0001/summary.json", {})
            self.assertEqual(RunCatalog(root).entries(), [])
