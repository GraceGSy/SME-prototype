"""Consolidated prompt files are runtime inputs, not documentation copies."""

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pipeline.extraction import SKILL
from pipeline.files import read_json, write_json
from pipeline.incremental_graph.configuration import load_pipeline_config
from pipeline.incremental_graph.jev_selection import JevSelector
from pipeline.incremental_graph.runs import DEFAULT_CONFIG, _policy_hash
from pipeline.prompts import PROMPT_ROOT, REPO_ROOT, REQUEST_PROMPT_ROOT, request_prompts
from pipeline.providers.anthropic import CACHEABLE_SYSTEM
from pipeline.providers.jev import JevSettings
from pipeline.providers.openai import INSTRUCTIONS, PROVIDER_PROMPTS


class PromptAssetsTest(unittest.TestCase):
    def test_runtime_roots_and_provider_instructions_use_consolidated_files(self):
        config = load_pipeline_config(DEFAULT_CONFIG)
        self.assertEqual(config.prompt_root, PROMPT_ROOT / "graph")
        self.assertEqual(config.context_root, PROMPT_ROOT / "contexts")
        self.assertEqual(config.skill_root, PROMPT_ROOT / "skills")
        self.assertEqual(SKILL.parent, config.skill_root)
        providers = request_prompts("providers")
        self.assertEqual(CACHEABLE_SYSTEM[0]["text"], providers["anthropic"])
        self.assertEqual(INSTRUCTIONS, providers["openai"])
        self.assertEqual(
            PROVIDER_PROMPTS["openai_result_wrapper"], providers["openai_result_wrapper"]
        )

    def test_editing_jev_file_changes_the_request_and_policy_hash_without_api_calls(self):
        config = load_pipeline_config(DEFAULT_CONFIG)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "requests"
            shutil.copytree(REQUEST_PROMPT_ROOT, assets)
            with (
                patch("pipeline.prompts.REQUEST_PROMPT_ROOT", assets),
                patch("pipeline.providers.jev.urlopen") as network,
            ):
                original = _policy_hash(config)
                extraction = read_json(assets / "extraction.json")
                extraction["instructions"] = "Changed extraction, not graph matching."
                write_json(assets / "extraction.json", extraction)
                self.assertEqual(_policy_hash(config), original)
                wording = read_json(assets / "jev.json")
                wording["choice_question"] = "Edited selection question?"
                write_json(assets / "jev.json", wording)
                selector = JevSelector(
                    JevSettings(), root / "cache", config.skill_root, config.prompt_root
                )
                body = selector.build_request(
                    {
                        "focus": {"full_text": "Source evidence"},
                        "candidates": [{"section_id": "s1", "full_text": "Candidate evidence"}],
                    }
                )
                self.assertEqual(
                    body["questions"]["match"]["instructions"]["question"],
                    wording["choice_question"],
                )
                self.assertNotEqual(_policy_hash(config), original)
                self.assertEqual(selector.client.repo_root, REPO_ROOT)
                network.assert_not_called()
