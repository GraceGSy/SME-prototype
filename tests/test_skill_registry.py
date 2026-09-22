"""Native skill versions are reusable only after a successful upload."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from pipeline.providers.registry import SkillRegistry, _credential_registry


class SkillRegistryTest(unittest.TestCase):
    def test_failed_version_upload_preserves_the_last_good_registration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / "skills" / "test"
            skill.mkdir(parents=True)
            source = skill / "SKILL.md"
            source.write_text("Original instructions")
            path = root / "registry.json"
            upload = Mock(return_value=("skill-1", "v1"))
            first = SkillRegistry(root, path, "account").register(skill, upload)
            saved = path.read_bytes()
            self.assertEqual(SkillRegistry(root, path, "account").register(skill, upload), first)
            self.assertEqual(upload.call_count, 1)
            source.write_text("Changed instructions")
            upload.side_effect = RuntimeError("Upload failed")
            with self.assertRaisesRegex(RuntimeError, "Upload failed"):
                SkillRegistry(root, path, "account").register(skill, upload)
            self.assertEqual(path.read_bytes(), saved)
            self.assertEqual(upload.call_args.args, (skill, first))
            upload.side_effect = None
            upload.return_value = ("skill-1", "v2")
            updated = SkillRegistry(root, path, "account").register(skill, upload)
            self.assertEqual(updated.version, "v2")
            self.assertNotEqual(updated.source_sha256, first.source_sha256)

    def test_skill_registry_is_scoped_without_storing_api_keys(self) -> None:
        state = {"schema_version": 1, "accounts": {}}
        document, first_registry = _credential_registry(state, "key-one")
        first_registry["skills/test"] = {
            "skill_id": "skill-1",
            "version": "v1",
            "source_sha256": "0" * 64,
        }
        _, second_registry = _credential_registry(document, "key-two")
        self.assertEqual(second_registry, {})
        self.assertNotIn("key-one", str(document))
        self.assertNotIn("key-two", str(document))

    def test_registry_rejects_legacy_and_malformed_shapes(self) -> None:
        for state in (
            {},
            {"skills/test": {"skill_id": "legacy"}},
            {"schema_version": "1", "accounts": {}},
            {"schema_version": 1, "accounts": {}, "extra": True},
            {"schema_version": 1, "accounts": {"not-a-hash": {}}},
        ):
            with self.subTest(state=state), self.assertRaises(ValueError):
                _credential_registry(state, "key")
