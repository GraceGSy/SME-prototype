from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

from question_synthesis import synthesize_question


class FakeMessages:
    def __init__(self) -> None:
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        block = SimpleNamespace(
            type="tool_use",
            name="record_overarching_question",
            input={
                "overarching_question": "How do examples support design exploration?"
            },
        )
        usage = SimpleNamespace(
            cache_creation_input_tokens=0, cache_read_input_tokens=0
        )
        return SimpleNamespace(content=[block], usage=usage)


class QuestionSynthesisTests(unittest.TestCase):
    def test_complete_paragraph_text_and_provenance_reach_claude(self) -> None:
        messages = FakeMessages()
        client = SimpleNamespace(messages=messages)
        full_text = "This complete paragraph contains a distinctive final sentence."
        paragraphs = [
            {
                "paper": "paper-a",
                "unit_id": "pa7",
                "parent_section_id": "s2",
                "section_title": "2 Design",
                "tag": "What was designed?",
                "text": full_text,
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = synthesize_question(
                "g1", paragraphs, Path(directory), client=client
            )
        prompt = messages.requests[0]["messages"][0]["content"]
        self.assertIn(full_text, prompt)
        self.assertIn("paper=paper-a", prompt)
        self.assertIn("paragraph=pa7", prompt)
        self.assertEqual(result["input_characters"], len(full_text))
        self.assertTrue(result["overarching_question"].endswith("?"))


if __name__ == "__main__":
    unittest.main()
