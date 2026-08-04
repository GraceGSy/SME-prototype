from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

from refine_epochs import (
    ASSIGNMENT_SYSTEM_PROMPT,
    EVIDENCE_ASSIGNMENT_SYSTEM_PROMPT,
    REPRESENTATIVE_ASSIGNMENT_SYSTEM_PROMPT,
    TfidfScorer,
    _assignment_tool,
    apply_assignments,
    assign_batch,
    assigned_keys,
    build_changes,
    format_assignment_groups,
    merge_groups,
    paragraph_batches,
    score_assignments,
)
from section_schema import Section


def paragraph(paper: str, unit_id: str, section: str, text: str, tag: str) -> dict:
    return {
        "paper": paper,
        "unit_id": unit_id,
        "parent_section_id": section,
        "section_title": section,
        "text": text,
        "tag": tag,
    }


class EpochRefinementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.paragraphs = [
            paragraph(
                "a",
                "p1",
                "s1",
                "Participants searched examples to understand a design space.",
                "What problem do examples solve?",
            ),
            paragraph(
                "a",
                "p2",
                "s1",
                "The interface presents comparable examples side by side.",
                "How does the interface support comparison?",
            ),
            paragraph(
                "b",
                "p1",
                "s9",
                "A study measured whether comparison improved authoring.",
                "How was comparison evaluated?",
            ),
        ]
        self.groups = [
            {
                "group_id": "g1",
                "question": "How do examples support comparison?",
                "members": [],
            },
            {
                "group_id": "g2",
                "question": "How was the system evaluated?",
                "members": [],
            },
        ]

    def test_tfidf_similarity_is_deterministic(self) -> None:
        scorer = TfidfScorer(self.paragraphs)
        first = scorer.score(self.groups[0]["question"], self.paragraphs[0])
        second = scorer.score(self.groups[0]["question"], self.paragraphs[0])
        self.assertEqual(first, second)
        self.assertGreater(first, 0)

    def test_assignment_prompt_only_reconsiders_orphans(self) -> None:
        self.assertIn("currently UNASSIGNED", ASSIGNMENT_SYSTEM_PROMPT)
        self.assertIn("Existing group memberships", ASSIGNMENT_SYSTEM_PROMPT)
        self.assertIn("reconsidered", ASSIGNMENT_SYSTEM_PROMPT)
        self.assertIn("Do not force-fit", ASSIGNMENT_SYSTEM_PROMPT)
        self.assertIn("empty group_ids list", ASSIGNMENT_SYSTEM_PROMPT)

    def test_claude_can_leave_a_complete_orphan_unassigned(self) -> None:
        requests = []

        def create(**kwargs):
            requests.append(kwargs)
            block = SimpleNamespace(
                type="tool_use",
                name="record_paragraph_assignments",
                input={
                    "assignments": [
                        {
                            "paragraph_id": "a:p1",
                            "group_ids": [],
                            "reason": "Neither question is a substantive match.",
                        }
                    ]
                },
            )
            usage = SimpleNamespace(
                cache_creation_input_tokens=0, cache_read_input_tokens=0
            )
            return SimpleNamespace(content=[block], usage=usage)

        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("refine_epochs.ASSIGNMENT_CACHE_DIR", Path(directory)),
        ):
            assignments = assign_batch(
                1, 1, self.groups, [self.paragraphs[0]], client=client
            )
        self.assertEqual(assignments[0]["group_ids"], [])
        prompt = requests[0]["messages"][0]["content"]
        self.assertIn("Currently unassigned", prompt)
        self.assertIn(self.paragraphs[0]["text"], prompt)

    def test_assignment_tool_enumerates_exact_paragraph_references(self) -> None:
        tool = _assignment_tool(["paper-a:p7", "paper-b:p2"], ["g1"])
        item = tool["input_schema"]["properties"]["assignments"]["items"]
        self.assertEqual(
            item["properties"]["paragraph_id"]["enum"],
            ["paper-a:p7", "paper-b:p2"],
        )
        self.assertNotIn("paper", item["properties"])
        self.assertNotIn("unit_id", item["properties"])

    def test_duplicate_assignment_records_are_consolidated(self) -> None:
        def create(**kwargs):
            block = SimpleNamespace(
                type="tool_use",
                name="record_paragraph_assignments",
                input={
                    "assignments": [
                        {
                            "paragraph_id": "a:p1",
                            "group_ids": ["g1"],
                            "reason": "Matches the example comparison question.",
                        },
                        {
                            "paragraph_id": "a:p1",
                            "group_ids": ["g2", "g1"],
                            "reason": "Also reports the evaluation.",
                        },
                    ]
                },
            )
            usage = SimpleNamespace(
                cache_creation_input_tokens=0, cache_read_input_tokens=0
            )
            return SimpleNamespace(content=[block], usage=usage)

        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("refine_epochs.ASSIGNMENT_CACHE_DIR", Path(directory)),
        ):
            assignments = assign_batch(
                1, 1, self.groups, [self.paragraphs[0]], client=client
            )

        self.assertEqual(assignments[0]["group_ids"], ["g1", "g2"])
        self.assertEqual(assignments[0]["source_record_count"], 2)
        self.assertIn(" | ", assignments[0]["reason"])

    def test_evidence_assignment_supplies_every_current_group_paragraph(self) -> None:
        requests = []
        groups = [
            {
                "group_id": "g1",
                "question": "How do examples support comparison?",
                "members": [
                    {"paper": "a", "unit_id": "p1"},
                    {"paper": "a", "unit_id": "p2"},
                ],
            }
        ]

        def create(**kwargs):
            requests.append(kwargs)
            block = SimpleNamespace(
                type="tool_use",
                name="record_paragraph_assignments",
                input={
                    "assignments": [
                        {
                            "paragraph_id": "b:p1",
                            "group_ids": [],
                            "reason": "No substantive match.",
                        }
                    ]
                },
            )
            usage = SimpleNamespace(
                cache_creation_input_tokens=0, cache_read_input_tokens=0
            )
            return SimpleNamespace(content=[block], usage=usage)

        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("refine_epochs.ASSIGNMENT_CACHE_DIR", Path(directory)),
        ):
            assign_batch(
                1,
                1,
                groups,
                [self.paragraphs[2]],
                assignment_context="all_group_paragraphs",
                corpus_paragraphs=self.paragraphs,
                client=client,
            )
        prompt = requests[0]["messages"][0]["content"]
        self.assertEqual(
            requests[0]["system"][0]["text"], EVIDENCE_ASSIGNMENT_SYSTEM_PROMPT
        )
        self.assertIn(self.paragraphs[0]["text"], prompt)
        self.assertIn(self.paragraphs[1]["text"], prompt)
        self.assertIn(self.paragraphs[2]["text"], prompt)
        self.assertIn("All current assigned paragraphs (2 memberships)", prompt)

    def test_representative_evidence_uses_deterministic_per_paper_medoids(self) -> None:
        corpus = [
            *self.paragraphs,
            paragraph(
                "a",
                "p3",
                "s2",
                "Examples reveal recurring design alternatives and tradeoffs.",
                "What alternatives do examples reveal?",
            ),
            paragraph(
                "a",
                "p4",
                "s2",
                "The system organizes examples for direct comparison.",
                "How are examples organized?",
            ),
        ]
        group = {
            "group_id": "g1",
            "question": "How do examples support comparison?",
            "members": [
                {"paper": item["paper"], "unit_id": item["unit_id"]}
                for item in corpus
            ],
        }
        scorer = TfidfScorer(corpus)
        first_text, first = format_assignment_groups(
            [group],
            "representative_group_paragraphs",
            corpus,
            scorer,
            representative_per_paper=1,
            representative_max_per_group=2,
        )
        second_text, second = format_assignment_groups(
            [group],
            "representative_group_paragraphs",
            corpus,
            scorer,
            representative_per_paper=1,
            representative_max_per_group=2,
        )
        self.assertEqual(first_text, second_text)
        self.assertEqual(first, second)
        selected = first["group_evidence"][0]["paragraph_ids"]
        self.assertEqual(len(selected), 2)
        self.assertEqual({item.split(":", 1)[0] for item in selected}, {"a", "b"})
        self.assertEqual(first["evidence_membership_count"], 2)
        self.assertEqual(
            first["selection_method"],
            "corpus-tfidf-greedy-k-medoids-per-paper-v1",
        )
        self.assertIn("Deterministic TF-IDF medoid paragraphs", first_text)
        self.assertIn("deterministic set", REPRESENTATIVE_ASSIGNMENT_SYSTEM_PROMPT)

    def test_unit_tags_must_be_complete_questions(self) -> None:
        with self.assertRaises(ValueError):
            Section(id="p1", tag="Evaluation method")
        self.assertEqual(
            Section(id="p1", tag="How was it evaluated?").tag,
            "How was it evaluated?",
        )

    def test_batches_preserve_every_complete_paragraph(self) -> None:
        batches = paragraph_batches(self.paragraphs, max_chars=55)
        flattened = [item for batch in batches for item in batch]
        self.assertEqual(flattened, self.paragraphs)
        self.assertEqual(flattened[0]["text"], self.paragraphs[0]["text"])

    def test_same_section_support_includes_existing_members(self) -> None:
        groups = [
            {
                **self.groups[0],
                "members": [{"paper": "a", "unit_id": "p2"}],
            },
            self.groups[1],
        ]
        assignments = [
            {
                "paper": "a",
                "unit_id": "p1",
                "group_ids": ["g1", "g2"],
                "reason": "Both apply.",
            }
        ]
        decisions = score_assignments(
            groups,
            [self.paragraphs[0]],
            assignments,
            TfidfScorer(self.paragraphs),
            section_weight=0.4,
            corpus_paragraphs=self.paragraphs,
        )
        by_group = {
            candidate["group_id"]: candidate for candidate in decisions[0]["candidates"]
        }
        self.assertEqual(by_group["g1"]["section_cohesion"], 1.0)
        self.assertEqual(by_group["g2"]["section_cohesion"], 0.0)

    def test_merging_preserves_every_existing_assignment_and_singleton(self) -> None:
        groups = [
            {
                "group_id": "g1",
                "question": "How are examples compared?",
                "members": [
                    {
                        "paper": "a",
                        "unit_id": "p1",
                        "combined_score": 0.8,
                        "source_group_ids": ["g1"],
                    }
                ],
                "question_history": [],
            },
            {
                "group_id": "g2",
                "question": "How are examples compared?",
                "members": [
                    {
                        "paper": "a",
                        "unit_id": "p2",
                        "combined_score": 0.7,
                        "source_group_ids": ["g2"],
                    }
                ],
                "question_history": [],
            },
            {
                "group_id": "g3",
                "question": "How was comparison evaluated?",
                "members": [
                    {
                        "paper": "b",
                        "unit_id": "p1",
                        "combined_score": 0.9,
                        "source_group_ids": ["g3"],
                    }
                ],
                "question_history": [],
            },
        ]
        components = [
            {
                "super_group_id": "super_group_1",
                "parent_group_ids": ["g1", "g2"],
                "overarching_question": "How are examples compared?",
                "members": [{"group_id": "g1"}, {"group_id": "g2"}],
                "links": [],
            },
            {
                "super_group_id": "g3",
                "parent_group_ids": ["g3"],
                "members": [{"group_id": "g3"}],
                "links": [],
            },
        ]
        before = assigned_keys(groups)
        merged, events = merge_groups(
            groups,
            components,
            self.paragraphs,
            TfidfScorer(self.paragraphs),
            epoch_number=1,
        )
        self.assertEqual(len(merged), 2)
        self.assertEqual(assigned_keys(merged), before)
        self.assertEqual(len(events), 1)
        self.assertIn("g3", {group["group_id"] for group in merged})

    def test_assignment_is_append_only_and_change_has_no_departure(self) -> None:
        groups = [
            {
                "group_id": "g1",
                "question": "How are examples compared?",
                "members": [{"paper": "a", "unit_id": "p1"}],
            }
        ]
        decisions = [
            {
                "paper": "a",
                "unit_id": "p2",
                "selected_group_ids": ["g1"],
                "reason": "It answers the comparison question.",
                "candidates": [
                    {
                        "group_id": "g1",
                        "semantic_similarity": 0.7,
                        "section_cohesion": 1.0,
                        "combined_score": 0.8,
                        "rank_for_paragraph": 1,
                    }
                ],
            }
        ]
        updated, newly_assigned, _ = apply_assignments(
            groups,
            decisions,
            {("a", "p2"): self.paragraphs[1]},
            epoch_number=1,
        )
        self.assertEqual(assigned_keys(updated), {("a", "p1"), ("a", "p2")})
        self.assertEqual(newly_assigned, [{"paper": "a", "unit_id": "p2"}])
        change = build_changes(decisions, 1)[0]
        self.assertEqual(change["removed_from"], [])
        self.assertFalse(change["became_unassigned"])
        self.assertTrue(change["newly_assigned"])


if __name__ == "__main__":
    unittest.main()
