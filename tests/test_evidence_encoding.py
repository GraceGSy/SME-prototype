import unittest

from pipeline.incremental_graph.evidence_encoding import encode_evidence


class EvidenceEncodingTest(unittest.TestCase):
    def test_lossless_ordered_shared_text(self):
        original = {
            "candidates": [
                {"id": "parent", "full_text": " first \n\nsecond\n\n"},
                {"id": "child", "full_text": "second"},
                {"id": "other-paper", "full_text": "second"},
            ]
        }
        result = encode_evidence(original)
        table = result["source_texts"]
        restored = []
        for item in result["candidates"]:
            restored.append(
                {
                    "id": item["id"],
                    "full_text": "\n\n".join(table[key] for key in item["full_text_refs"]),
                }
            )
        self.assertEqual(restored, original["candidates"])
        self.assertEqual(len(table), 3)
        self.assertIn("full_text", original["candidates"][0])
        self.assertEqual(result, encode_evidence(original))

    def test_reject_non_string_text(self):
        with self.assertRaises(TypeError):
            encode_evidence({"full_text": None})
