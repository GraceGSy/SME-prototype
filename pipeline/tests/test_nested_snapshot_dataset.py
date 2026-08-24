from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_nested_snapshot_dataset import build_dataset
from viewer_dataset import validate_dataset


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def paper_section(name: str, question: str, paragraphs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "section_name": name,
        "section_number": None,
        "paragraphs": paragraphs,
        "question_this_section_answers": question,
    }


def mapping(question: str, papers: dict[str, tuple[str, int, str]]) -> dict[str, object]:
    return {
        "question_the_sections_answer": question,
        "papers": {
            paper_id: {
                "section_number": f"{paper_id}::{section}::{number}",
                "paragraphs": [{"paragraph_number": number, "text": text}],
            }
            for paper_id, (section, number, text) in papers.items()
        },
    }


def make_sources(root: Path) -> tuple[Path, Path, Path]:
    metadata = root / "metadata"
    paper_dir = root / "papers"
    structure = root / "structure.json"
    write_json(metadata / "manifest.json", [
        {"paper_id": "paper_a", "title": "Paper A", "file": "paper_a.json"},
        {"paper_id": "paper_b", "title": "Paper B", "file": "paper_b.json"},
    ])
    write_json(paper_dir / "paper_a-sections-with-paragraphs-and-questions-no-appendices.json", [
        paper_section("Introduction", "What does this section introduce?", [
            {"paragraph_number": 0, "text": "Shared paragraph A."},
            {
                "paragraph_number": 1,
                "text": "Explicit fallback paragraph.",
                "question_this_paragraph_answers": "What fallback question is answered?",
            },
        ]),
        paper_section("Case Study", "What happened in the case study?", [
            {"paragraph_number": 0, "text": "Section-only question paragraph."},
        ]),
        paper_section("References", "What is cited?", []),
    ])
    write_json(paper_dir / "paper_b-sections-with-paragraphs-and-questions-no-appendices.json", [
        paper_section("INTRODUCTION", "What does this section introduce?", [
            {"paragraph_number": 0, "text": "Shared paragraph B."},
        ]),
    ])
    write_json(structure, [{
        "role_slug": "introduction",
        "row_source": "test",
        "paragraph_level_common_structure": [mapping(
            "What shared question is answered?",
            {
                "paper_a": ("Introduction", 0, "Shared paragraph A."),
                "paper_b": ("Introduction", 0, "Shared paragraph B."),
            },
        )],
        "paragraph_level_leftovers": [mapping(
            "What is unique about this paragraph?",
            {"paper_a": ("Introduction", 0, "Shared paragraph A.")},
        )],
    }])
    return structure, paper_dir, metadata


class NestedSnapshotDatasetTest(unittest.TestCase):
    def test_preserves_many_to_many_questions_and_leaves_section_only_paragraph_unassigned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            structure, paper_dir, metadata = make_sources(root)
            first = root / "first"
            second = root / "second"

            stats = build_dataset(structure, paper_dir, metadata, first)
            build_dataset(structure, paper_dir, metadata, second)
            descriptor = validate_dataset(first, "nested", "Nested")

            self.assertEqual(descriptor["mode"], "final_snapshot")
            self.assertEqual(descriptor["paragraph_count"], 4)
            self.assertEqual(stats["shared_question_groups"], 1)
            self.assertEqual(stats["singleton_questions"], 2)
            self.assertEqual(stats["shared_singleton_overlap"], 1)
            self.assertEqual(stats["source_paragraph_questions_used"], 1)
            self.assertEqual(stats["unassigned_paragraph_chunks"], 1)

            paper_a = json.loads((first / "paper_a.json").read_text(encoding="utf-8"))
            self.assertEqual(paper_a["paragraphs"][0]["tag"], "What shared question is answered?")
            self.assertEqual(paper_a["paragraphs"][1]["tag"], "What fallback question is answered?")
            self.assertEqual(paper_a["paragraphs"][2]["tag"], "")

            for path in sorted(first.glob("*.json")):
                self.assertEqual(path.read_bytes(), (second / path.name).read_bytes())


if __name__ == "__main__":
    unittest.main()
