"""Serve real exported fixtures for browser regression tests; no model calls."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_viewer_dataset import make_snapshot_dataset, VIEWER_PATH
from pipeline.viewer.package import package_dataset, package_study

if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        root = Path(directory)
        make_snapshot_dataset(root / "source")
        package_dataset(root / "source", root / "single", VIEWER_PATH, "test", "Test Dataset")
        package_study({"sherlock": {"dataset_dir": root / "source", "participant_prefix": "SH", "label": "Sherlock"}},
                      root / "study", VIEWER_PATH)
        handler = partial(SimpleHTTPRequestHandler, directory=str(root))
        ThreadingHTTPServer(("127.0.0.1", 8765), handler).serve_forever()
