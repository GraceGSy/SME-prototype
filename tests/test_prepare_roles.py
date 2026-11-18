import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pipeline.document import ROLE_FIELD, strip_annotations
from pipeline.files import read_json, write_json
from pipeline.prepare_roles import prepare


class WholePaperRolesTest(unittest.TestCase):
    def test_source_only_prefix_one_focus_per_call_and_offline_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = [
                {
                    "section_name": "Methods",
                    "section_number": "1",
                    "paragraphs": [],
                    "question_this_text_answers": "LEGACY QUESTION?",
                    "subsections": [
                        {
                            "section_name": "Recruitment",
                            "section_number": "1.1",
                            "paragraphs": [
                                {
                                    "paragraph_number": 0,
                                    "text": "We recruited volunteers.",
                                    ROLE_FIELD: "PREVIOUS STATEMENT.",
                                }
                            ],
                        }
                    ],
                }
            ]
            write_json(root / "clean.json", src)
            manifest = root / "input.yaml"
            write_json(
                manifest,
                {
                    "schema_version": 1,
                    "max_granularity": "section",
                    "papers": [{"paper_id": "test", "title": "Test", "file": "clean.json"}],
                },
            )
            sdk = Mock()
            calls = []

            def respond(**params):
                blocks = params["messages"][0]["content"]
                calls.append(blocks)
                return Mock(
                    model_dump=lambda **_: {
                        "stop_reason": "end_turn",
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {ROLE_FIELD: "Describes participant selection."}
                                ),
                            }
                        ],
                        "usage": {
                            "cache_creation_input_tokens": 1000 if len(calls) == 1 else 0,
                            "cache_read_input_tokens": 0 if len(calls) == 1 else 1000,
                        },
                    }
                )

            sdk.messages.create.side_effect = respond
            out = root / "prepared"
            with (
                patch("pipeline.prepare_roles.Anthropic", return_value=sdk),
                patch("pipeline.prepare_roles.load_api_key", return_value="offline"),
            ):
                prepare(manifest, out)
            self.assertEqual(len(calls), 2)
            self.assertEqual(
                [b[1]["text"].splitlines()[0] for b in calls],
                ["Focus: section: 1 Methods", "Focus: paragraph 1 of 1 Methods / 1.1 Recruitment"],
            )
            # The paper prefix names each unit by its printed heading, once.
            prefix = calls[0][0]["text"]
            self.assertEqual(prefix.count("[section: 1 Methods]"), 1)
            self.assertIn("[paragraph 1 of 1 Methods / 1.1 Recruitment] We recruited", prefix)
            self.assertTrue(
                all(
                    b[0] == calls[0][0] and b[0]["cache_control"] == {"type": "ephemeral"}
                    for b in calls
                )
            )
            self.assertEqual(calls[0][0]["text"].count("We recruited volunteers."), 1)
            self.assertNotIn("LEGACY QUESTION", str(calls))
            self.assertNotIn("PREVIOUS STATEMENT", str(calls))
            self.assertNotIn("Describes participant selection.", str(calls))
            self.assertEqual(
                strip_annotations(read_json(out / "test.json")), strip_annotations(src)
            )
            with patch(
                "pipeline.prepare_roles.Anthropic",
                side_effect=AssertionError("Contacted Claude on replay"),
            ):
                prepare(manifest, out)
            self.assertEqual(
                len((out / "responses.jsonl").read_text(encoding="utf-8").splitlines()), 5
            )
            self.assertEqual(read_json(root / "clean.json"), src)
            # A new paper can reuse the earlier preparation's exact request wording.
            log = out / "responses.jsonl"
            saved = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
            saved["prompts"]["section"] = "EARLIER SECTION WORDING."
            log.write_text(
                "\n".join([json.dumps(saved), *log.read_text(encoding="utf-8").splitlines()[1:]]),
                encoding="utf-8",
            )
            calls.clear()
            with (
                patch("pipeline.prepare_roles.Anthropic", return_value=sdk),
                patch("pipeline.prepare_roles.load_api_key", return_value="offline"),
            ):
                prepare(manifest, root / "again", policy_from=log)
            self.assertEqual(
                calls[0][1]["text"], "Focus: section: 1 Methods\nEARLIER SECTION WORDING."
            )
