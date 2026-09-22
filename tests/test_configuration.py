"""Configuration mistakes must fail before a model client or run directory exists."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml
from test_graph_runs import manifest
from test_incremental_graph import CONFIG_PATH

from pipeline.incremental_graph.configuration import PromptRepository, load_pipeline_config
from pipeline.incremental_graph.runs import start_graph


class ConfigurationTest(unittest.TestCase):
    def test_rejects_reordered_or_unknown_stages_before_run_creation(self):
        for corruption in ("order", "handler", "prompt", "skill"):
            with self.subTest(corruption=corruption), TemporaryDirectory() as directory:
                root = Path(directory)
                config = load_pipeline_config(CONFIG_PATH).model_dump(mode="json")
                if corruption == "order":
                    config["stages"][1], config["stages"][2] = (
                        config["stages"][2],
                        config["stages"][1],
                    )
                elif corruption == "handler":
                    config["stages"][1]["handler"] = "not_a_handler"
                elif corruption == "prompt":
                    config["stages"][1]["prompt"] = "absent/v1"
                else:
                    config["stages"][1]["skill"] = "absent"
                path = root / "config.yaml"
                path.write_text(yaml.safe_dump(config))
                documents = manifest(root, ["a", "b"], "docs")
                with patch("pipeline.incremental_graph.runs.CachedJudgments") as provider:
                    with self.assertRaises(ValueError):
                        start_graph(documents, root / "run", path)
                    provider.assert_not_called()
                    self.assertFalse((root / "run").exists())

    def test_source_braces_are_not_treated_as_template_instructions(self):
        config = load_pipeline_config(CONFIG_PATH)
        rendered = PromptRepository(config.prompt_root, config.context_root).render(
            "section-question/v1",
            "section-question",
            {"paper": {"title": "Title"}, "section": {"full_text": "{{literal_source}}"}},
        )
        self.assertIn("{{literal_source}}", rendered.user)

    def test_context_configuration_rejects_typos_and_coercion(self):
        config = load_pipeline_config(CONFIG_PATH)
        for content in (
            "include: [paper, section]\nmax_characters: '10'\noverflow: fail\n",
            "include: [paper, section]\nmax_characters: 0\noverflow: fail\nexclude: []\n",
            "include: [paper, section]\nmax_characters: 0\noverflow: fail\ncache_prefix: [typo]\n",
            "include: [paper, section]\nmax_characters: 0\noverflow: fail\ncache_prefix: [paper, paper]\n",
        ):
            with self.subTest(content=content), TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "test.yaml").write_text(content)
                with self.assertRaises(ValueError):
                    PromptRepository(config.prompt_root, root).render(
                        "section-question/v1", "test", {"paper": {}, "section": {}}
                    )

    def test_matching_windows_render_in_reading_order_in_both_directions(self):
        config = load_pipeline_config(CONFIG_PATH)
        repository = PromptRepository(config.prompt_root, config.context_root)
        window = {
            "previous_paragraph": {"full_text": "The witness finishes speaking."},
            "paragraph_under_consideration": {"full_text": "Why did he return?"},
            "next_paragraph": {"full_text": "He returned to recover the evidence."},
        }
        group = {"members": [window]}
        for prompt, focus, candidate in (
            ("paragraph-to-group-match/v1", window, group),
            ("group-to-paragraph-match/v1", group, window),
        ):
            with self.subTest(prompt=prompt):
                rendered = repository.render(
                    prompt,
                    "matching",
                    {
                        "scope": {"level": "paragraph"},
                        "focus": focus,
                        "candidates": [{**candidate, "selection_id": "allowed"}],
                    },
                )
                # Check the actual JSON, not similarly worded instructions above it.
                for block in (rendered.cacheable_context, rendered.user):
                    payload = block[block.index("{\n") :]
                    self.assertLess(
                        payload.index('"previous_paragraph"'),
                        payload.index('"paragraph_under_consideration"'),
                    )
                    self.assertLess(
                        payload.index('"paragraph_under_consideration"'),
                        payload.index('"next_paragraph"'),
                    )
                self.assertIn("paragraph_under_consideration", rendered.system)
                instructions = (config.skill_root / "match-role/SKILL.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("role first", instructions)
                self.assertIn("context only", rendered.system)
