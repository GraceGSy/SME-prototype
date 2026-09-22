"""Provider SDK details must not leak into extraction or graph construction."""

import ast
import unittest
from pathlib import Path


class ProviderBoundaryTest(unittest.TestCase):
    def test_application_modules_use_only_provider_contracts_and_factory(self):
        root = Path(__file__).resolve().parents[1] / "pipeline"
        files = [root / "extraction.py", *(root / "incremental_graph").glob("*.py")]
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    self.assertNotIn(
                        module,
                        {
                            "llm.client",
                            "providers.anthropic",
                            "providers.openai",
                            "anthropic",
                            "openai",
                        },
                        path,
                    )
                elif isinstance(node, ast.Import):
                    for name in node.names:
                        self.assertNotIn(name.name.split(".")[0], {"anthropic", "openai"}, path)
