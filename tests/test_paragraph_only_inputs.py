"""Whole-document preparation preserves evidence and removes section gating."""

import copy
import tempfile
import unittest
from pathlib import Path

from test_incremental_graph import CONFIG_PATH, ScriptedJudge

from helpers.prepare_content_corpus import flatten_to_single_section, prepare_content_corpus
from pipeline.files import read_json, write_json
from pipeline.incremental_graph.configuration import load_pipeline_config
from pipeline.incremental_graph.input_data import load_manifest
from pipeline.incremental_graph.runner import IncrementalGraphRunner


def document():
    return [
        {
            "section_name": "Background",
            "section_number": "I",
            "paragraphs": [
                {"paragraph_number": 0, "text": "  First background paragraph.\n"},
            ],
            "subsections": [
                {
                    "section_name": "Detail",
                    "section_number": "A",
                    "paragraphs": [
                        {"paragraph_number": 0, "text": "Subsection evidence."},
                    ],
                },
            ],
        },
        {
            "section_name": "Analysis",
            "section_number": "II",
            "paragraphs": [
                {"paragraph_number": 0, "text": "First analysis paragraph."},
            ],
            "subsections": [],
        },
    ]


class ParagraphOnlyInputsTest(unittest.TestCase):
    def test_flattening_preserves_text_order_without_mutating_source(self):
        source = document()
        original = copy.deepcopy(source)
        flat = flatten_to_single_section(source, "Whole opinion")
        self.assertEqual(source, original)
        self.assertEqual(len(flat), 1)
        self.assertEqual(flat[0]["subsections"], [])
        self.assertEqual(
            flat[0]["paragraphs"],
            [
                {"paragraph_number": 0, "text": "  First background paragraph.\n"},
                {"paragraph_number": 1, "text": "Subsection evidence."},
                {"paragraph_number": 2, "text": "First analysis paragraph."},
            ],
        )

    def test_prepared_pair_compares_every_paragraph_without_structural_judgments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = document()
            manifest = {
                "schema_version": 1,
                "max_granularity": "section",
                "papers": [
                    {"paper_id": name, "title": name, "file": f"{name}.json"}
                    for name in ("first", "second")
                ],
            }
            for entry in manifest["papers"]:
                write_json(root / entry["file"], source)
            write_json(root / "manifest.json", manifest)
            self.assertEqual(
                prepare_content_corpus(root / "manifest.json", root / "flat", whole_section=True), 2
            )
            prepared, papers = load_manifest(root / "flat/manifest.yaml")
            self.assertEqual(prepared.max_granularity, "paragraph")
            self.assertTrue(all(len(p.sections) == 1 for p in papers))
            self.assertEqual(read_json(root / "first.json"), source)
            judge = ScriptedJudge({})
            runner = IncrementalGraphRunner(
                load_pipeline_config(CONFIG_PATH),
                judge,
                root / "revision",
                max_granularity="paragraph",
            )
            runner.run(papers)
            self.assertFalse(any(r.stage_id.startswith("section_") for r in judge.requests))
            matches = [r for r in judge.requests if r.stage_id == "paragraph_matching"]
            self.assertEqual(len(matches), 6)
            self.assertTrue(all(len(r.allowed_match_ids) == 3 for r in matches))
            self.assertTrue(
                (root / "revision/stages/0002-paragraph_rerepresentation.json").is_file()
            )
            crossing = next(
                r for r in matches if r.key == "second:paragraph_matching:new_to_group:s0001.p0002"
            )
            self.assertEqual(
                crossing.context["focus"]["previous_paragraph"]["full_text"],
                source[0]["paragraphs"][0]["text"],
            )
            self.assertEqual(
                crossing.context["focus"]["next_paragraph"]["full_text"],
                source[1]["paragraphs"][0]["text"],
            )

    def test_malformed_source_is_rejected_not_repaired(self):
        source = document()
        source[0]["unexpected"] = "not canonical"
        with self.assertRaises(ValueError):
            flatten_to_single_section(source, "Whole opinion")
