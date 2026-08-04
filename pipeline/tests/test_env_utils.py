from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

from env_utils import load_dotenv_upwards


class DotenvTests(unittest.TestCase):
    def test_loads_multiple_ancestor_files_without_overwriting_nearer_values(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "child" / "repo"
            child.mkdir(parents=True)
            (root / ".env").write_text(
                "ANTHROPIC_API_KEY=parent-key\nSHARED=parent\n", encoding="utf-8"
            )
            (root / "child" / ".env").write_text(
                "API_TOKEN=child-token\nSHARED=child\n", encoding="utf-8"
            )
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_dotenv_upwards(child)
                self.assertEqual(os.environ["ANTHROPIC_API_KEY"], "parent-key")
                self.assertEqual(os.environ["API_TOKEN"], "child-token")
                self.assertEqual(os.environ["SHARED"], "child")
                self.assertEqual(loaded, [root / "child" / ".env", root / ".env"])


if __name__ == "__main__":
    unittest.main()
