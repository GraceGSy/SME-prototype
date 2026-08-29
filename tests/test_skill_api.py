from types import SimpleNamespace
import unittest

from pipeline.incremental_graph.skill_api import _version_id


class SkillApiTest(unittest.TestCase):
    def test_reads_current_and_legacy_skill_version_fields(self) -> None:
        self.assertEqual(
            _version_id(SimpleNamespace(latest_version_id="current"), "latest_version_id", "latest_version"),
            "current",
        )
        self.assertEqual(
            _version_id(SimpleNamespace(version="legacy"), "id", "version"),
            "legacy",
        )


if __name__ == "__main__":
    unittest.main()
