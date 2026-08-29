from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from pipeline.viewer.final_snapshot import build_dataset


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def pseudo_section(
    source_id: str,
    section_name: str,
    question: str,
    text: str,
) -> dict[str, object]:
    return {
        "section_number": source_id,
        "section_name": section_name,
        "question_this_section_answers": question,
        "paragraphs": [{"paragraph_number": 1, "text": text}],
    }


def make_sources(root: Path) -> tuple[Path, Path, Path]:
    metadata = root / "metadata"
    write_json(metadata / "manifest.json", [
        {"paper_id": "paper_a", "title": "Paper A", "file": "paper_a.json"},
        {"paper_id": "paper_b", "title": "Paper B", "file": "paper_b.json"},
    ])
    write_json(metadata / "paper_a.json", {
        "sections": [{"title": "Introduction"}, {"title": "Discussion"}],
    })
    write_json(metadata / "paper_b.json", {
        "sections": [{"title": "Introduction"}, {"title": "Conclusion"}],
    })

    archive_path = root / "pseudo-sections.zip"
    entries = [
        pseudo_section(
            "paper_a::introduction::2",
            "Introduction",
            "What shared role does A serve?",
            "Exact duplicate paragraph.",
        ),
        pseudo_section(
            "paper_a::discussion::1",
            "Discussion",
            "Why is this unique to A?",
            "Exact duplicate paragraph.",
        ),
        pseudo_section(
            "paper_b::introduction::1",
            "Introduction",
            "What shared role does B serve?",
            "Paper B shared paragraph.",
        ),
        pseudo_section(
            "paper_b::conclusion::1",
            "Conclusion",
            "What raw fallback question is answered?",
            "Paper B singleton paragraph.",
        ),
        pseudo_section(
            "paper_a::references::1",
            "References",
            "What is cited?",
            "Omitted references text.",
        ),
        pseudo_section(
            "paper_b::appendix::1",
            "Appendix A",
            "What supplemental material is included?",
            "Omitted appendix text.",
        ),
    ]
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("chunks.json", json.dumps(entries))

    structure_path = root / "structure.json"
    write_json(structure_path, [
        {
            "role_slug": "introduction",
            "row_source": "common",
            "section_level_match": {
                "question_the_sections_answer": "What motivates the papers?",
                "pairing_status": "common-structure",
                "papers": {
                    "paper_a": {"section_name": "Introduction", "section_number": "1"},
                    "paper_b": {"section_name": "Introduction", "section_number": "1"},
                },
            },
            "paragraph_level_common_structure": [{
                "question_the_sections_answer": "What shared role do the papers address?",
                "pairing_status": "common-structure",
                "papers": {
                    "paper_a": {"section_number": "paper_a::introduction::2"},
                    "paper_b": {"section_number": "paper_b::introduction::1"},
                },
            }],
            "paragraph_level_leftovers": [],
        },
        {
            "role_slug": "discussion",
            "row_source": "paper_a",
            "section_level_match": {
                "question_the_sections_answer": "What does A discuss?",
                "papers": {
                    "paper_a": {"section_name": "Discussion", "section_number": "2"},
                },
            },
            "paragraph_level_common_structure": [],
            "paragraph_level_leftovers": [{
                "question_the_sections_answer": "Why is this unique to A?",
                "papers": {
                    "paper_a": {"section_number": "paper_a::discussion::1"},
                },
            }],
        },
        {
            "role_slug": "conclusion",
            "row_source": "paper_b",
            "section_level_match": {
                "question_the_sections_answer": "What does B conclude?",
                "papers": {
                    "paper_b": {"section_name": "Conclusion", "section_number": "2"},
                },
            },
            "paragraph_level_common_structure": [],
            "paragraph_level_leftovers": [{
                "question_the_sections_answer": None,
                "papers": {
                    "paper_b": {"section_number": "paper_b::conclusion::1"},
                },
            }],
        },
    ])
    return archive_path, structure_path, metadata


class FinalSnapshotDatasetTest(unittest.TestCase):
    def test_builds_deduplicated_provenance_preserving_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, structure, metadata = make_sources(root)
            first = root / "first"
            second = root / "second"

            stats = build_dataset(archive, structure, metadata, first)
            build_dataset(archive, structure, metadata, second)

            self.assertEqual(stats["raw_paragraph_chunks"], 4)
            self.assertEqual(stats["paragraph_chunks"], 3)
            self.assertEqual(stats["exact_duplicates_removed"], 1)
            self.assertEqual(stats["omitted_reference_or_appendix_chunks"], 2)
            self.assertEqual(stats["shared_question_groups"], 1)
            self.assertEqual(stats["shared_paragraph_chunks"], 2)
            self.assertEqual(stats["singleton_questions"], 1)
            self.assertEqual(stats["section_question_groups"], 1)

            snapshot = json.loads((first / "final_snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["singletons"][0]["overarching_question"], "What raw fallback question is answered?")
            self.assertEqual(len(snapshot["groups"][0]["members"]), 2)
            paper_a_member = next(
                member for member in snapshot["groups"][0]["members"] if member["paper"] == "paper_a"
            )
            self.assertEqual(
                paper_a_member["source_ids"],
                ["paper_a::discussion::1", "paper_a::introduction::2"],
            )

            all_paper_text = " ".join(
                json.loads((first / entry["file"]).read_text(encoding="utf-8"))["paragraphs"][0]["text"]
                for entry in json.loads((first / "manifest.json").read_text(encoding="utf-8"))
            )
            self.assertNotIn("Omitted references text", all_paper_text)
            self.assertNotIn("Omitted appendix text", all_paper_text)

            for path in sorted(first.glob("*.json")):
                self.assertEqual(path.read_bytes(), (second / path.name).read_bytes())


if __name__ == "__main__":
    unittest.main()
