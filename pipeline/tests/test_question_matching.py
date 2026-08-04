from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

from group_groups import group_links
from question_matching import (
    directional_question_matches,
    eligible_merge_links,
    reciprocal_question_links,
)


class QuestionMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.groups = [
            {"group_id": "g1", "question": "How was the interface evaluated?"},
            {
                "group_id": "g2",
                "question": "How did researchers evaluate the interface?",
            },
            {"group_id": "g3", "question": "Why are code examples difficult to find?"},
        ]

    def test_merging_requires_reciprocal_claude_selection(self) -> None:
        entries = [
            {
                "group_id": "g1",
                "overarching_question": self.groups[0]["question"],
                "matches": [{"group_id": "g2", "reason": "Same evaluation role."}],
            },
            {
                "group_id": "g2",
                "overarching_question": self.groups[1]["question"],
                "matches": [{"group_id": "g1", "reason": "Same evaluation role."}],
            },
            {
                "group_id": "g3",
                "overarching_question": self.groups[2]["question"],
                "matches": [{"group_id": "g1", "reason": "Related domain."}],
            },
        ]
        links = reciprocal_question_links(entries)
        self.assertEqual(
            [(link["group_a"], link["group_b"]) for link in links], [("g1", "g2")]
        )
        self.assertTrue(links[0]["claude_reciprocal"])
        self.assertIn("lexical_similarity", links[0])

    def test_singletons_survive_component_merging(self) -> None:
        links = [{"group_a": "g1", "group_b": "g2", "similarity": 0.8}]
        components = group_links(self.groups, links)
        self.assertEqual(len(components), 2)
        merged = next(component for component in components if component["is_merged"])
        singleton = next(
            component for component in components if not component["is_merged"]
        )
        self.assertEqual(merged["parent_group_ids"], ["g1", "g2"])
        self.assertEqual(singleton["super_group_id"], "g3")
        self.assertEqual(singleton["parent_group_ids"], ["g3"])

    def test_merge_requires_both_claude_reciprocity_and_lexical_threshold(self) -> None:
        links = [
            {
                "group_a": "g1",
                "group_b": "g2",
                "claude_reciprocal": True,
                "lexical_similarity": 0.61,
            },
            {
                "group_a": "g1",
                "group_b": "g3",
                "claude_reciprocal": False,
                "lexical_similarity": 0.91,
            },
            {
                "group_a": "g2",
                "group_b": "g3",
                "claude_reciprocal": True,
                "lexical_similarity": 0.29,
            },
        ]
        eligible = eligible_merge_links(links, 0.33)
        self.assertEqual(
            [(link["group_a"], link["group_b"]) for link in eligible],
            [("g1", "g2")],
        )

    def test_claude_judgments_are_directional_and_lexical_scores_are_local(
        self,
    ) -> None:
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            block = SimpleNamespace(
                type="tool_use",
                name="record_directional_question_matches",
                input={
                    "sources": [
                        {
                            "group_id": "g1",
                            "matches": [{"group_id": "g2", "reason": "Same question."}],
                        },
                        {
                            "group_id": "g2",
                            "matches": [{"group_id": "g1", "reason": "Same question."}],
                        },
                        {"group_id": "g3", "matches": []},
                    ]
                },
            )
            usage = SimpleNamespace(
                cache_creation_input_tokens=0, cache_read_input_tokens=0
            )
            return SimpleNamespace(content=[block], usage=usage)

        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        with tempfile.TemporaryDirectory() as directory:
            entries = directional_question_matches(
                self.groups,
                Path(directory),
                label="test",
                top_k=2,
                client=client,
            )
        self.assertEqual(len(calls), 1)
        self.assertNotIn("similarity", str(calls[0]["messages"]))
        match = entries[0]["matches"][0]
        self.assertEqual(match["group_id"], "g2")
        self.assertGreater(match["similarity"], 0)

    def test_malformed_tool_shape_is_retried_without_caching(self) -> None:
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            sources = (
                ["g1", "g2", "g3"]
                if len(calls) == 1
                else [
                    {"group_id": "g1", "matches": []},
                    {"group_id": "g2", "matches": []},
                    {"group_id": "g3", "matches": []},
                ]
            )
            block = SimpleNamespace(
                type="tool_use",
                name="record_directional_question_matches",
                input={"sources": sources},
            )
            usage = SimpleNamespace(
                cache_creation_input_tokens=0, cache_read_input_tokens=0
            )
            return SimpleNamespace(content=[block], usage=usage)

        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        with tempfile.TemporaryDirectory() as directory:
            entries = directional_question_matches(
                self.groups,
                Path(directory),
                label="retry-test",
                top_k=2,
                client=client,
            )
            cache_files = list(Path(directory).glob("*.json"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(entries), 3)
        self.assertEqual(len(cache_files), 1)
        self.assertIn(
            "previous tool response was invalid", calls[1]["messages"][0]["content"]
        )


if __name__ == "__main__":
    unittest.main()
