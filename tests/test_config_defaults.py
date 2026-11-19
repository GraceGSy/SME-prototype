"""Matching defaults are the same at both levels; older saved configs keep their settings."""

import unittest

from pipeline.incremental_graph.configuration import load_pipeline_config
from pipeline.incremental_graph.models import PipelineConfig
from pipeline.incremental_graph.runs import DEFAULT_CONFIG


class ConfigDefaultsTest(unittest.TestCase):
    def test_new_runs_shortlist_fan_in_and_resolve_close_calls(self):
        config = load_pipeline_config(DEFAULT_CONFIG)
        self.assertEqual(config.shortlist, 10)
        self.assertTrue(config.fan_in)
        self.assertEqual(config.close_call_margin, 0.10)

    def test_saved_configs_with_older_names_keep_what_they_ran(self):
        saved = load_pipeline_config(DEFAULT_CONFIG).model_dump()
        for name in ("fan_in", "shortlist", "close_call_margin"):
            saved.pop(name)
        saved["section_fan_in"] = False
        old = PipelineConfig.model_validate(saved)
        self.assertFalse(old.fan_in)
        self.assertIsNone(old.shortlist)
        self.assertIsNone(old.close_call_margin)
        saved.update(section_fan_in=True, paragraph_shortlist=8, close_call_margin=0.1)
        old = PipelineConfig.model_validate(saved)
        self.assertEqual((old.fan_in, old.shortlist, old.close_call_margin), (True, 8, 0.1))


if __name__ == "__main__":
    unittest.main()
