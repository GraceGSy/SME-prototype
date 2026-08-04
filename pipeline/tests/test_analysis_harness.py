from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import analysis_server
from analysis_server import (
    AnalysisHandler,
    RunManager,
    analysis_python,
    safe_paper_id,
    save_upload,
)
from extract_fine_grained import split_text_chunks
from match_tags import match_granularity
from question_matching import USER_PROMPT_TEMPLATE as QUESTION_MATCH_USER_PROMPT
from question_synthesis import USER_PROMPT_TEMPLATE as SYNTHESIS_USER_PROMPT
from refine_epochs import (
    ASSIGNMENT_USER_PROMPT_TEMPLATE,
    EVIDENCE_ASSIGNMENT_USER_PROMPT_TEMPLATE,
    REPRESENTATIVE_ASSIGNMENT_USER_PROMPT_TEMPLATE,
)
from relabel_full_paper import USER_PROMPT_TEMPLATE as FULL_PAPER_USER_PROMPT
from relabel_section_context import USER_PROMPT_TEMPLATE as FIXED_SECTION_USER_PROMPT
from run_analysis import prompt_manifest, reuse_source_artifacts, stage_input_papers
from section_schema import Section, SectionedPaper


class AnalysisHarnessTests(unittest.TestCase):
    def test_upload_is_validated_and_saved_with_provenance(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(analysis_server, "UPLOADS_DIR", Path(directory)),
        ):
            result = save_upload("A paper with spaces.pdf", b"%PDF-1.4\nfixture")
            self.assertEqual(result["paper_id"], "A_paper_with_spaces")
            self.assertTrue((Path(directory) / result["stored_filename"]).is_file())
            self.assertTrue((Path(directory) / f"{result['upload_id']}.json").is_file())
            self.assertNotIn("fixture", str(result))

    def test_upload_rejects_non_pdf_content(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(analysis_server, "UPLOADS_DIR", Path(directory)),
            self.assertRaisesRegex(ValueError, "valid PDF header"),
        ):
            save_upload("paper.pdf", b"not a pdf")

    def test_config_exposes_every_repeatability_setting(self) -> None:
        config = AnalysisHandler._validated_config({})
        for name in (
            "model",
            "max_epochs",
            "section_weight",
            "question_stability_threshold",
            "section_context_max_chars",
            "paragraph_chunk_chars",
            "assignment_batch_chars",
            "representative_per_paper",
            "representative_max_per_group",
            "match_top_k",
            "section_group_threshold",
            "paragraph_group_threshold",
            "supergroup_threshold",
            "experiment_label",
            "paragraph_context",
            "assignment_context",
            "reuse_scope",
            "source_run_id",
        ):
            self.assertIn(name, config)

    def test_prompt_manifest_uses_runtime_prompt_templates(self) -> None:
        prompts = prompt_manifest()["prompts"]
        self.assertEqual(
            prompts["question_synthesis"]["user_template"], SYNTHESIS_USER_PROMPT
        )
        self.assertEqual(
            prompts["group_question_matching"]["user_template"],
            QUESTION_MATCH_USER_PROMPT,
        )
        self.assertEqual(
            prompts["epoch_assignment"]["user_template"],
            ASSIGNMENT_USER_PROMPT_TEMPLATE,
        )
        self.assertEqual(
            prompts["full_paper_paragraph_relabeling"]["user_template"],
            FULL_PAPER_USER_PROMPT,
        )
        self.assertEqual(
            prompts["fixed_section_paragraph_relabeling"]["user_template"],
            FIXED_SECTION_USER_PROMPT,
        )
        self.assertEqual(
            prompts["epoch_assignment_all_group_paragraphs"]["user_template"],
            EVIDENCE_ASSIGNMENT_USER_PROMPT_TEMPLATE,
        )
        self.assertEqual(
            prompts["epoch_assignment_representative_group_paragraphs"][
                "user_template"
            ],
            REPRESENTATIVE_ASSIGNMENT_USER_PROMPT_TEMPLATE,
        )

    def test_api_key_is_child_only_and_never_enters_public_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / "papers"
            library.mkdir()
            for name in ("one.pdf", "two.pdf"):
                (library / name).write_bytes(b"%PDF-1.4\nfixture")
            runs = root / "runs"
            runs.mkdir()
            with (
                patch.object(analysis_server, "RUNS_DIR", runs),
                patch.object(analysis_server, "LATEST_PATH", root / "missing.json"),
                patch.object(analysis_server, "UPLOADS_DIR", root / "uploads"),
                patch.object(analysis_server, "papers_dir", return_value=library),
                patch.object(analysis_server.subprocess, "Popen") as popen,
                patch.object(analysis_server.threading, "Thread") as thread,
            ):
                process = MagicMock()
                process.poll.return_value = 0
                popen.return_value = process
                manager = RunManager()
                state = manager.start(
                    ["one", "two"],
                    [],
                    dict(analysis_server.DEFAULT_CONFIG),
                    api_key="secret-run-key",
                )
            child_env = popen.call_args.kwargs["env"]
            self.assertEqual(child_env["ANTHROPIC_API_KEY"], "secret-run-key")
            input_names = __import__("json").loads(child_env["SME_INPUT_NAMES_JSON"])
            self.assertEqual(set(input_names.values()), {"one.pdf", "two.pdf"})
            self.assertNotIn("secret-run-key", str(state))
            self.assertNotIn("anthropic_api_key", state["config"])
            thread.return_value.start.assert_called_once()

    def test_analysis_process_uses_project_virtual_environment(self) -> None:
        expected = analysis_server.PIPELINE_DIR / ".venv" / "Scripts" / "python.exe"
        if expected.is_file():
            self.assertEqual(analysis_python(), expected)

    def test_staged_inputs_are_collision_safe_and_replayable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            (left / "paper.pdf").write_bytes(b"%PDF-1.4\nleft")
            (right / "paper.pdf").write_bytes(b"%PDF-1.4\nright")
            output = root / "run"
            output.mkdir()
            staged, metadata = stage_input_papers(
                [left / "paper.pdf", right / "paper.pdf"], output
            )
            self.assertEqual([path.stem for path in staged], ["paper", "paper_2"])
            self.assertEqual(len({item["sha256"] for item in metadata}), 2)
            self.assertTrue(all(path.is_file() for path in staged))

    def test_uploaded_display_name_survives_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / ("a" * 32 + "--stored.pdf")
            source.write_bytes(b"%PDF-1.4\nfixture")
            output = root / "run"
            output.mkdir()
            staged, metadata = stage_input_papers(
                [source], output, {str(source.resolve()): "Human readable paper.pdf"}
            )
            self.assertEqual(staged[0].stem, "Human_readable_paper")
            self.assertEqual(
                metadata[0]["original_filename"], "Human readable paper.pdf"
            )

    def test_chunking_never_drops_source_text(self) -> None:
        text = "first line\nsecond line\nthird line\nfourth line"
        chunks = split_text_chunks(text, 18)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), text)
        self.assertEqual(split_text_chunks(text, 0), [text])

    def test_safe_paper_id_is_not_tied_to_fixture_names(self) -> None:
        self.assertEqual(safe_paper_id("Novel Study (2027).pdf"), "Novel_Study_2027")

    def test_cross_paper_matching_supports_arbitrary_paper_counts(self) -> None:
        papers = {
            f"paper_{index}": SectionedPaper(
                paper_id=f"paper_{index}",
                title=f"Paper {index}",
                sections=[Section(id="s1", tag=f"What does study {index} contribute?")],
            )
            for index in range(4)
        }
        entries = match_granularity(papers, "sections")
        self.assertEqual(len(entries), 4)
        for entry in entries:
            self.assertEqual(
                {match["paper"] for match in entry["matches"]},
                set(papers) - {entry["paper"]},
            )

    def test_source_reuse_requires_identical_pdfs_and_preserves_paragraph_ids(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            output.mkdir()
            paper = SectionedPaper(
                paper_id="one",
                title="One",
                sections=[Section(id="s1", tag="What is studied?")],
                paragraphs=[
                    Section(
                        id="pa1",
                        tag="What is the finding?",
                        text="Complete paragraph.",
                        parent_section_id="s1",
                    )
                ],
            )
            (source / "one.json").write_text(
                __import__("json").dumps(paper.model_dump()), encoding="utf-8"
            )
            (source / "manifest.json").write_text(
                __import__("json").dumps(
                    [{"paper_id": "one", "title": "One", "file": "one.json"}]
                ),
                encoding="utf-8",
            )
            (source / "analysis_run.json").write_text(
                __import__("json").dumps(
                    {
                        "run_id": "source-run",
                        "status": "complete",
                        "papers": [{"paper_id": "one", "sha256": "abc"}],
                    }
                ),
                encoding="utf-8",
            )
            provenance = reuse_source_artifacts(
                source,
                output,
                "paragraph_corpus",
                [{"paper_id": "one", "sha256": "abc"}],
            )
            self.assertEqual(provenance["paragraph_count"], 1)
            self.assertEqual(provenance["source_run_id"], "source-run")
            self.assertTrue((output / "one.json").is_file())
            with self.assertRaisesRegex(ValueError, "do not exactly match"):
                reuse_source_artifacts(
                    source,
                    output,
                    "paragraph_corpus",
                    [{"paper_id": "one", "sha256": "different"}],
                )


if __name__ == "__main__":
    unittest.main()
