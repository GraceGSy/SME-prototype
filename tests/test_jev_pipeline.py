"""Exercise real orchestration/export/retry with scripted HTTP and Skill responses."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_jev import answer

from pipeline.document import ROLE_FIELD
from pipeline.files import read_json, write_json
from pipeline.incremental_graph.compare import compare_revisions, load_revision
from pipeline.incremental_graph.runs import retry_graph, start_graph
from pipeline.incremental_graph.smoke_check import check_smoke
from pipeline.providers.contracts import SkillRef
from pipeline.providers.jev import NO_MATCH
from pipeline.viewer.package import validate_dataset

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "datasets/jev-smoke/manifest.yaml"
# Jev calls for the whole smoke run; two come from section fan-in during singleton recovery.
SMOKE_JEV_CALLS = 8


def labeled_texts(papers):
    members = {}
    for rows in papers.values():
        for row in rows:
            for tag in row.get("roles", [row]):
                if row.get("context_only"):
                    continue
                side = tag.get("candidate", tag.get("candidate_group", "focus"))
                by_member = members.setdefault(side, {})
                by_member.setdefault(tag.get("member", 1), []).append(row["text"])
    return {side: ["\n\n".join(parts[i]) for i in sorted(parts)] for side, parts in members.items()}


class ScriptedSkills:
    def __init__(self):
        self.calls = 0

    def register(self, path):
        return SkillRef(str(path), "offline-skill", "1", "offline-hash")

    def run_json(self, skills, user, schema, **kwargs):
        self.calls += 1
        if ROLE_FIELD in schema["properties"]:
            value = {ROLE_FIELD: "Describes how the intervention was evaluated."}
        else:
            target = schema["properties"]["target_id"]["enum"][0]
            focus, _ = json.JSONDecoder().raw_decode(user)
            prefix = kwargs["cacheable_context"]
            papers = json.loads(prefix.split("\n\n", 1)[1])["papers"] if prefix else {}
            centers = labeled_texts({**papers, **focus["papers"]})
            value = {
                "target_id": target,
                "basis": "Scripted offline explanation of the fixed choice.",
                "evidence": {
                    "focus": [text[:80] for text in centers["focus"]],
                    "target": [text[:80] for text in centers[target]],
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
    # This fixture has two disjoint sections per paper, one paragraph per section.
    centers = {}
    side = block = None
    for line in body["state"].splitlines():
        if line in {"Focus", "Context", "Candidates"}:
            block, side = line, None
        elif line.startswith("Section: ") and block != "Context":
            side = "focus" if block == "Focus" else line.split()[1]
            centers[side] = []
        elif side and line.startswith("Content: "):
            centers[side].append(line.removeprefix("Content: "))

    def role(value):
        text = " ".join(value)
        if "water supply" in text or "warning from reaching" in text:
            return "mechanism"
        return "limitation" if "small sample" in text else "future"

    selected = next(
        (
            key
            for key, candidate in centers.items()
            if key != "focus" and role(candidate) == role(centers["focus"])
        ),
        NO_MATCH,
    )
    return io.BytesIO(json.dumps(answer(body, selected)).encode())


class JevPipelineTest(unittest.TestCase):
    def test_section_checkpoint_stops_before_all_paragraph_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "sections"
            with (
                patch("pipeline.incremental_graph.runs.load_api_key", return_value="offline-key"),
                patch("pipeline.providers.jev.load_api_key", return_value="offline-key"),
                patch("pipeline.providers.jev.urlopen", side_effect=scripted_http) as network,
                patch(
                    "pipeline.incremental_graph.judgments.create_skill_client",
                    return_value=ScriptedSkills(),
                ),
            ):
                result = start_graph(MANIFEST, run, jev=True, sections_only=True)
                rev = Path(result["revision_dir"])
                groups = read_json(rev / "section-checkpoint.json")["section_groups"].values()
                self.assertEqual(sorted(len(group["members"]) for group in groups), [1, 1, 2])
                self.assertFalse(any((rev / "stages").glob("*paragraph*")))
                self.assertFalse((rev / "summary.json").exists())
                self.assertIsNone(read_json(run / "run.json")["current_revision"])
                calls = network.call_count
                resumed = retry_graph(run)
                self.assertEqual(network.call_count, calls)
                self.assertTrue(Path(resumed["dataset_dir"]).exists())

    def test_new_uncapped_run_reuses_exact_cached_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = (
                Path(directory).resolve()
            )  # Windows CI gives temp folders short names (RUNNER~1); the code resolves paths.
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
                    jev_model="jev-1.13.0",
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
                first = start_graph(MANIFEST, run, jev=True)
                self.assertTrue(check_smoke(run)["passed"])
                self.assertTrue(validate_dataset(Path(first["dataset_dir"]), "noul", "Noul smoke"))
                paid_calls = (network.call_count, skills.calls)
                retry_graph(run)
                self.assertEqual((network.call_count, skills.calls), paid_calls)
                config = read_json(run / "run.json")["config"]
                self.assertNotIn("selection_mode", config["jev"])
                config["jev"]["model"] = "jev-1.13.0"
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
                self.assertEqual(network.call_count, SMOKE_JEV_CALLS)
                self.assertEqual(skills.calls, 2)  # Group roles only; no explanations.
                revision = run / "revisions/revision-0001"
                snapshot = read_json(revision / "dataset/final_snapshot.json")
                self.assertEqual(snapshot["schema_version"], 2)
                for group in (
                    snapshot["groups"] + snapshot["singletons"] + snapshot["section_groups"]
                ):
                    self.assertIn("role_statement", group)
                    self.assertNotIn("overarching_question", group)
                events = read_json(revision / "events.json")
                self.assertFalse(any(e["action"] == "accepted_match_explained" for e in events))
                attempts = [
                    json.loads(line)
                    for line in (revision / "provenance/attempts.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]
                # Inherited single-paragraph matches keep their deterministic note.
                votes = [a for a in attempts if "jev" in (a.get("raw_response") or {})]
                self.assertTrue(votes)
                for vote in votes:
                    # Jev's selection is the whole record; no generative basis follows it.
                    self.assertNotIn("basis", vote["normalized"])
                    self.assertTrue(vote["raw_response"]["jev"]["calls"])
                data = validate_dataset(
                    Path(first["dataset_dir"]), "offline-smoke", "Offline smoke"
                )
                self.assertTrue(data)
                original_state = read_json(run / "run.json")
                retry_graph(run, jev_max_calls=24, max_api_responses=160)
                self.assertEqual(network.call_count, SMOKE_JEV_CALLS)
                self.assertEqual(skills.calls, 2)  # Group roles only; no explanations.
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
                self.assertEqual(network.call_count, SMOKE_JEV_CALLS)
                self.assertEqual(skills.calls, 2)  # Group roles only; no explanations.
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
                self.assertEqual(network.call_count, SMOKE_JEV_CALLS)
                self.assertEqual(skills.calls, 2)  # Group roles only; no explanations.
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
                    if ROLE_FIELD in args[2]["properties"]:
                        raise RuntimeError("scripted group role outage")
                    return original(*args, **kwargs)

                with patch.object(skills, "run_json", side_effect=broken):
                    with self.assertRaisesRegex(RuntimeError, "group role outage"):
                        start_graph(MANIFEST, run, jev=True)
                self.assertEqual(network.call_count, SMOKE_JEV_CALLS)
                self.assertIsNone(read_json(run / "run.json")["current_revision"])
                retry_graph(run)
                self.assertEqual(network.call_count, SMOKE_JEV_CALLS)
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
