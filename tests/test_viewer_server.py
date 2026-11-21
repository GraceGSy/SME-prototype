import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from test_viewer_dataset import make_snapshot_dataset, write_json

from pipeline.viewer.package_catalog import package_catalog
from pipeline.viewer.server import RunCatalog, handler_for


class ViewerServerTest(unittest.TestCase):
    def test_public_reuters_text_is_limited_to_approved_revisions(self):
        run = "reuters-technology-jev-singletons-20261105"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runs"
            for rev in ("revision-0001", "revision-0002"):
                revision = root / run / "revisions" / rev
                make_snapshot_dataset(revision / "dataset")
                write_json(revision / "summary.json", {"paper_count": 2})
            site = Path(directory) / "site"
            [entry] = package_catalog(root, site)
            self.assertEqual(entry["sourceTextRevisions"], ["revision-0001"])
            published = site / "public/runs" / run
            original = root / run / "revisions/revision-0001/dataset/paper_a.json"
            self.assertEqual(
                json.loads((published / "revision-0001/paper_a.json").read_text(encoding="utf-8")),
                json.loads(original.read_text(encoding="utf-8")),
            )
            self.assertNotIn(
                "Shared A", (published / "revision-0002/paper_a.json").read_text(encoding="utf-8")
            )

    def test_public_catalog_publishes_only_chosen_completed_snapshots_without_prose(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runs"
            summary = {"paper_count": 2}
            for name, rev in (("example", 1), ("example", 2), ("example", 3), ("private", 1)):
                revision = root / name / "revisions" / f"revision-{rev:04d}"
                make_snapshot_dataset(revision / "dataset")
                write_json(revision / "summary.json", summary)
            write_json(root / "example/revisions/revision-0002/failure.json", {})
            site = Path(directory) / "site"
            # HCI keeps its source text; any other collection is redacted.
            catalog = package_catalog(root, site, {"example": "Synthetic | Test run"})
            self.assertEqual([e["id"] for e in catalog], ["example"])
            self.assertEqual(catalog[0]["revisions"], ["revision-0001", "revision-0003"])
            self.assertIn("2 documents", catalog[0]["revisionLabels"]["revision-0003"])
            self.assertFalse((site / "public/runs/private").exists())
            for rev in catalog[0]["revisions"]:
                dest = site / "public/runs/example" / rev
                src = root / "example/revisions" / rev / "dataset"
                self.assertEqual(
                    json.loads((dest / "final_snapshot.json").read_text(encoding="utf-8")),
                    json.loads((src / "final_snapshot.json").read_text(encoding="utf-8")),
                )
                paper = json.loads((dest / "paper_a.json").read_text(encoding="utf-8"))
                self.assertTrue(
                    all(
                        u["text"] == "Source text is not included in this results viewer."
                        for u in paper["sections"] + paper["paragraphs"]
                    )
                )
                self.assertNotIn("Shared A", (dest / "paper_a.json").read_text(encoding="utf-8"))

    def test_http_serves_validated_export_but_not_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            revision = root / "example/revisions/revision-0001"
            make_snapshot_dataset(revision / "dataset")
            write_json(revision / "summary.json", {"paper_count": 2})
            write_json(root / "example/viewer.json", {"label": "Readable study name"})
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(RunCatalog(root)))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/runs/example/revision-0001/dataset.json") as response:
                    descriptor = json.load(response)
                    self.assertEqual(descriptor["paper_count"], 2)
                    self.assertEqual(descriptor["label"], "Readable study name")
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                with urlopen(base + "/local.json") as response:
                    self.assertEqual(json.load(response)[0]["label"], "Readable study name")
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
            # Windows CI gives temp folders short names (RUNNER~1); the code resolves paths.
            root = Path(directory).resolve()
            run = root / "example"
            revision = run / "revisions/revision-0001"
            make_snapshot_dataset(revision / "dataset")
            write_json(revision / "summary.json", {"paper_count": 2})
            write_json(run / "run.json", {"current_revision": "revision-0001"})
            write_json(run / "revisions/revision-0002/failure.json", {"message": "failed"})
            catalog = RunCatalog(root)
            self.assertEqual(catalog.entries()[0]["revisions"], ["revision-0001"])
            self.assertEqual(catalog.entries()[0]["label"], "example")
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
