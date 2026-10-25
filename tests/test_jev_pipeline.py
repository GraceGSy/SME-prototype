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
from pipeline.incremental_graph.compare import compare_revisions, load_revision
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
            for candidate in state["candidates"].values()
            if role(candidate) == role(state["focus"])
        ),
        NO_MATCH,
    )
    return io.BytesIO(json.dumps(answer(body, selected)).encode())


class JevPipelineTest(unittest.TestCase):
    def test_new_uncapped_run_reuses_exact_cached_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skills = ScriptedSkills()
            with (
                patch("pipeline.incremental_graph.runs.load_api_key", return_value="offline-key"),
                patch("pipeline.providers.jev.load_api_key", return_value="offline-key"),
                patch("pipeline.providers.jev.urlopen", side_effect=scripted_http) as network,
                patch(
                    "pipeline.incremental_graph.judgments.create_skill_client", return_value=skills
                ),
            ):
                source = root / "capped"
                start_graph(MANIFEST, source, jev=True, jev_max_calls=12, max_api_responses=80)
                source_state = (source / "run.json").read_bytes()
                paid_calls = (network.call_count, skills.calls)
                destination = root / "uncapped"
                start_graph(MANIFEST, destination, jev=True, cache_from=source)
                self.assertEqual((network.call_count, skills.calls), paid_calls)
                self.assertTrue(check_smoke(destination)["passed"])
                self.assertEqual((source / "run.json").read_bytes(), source_state)
                config = read_json(destination / "run.json")["config"]
                self.assertIsNone(config["jev"]["max_calls"])
                self.assertIsNone(config["jev"]["max_input_tokens"])
                self.assertIsNone(config["model"]["max_api_responses_per_process"])
                self.assertEqual(
                    read_json(destination / "cache-source.json")["run_dir"], str(source)
                )
                start_graph(
                    MANIFEST,
                    root / "changed",
                    jev=True,
                    jev_selection_mode="choice_noul",
                    cache_from=source,
                )
                self.assertGreater(network.call_count, paid_calls[0])

    def test_invalid_cache_source_fails_before_run_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "Cache source"):
                start_graph(MANIFEST, root / "new", cache_from=root / "missing")
            self.assertFalse((root / "new").exists())

    def test_noul_smoke_exports_and_retries_without_paid_calls(self):
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
                first = start_graph(MANIFEST, run, jev=True, jev_selection_mode="choice_noul")
                self.assertTrue(check_smoke(run)["passed"])
                self.assertTrue(validate_dataset(Path(first["dataset_dir"]), "noul", "Noul smoke"))
                paid_calls = (network.call_count, skills.calls)
                retry_graph(run)
                self.assertEqual((network.call_count, skills.calls), paid_calls)
                config = read_json(run / "run.json")["config"]
                self.assertEqual(config["jev"]["selection_mode"], "choice_noul")
                config["jev"]["selection_mode"] = "choice"
                write_json(run / "changed.json", config)
                with self.assertRaisesRegex(ValueError, "scientific configuration changed"):
                    retry_graph(run, config_path=run / "changed.json")

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
                self.assertEqual(network.call_count, 4)
                self.assertEqual(skills.calls, 4)
                data = validate_dataset(
                    Path(first["dataset_dir"]), "offline-smoke", "Offline smoke"
                )
                self.assertTrue(data)
                original_state = read_json(run / "run.json")
                retry_graph(run, jev_max_calls=24, max_api_responses=160)
                self.assertEqual(network.call_count, 4)
                self.assertEqual(skills.calls, 4)
                retry_config = read_json(run / "run.json")["config"]
                retry_config["jev"].update(max_input_tokens=4_000_000, timeout_seconds=240)
                retry_config["model"].update(
                    max_input_tokens=400_000,
                    max_prompt_characters=1_000_000,
                    max_session_input_tokens=60_000_000,
                    max_session_output_tokens=2_000_000,
                )
                for stage in retry_config["stages"]:
                    stage["max_input_tokens"] = 400_000
                write_json(run / "retry-config.json", retry_config)
                retry_graph(run, config_path=run / "retry-config.json")
                self.assertEqual(network.call_count, 4)
                self.assertEqual(skills.calls, 4)
                self.assertEqual(
                    read_json(run / "run.json")["policy_sha256"], original_state["policy_sha256"]
                )
                self.assertEqual(
                    read_json(run / "revisions/revision-0001/config.json"), original_state["config"]
                )
                self.assertEqual(
                    read_json(run / "revisions/revision-0003/config.json"), retry_config
                )
            report = compare_revisions(
                run / "revisions/revision-0001", run / "revisions/revision-0002"
            )
            self.assertEqual(report["levels"]["paragraph"]["changed_units"], 0)
            self.assertEqual(read_json(run / "run.json")["config"]["jev"]["model"], "jev-1.14.0")
            self.assertEqual(
                load_revision(run / "revisions/revision-0001")["settings"]["jev"]["max_calls"], 12
            )
            self.assertEqual(load_revision(run)["settings"]["jev"]["timeout_seconds"], 240)

    def test_call_budget_failure_can_retry_with_larger_budget_without_rebuying_choices(self):
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
                with self.assertRaisesRegex(ValueError, "Jev call limit"):
                    start_graph(MANIFEST, run, jev=True, jev_max_calls=1)
                self.assertEqual(network.call_count, 1)
                failure = run / "revisions/revision-0001/failure.json"
                original_failure = failure.read_bytes()
                retry_graph(run, jev_max_calls=12)
                self.assertEqual(network.call_count, 4)
                self.assertEqual(skills.calls, 4)
                self.assertEqual(failure.read_bytes(), original_failure)
                self.assertTrue(check_smoke(run)["passed"])

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
                self.assertEqual(network.call_count, 4)
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
