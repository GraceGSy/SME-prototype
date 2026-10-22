"""Exercise real orchestration/export/retry with scripted HTTP and Skill responses."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_jev import answer

from pipeline.document import QUESTION_FIELD
from pipeline.files import read_json, write_json
from pipeline.incremental_graph.compare import compare_revisions
from pipeline.incremental_graph.match_evidence import candidate_handle, center_texts
from pipeline.incremental_graph.runs import retry_graph, start_graph
from pipeline.incremental_graph.smoke_check import check_smoke
from pipeline.providers.contracts import SkillRef
from pipeline.providers.jev import NO_MATCH
from pipeline.viewer.package import validate_dataset

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "datasets/jev-smoke/manifest.yaml"


def decode_state(value):
    texts = value["source_texts"]

    def decode(item):
        if isinstance(item, list):
            return [decode(child) for child in item]
        if not isinstance(item, dict):
            return item
        result = {key: decode(child) for key, child in item.items() if key != "full_text_refs"}
        if "full_text_refs" in item:
            result["full_text"] = "\n\n".join(texts[key] for key in item["full_text_refs"])
        return result

    return decode(value)


class ScriptedSkills:
    def __init__(self):
        self.calls = 0

    def register(self, path):
        return SkillRef(str(path), "offline-skill", "1", "offline-hash")

    def run_json(self, skills, user, schema, **kwargs):
        self.calls += 1
        if QUESTION_FIELD in schema["properties"]:
            value = {QUESTION_FIELD: "What role do these passages perform?"}
        else:
            target = schema["properties"]["target_id"]["enum"][0]
            focus, _ = json.JSONDecoder().raw_decode(user)
            prefix = json.loads(kwargs["cacheable_context"].split("\n\n", 1)[1])
            context = {**decode_state(prefix), **focus}
            candidate = next(
                item for item in context["candidates"] if candidate_handle(item) == target
            )
            value = {
                "target_id": target,
                "basis": "Scripted offline explanation of the fixed choice.",
                "evidence": {
                    "focus": [text[:80] for text in center_texts(context["focus"])],
                    "target": [text[:80] for text in center_texts(candidate)],
                },
            }
        return SimpleNamespace(
            value=value,
            raw_response={
                "id": f"offline-{self.calls}",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )


def scripted_http(request, **kwargs):
    body = json.loads(request.data)
    state = decode_state(body["state"])

    def role(value):
        text = " ".join(center_texts(value))
        if "water supply" in text or "warning from reaching" in text:
            return "mechanism"
        return "limitation" if "small sample" in text else "future"

    selected = next(
        (
            candidate_handle(candidate)
            for candidate in state["candidates"]
            if role(candidate) == role(state["focus"])
        ),
        NO_MATCH,
    )
    return io.BytesIO(json.dumps(answer(body, selected)).encode())


class JevPipelineTest(unittest.TestCase):
    def test_smoke_exports_viewer_data_and_retry_reuses_both_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            skills = ScriptedSkills()
            with (
                patch("pipeline.incremental_graph.runs.load_api_key", return_value="offline-key"),
                patch("pipeline.providers.jev.load_api_key", return_value="offline-key"),
                patch("pipeline.providers.jev.urlopen", side_effect=scripted_http) as network,
                patch(
                    "pipeline.incremental_graph.judgments.create_skill_client", return_value=skills
                ),
            ):
                first = start_graph(MANIFEST, run, jev=True, jev_max_calls=12, max_api_responses=80)
                self.assertTrue(check_smoke(run)["passed"])
                self.assertEqual(network.call_count, 6)
                self.assertEqual(skills.calls, 6)
                data = validate_dataset(
                    Path(first["dataset_dir"]), "offline-smoke", "Offline smoke"
                )
                self.assertTrue(data)
                retry_graph(run)
                self.assertEqual(network.call_count, 6)
                self.assertEqual(skills.calls, 6)
            report = compare_revisions(
                run / "revisions/revision-0001", run / "revisions/revision-0002"
            )
            self.assertEqual(report["levels"]["paragraph"]["changed_units"], 0)
            self.assertEqual(read_json(run / "run.json")["config"]["jev"]["model"], "jev-1.14.0")

    def test_failure_keeps_selection_and_retry_finishes_without_rebuying_it(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            skills = ScriptedSkills()
            with (
                patch("pipeline.incremental_graph.runs.load_api_key", return_value="offline-key"),
                patch("pipeline.providers.jev.load_api_key", return_value="offline-key"),
                patch("pipeline.providers.jev.urlopen", side_effect=scripted_http) as network,
                patch(
                    "pipeline.incremental_graph.judgments.create_skill_client", return_value=skills
                ),
            ):
                original = skills.run_json

                def broken(*args, **kwargs):
                    if "target_id" in args[2]["properties"]:
                        raise RuntimeError("scripted evidence outage")
                    return original(*args, **kwargs)

                with patch.object(skills, "run_json", side_effect=broken):
                    with self.assertRaisesRegex(RuntimeError, "evidence outage"):
                        start_graph(MANIFEST, run, jev=True)
                self.assertEqual(network.call_count, 1)
                self.assertIsNone(read_json(run / "run.json")["current_revision"])
                retry_graph(run)
                self.assertEqual(network.call_count, 6)
                self.assertTrue(check_smoke(run)["passed"])

    def test_smoke_checker_fails_on_wrong_membership(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            with (
                patch("pipeline.incremental_graph.runs.load_api_key", return_value="offline-key"),
                patch("pipeline.providers.jev.load_api_key", return_value="offline-key"),
                patch("pipeline.providers.jev.urlopen", side_effect=scripted_http),
                patch(
                    "pipeline.incremental_graph.judgments.create_skill_client",
                    return_value=ScriptedSkills(),
                ),
            ):
                result = start_graph(MANIFEST, run, jev=True)
            path = Path(result["dataset_dir"]) / "final_snapshot.json"
            snapshot = read_json(path)
            shared = snapshot["groups"].pop()
            for index, member in enumerate(shared["members"]):
                snapshot["singletons"].append(
                    {**shared, "group_id": f"split-{index}", "members": [member]}
                )
            write_json(path, snapshot)
            self.assertFalse(check_smoke(run)["passed"])


if __name__ == "__main__":
    unittest.main()
