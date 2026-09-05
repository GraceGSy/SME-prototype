"""Fresh source extraction must work without a prepared-content checkpoint."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from pipeline.skill_pipeline.runner import Harness, ROOT


class FreshExtractionTest(unittest.TestCase):
    def test_fresh_extraction_sends_explicit_domain_and_defined_prompt(self):
        for kind, domain in (("xhtml", "narrative"), ("text", "legal"), ("pdf", "academic")):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                harness = object.__new__(Harness)
                harness.prepared, harness.force = set(), False
                harness.config = {"datasets": {"test": {
                    "domain": domain, "documents": [{"id": "source", "title": "Source", kind: {}}],
                }}}
                harness._content_dir = Mock(return_value=Path(directory))
                harness._stage = Mock(return_value={"id": "extraction"})
                harness._source_path = Mock(return_value=ROOT / "source.txt")
                harness._skill, harness._call_policy = Mock(), Mock()
                harness._log, harness._log_error = Mock(), Mock()
                api = Mock()
                api.run_json_file.return_value = SimpleNamespace(value=[{
                    "section_name": "S", "section_number": None, "subsections": [],
                    "paragraphs": [{"paragraph_number": 0, "text": "Evidence."}],
                }])
                harness._api = Mock(return_value=api)
                from unittest.mock import patch
                with patch("pipeline.skill_pipeline.runner.validate_text_completion"), \
                     patch.object(Path, "read_text", return_value="Evidence."):
                    harness.prepare("test")
                args, kwargs = api.run_json_file.call_args
                self.assertIn("Source", args[1])
                self.assertIn(f"{domain} mode", kwargs["cacheable_prompt"])
