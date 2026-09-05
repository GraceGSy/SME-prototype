"""Extraction runs only for new raw sources and never overwrites prepared data."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from pipeline.extraction import extract_document


class NewDocumentTest(unittest.TestCase):
    def test_extracts_each_supported_source_once_with_explicit_domain(self):
        for extension, domain in (("xhtml", "narrative"), ("txt", "legal"), ("pdf", "academic")):
            with self.subTest(extension=extension), TemporaryDirectory() as directory:
                source, output = (
                    Path(directory) / f"source.{extension}",
                    Path(directory) / "content.json",
                )
                source.write_text("Source evidence.", encoding="utf8")
                client = Mock()
                client.run_json_file.return_value = SimpleNamespace(
                    value=[
                        {
                            "section_name": "S",
                            "section_number": None,
                            "subsections": [],
                            "paragraphs": [{"paragraph_number": 0, "text": "Source evidence."}],
                        }
                    ],
                    response_id="r1",
                    usage={"input_tokens": 10},
                )
                extract_document(source, output, domain=domain, title="Source", client=client)
                self.assertEqual(
                    json.loads(output.read_text())[0]["paragraphs"][0]["text"], "Source evidence."
                )
                args, kwargs = client.run_json_file.call_args
                self.assertIn("Source", args[1])
                self.assertIn(f"{domain} mode", kwargs["cacheable_prompt"])
                if extension == "pdf":
                    largest_fixture = max(
                        path.stat().st_size
                        for path in (
                            Path(__file__).resolve().parents[1] / "datasets/hci-five-paper/raw"
                        ).glob("*.pdf")
                    )
                    self.assertGreaterEqual(kwargs["policy"].max_attachment_bytes, largest_fixture)
                with self.assertRaises(FileExistsError):
                    extract_document(source, output, domain=domain, title="Source", client=client)
                self.assertEqual(client.run_json_file.call_count, 1)

    def test_rejects_domain_and_format_before_client_use(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            source.write_text("[]")
            for domain in ("academic", "fiction"):
                client = Mock()
                with self.assertRaises(ValueError):
                    extract_document(
                        source,
                        Path(directory) / "out.json",
                        domain=domain,
                        title="S",
                        client=client,
                    )
                client.register.assert_not_called()

    def test_rejects_malformed_extraction_without_publishing_content(self):
        with TemporaryDirectory() as directory:
            source, output = Path(directory) / "source.txt", Path(directory) / "content.json"
            source.write_text("Source evidence.")
            client = Mock()
            client.run_json_file.return_value = SimpleNamespace(value={"sections": []})
            with self.assertRaises(ValueError):
                extract_document(source, output, domain="legal", title="S", client=client)
            self.assertFalse(output.exists())
