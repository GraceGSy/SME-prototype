"""Jev transport, selection, caching, and evidence tests without network access."""

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import test_judgment_cache
from test_graph_runs import manifest
from test_incremental_graph import CONFIG_PATH
from test_paragraph_only_inputs import document

from pipeline.files import write_json
from pipeline.incremental_graph.configuration import PromptRepository, load_pipeline_config
from pipeline.incremental_graph.evidence import Evidence
from pipeline.incremental_graph.evidence_encoding import encode_evidence
from pipeline.incremental_graph.graph import RoleGraph
from pipeline.incremental_graph.input_data import load_paper
from pipeline.incremental_graph.jev_selection import JevSelector
from pipeline.incremental_graph.judgments import CachedJudgments, JudgmentError
from pipeline.incremental_graph.models import PaperManifest
from pipeline.incremental_graph.runs import start_graph
from pipeline.providers.jev import (
    NO_MATCH,
    JevClient,
    JevRequestTooLarge,
    JevSettings,
    choice_from_probabilities,
    encode_request,
    validate_response,
)


def answer(body, choice=None, noul=None):
    answers = {}
    if "match" in body["questions"]:
        options = body["questions"]["match"]["criteria"]
        selected = choice if choice in options else next(iter(options))
        answers["match"] = {
            "type": "choice",
            "choice": selected,
            "confidence": 1.0,
            "probabilities": {option: float(option == selected) for option in options},
        }
    if "has_match" in body["questions"]:
        answers["has_match"] = {
            "type": "noul",
            "noul": float(choice != NO_MATCH) if noul is None else noul,
        }
    return {
        "model": body["model"],
        "answers": answers,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


class JevTest(unittest.TestCase):
    def setUp(self):
        self.config = load_pipeline_config(CONFIG_PATH)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def selector(self, **settings):
        # Long context is on by default; these unit tests turn it off unless they test it,
        # so size rejections exercise the split and stop rules directly.
        return JevSelector(
            JevSettings(**{"long_context_retry": False, **settings}),
            self.root / "jev",
        )

    def request(self, count=1):
        request = test_judgment_cache.JudgmentCacheTest().request()
        request.allowed_match_ids = [f"candidate-{i}" for i in range(count)]
        source = request.context["candidates"][0]
        request.context["candidates"] = [
            {
                **source,
                "selection_id": key,
                "paragraph_under_consideration": {"full_text": f"Repeated corpus passage {n}."},
            }
            for n, key in enumerate(request.allowed_match_ids)
        ]
        return request

    def provider(self, **settings):
        return CachedJudgments(
            PromptRepository(self.config.prompt_root, self.config.context_root),
            self.config.model,
            self.root / "cache",
            self.config.skill_root,
            jev=JevSettings(**settings),
        )

    def test_source_order_and_group_labels_survive_overlapping_windows(self):
        def unit(paper, i, center, before=None, after=None):
            return {
                "paper_key": paper,
                "source_position": [1, i],
                "paragraph_under_consideration": {"full_text": center},
                "previous_paragraph": {"full_text": before} if before else None,
                "next_paragraph": {"full_text": after} if after else None,
            }

        req = self.request(2)
        req.context.update(
            focus=unit("paper-3", 1, "The trial found fewer errors."),
            candidates=[
                {
                    "selection_id": "design",
                    "members": [unit("paper-1", 3, "Users compared two screens.", "Errors fell.")],
                },
                {
                    "selection_id": "results",
                    "members": [
                        unit("paper-2", 1, "Accuracy improved."),
                        unit(
                            "paper-1",
                            2,
                            "Errors fell.",
                            "We tested the tool.",
                            "Users compared two screens.",
                        ),
                    ],
                },
            ],
        )
        req.allowed_match_ids = ["design", "results"]
        reverse = req.model_copy(deep=True)
        reverse.context.update(
            focus=req.context["candidates"][1],
            candidates=[
                {**req.context["focus"], "selection_id": "private-id-1"},
                {**unit("paper-3", 2, "We invited volunteers."), "selection_id": "private-id-2"},
            ],
        )
        reverse.allowed_match_ids = ["private-id-1", "private-id-2"]
        for request, option, question in [
            (req, "Group P1", "Does the new paragraph fit"),
            (reverse, "C1.2", "Does any candidate paragraph"),
        ]:
            selector = self.selector()
            gate = selector.build_request(request.context)
            rank = selector.build_request(request.context, "match")
            self.assertTrue(
                gate["questions"]["has_match"]["instructions"]["question"].startswith(question)
            )
            self.assertEqual(rank["state"], gate["state"])
            if request is req:
                self.assertEqual(list(rank["questions"]["match"]["criteria"]), ["A1.3", "Group P1"])
                self.assertNotIn("Group A", rank["state"])
            focus, candidates = rank["state"].split("\nCandidates\n")
            self.assertIn("The trial found fewer errors.", focus if request is req else candidates)
            self.assertIn("Accuracy improved.", candidates if request is req else focus)
            self.assertIn("context only", rank["state"])
            self.assertLess(
                rank["state"].index("Errors fell."), rank["state"].index("Accuracy improved.")
            )
            self.assertEqual(rank["state"].count("Errors fell."), 1)
            self.assertIn(option, rank["questions"]["match"]["criteria"])
            wire = json.dumps(rank)
            rendered = self.provider().render_request(request)
            for key in request.allowed_match_ids:
                self.assertNotIn(key, wire)
                self.assertNotIn(
                    key,
                    (rendered.cacheable_context or "")
                    + rendered.user
                    + json.dumps(rendered.schema),
                )
            with patch.object(
                selector.client, "choose", side_effect=lambda body: answer(body, option)
            ) as client:
                self.assertEqual(
                    selector.select(request)["target_id"], request.allowed_match_ids[1]
                )
                self.assertTrue(all(c["cache_hit"] for c in selector.select(request)["calls"]))
                self.assertEqual(client.call_count, 2)

    def test_singletons_render_identically_regardless_of_which_side_is_wrapped(self):
        req = self.request(2)
        focus = {**req.context["focus"], "source_position": [1, 1]}
        units = [
            {**c, "source_position": [1, i]} for i, c in enumerate(req.context["candidates"], 1)
        ]

        def wrap(unit):
            return {"members": [unit], "selection_id": unit.get("selection_id", "hidden-focus")}

        ctx = {**req.context, "focus": focus, "candidates": [wrap(c) for c in units]}
        other = {**ctx, "focus": wrap(focus), "candidates": units}
        for phase in ("has_match", "match"):
            body = self.selector().build_request(ctx, phase)
            self.assertEqual(body, self.selector().build_request(other, phase))
            self.assertNotIn("group", json.dumps(body).lower())
            self.assertIn("B1.1 [focus]", body["state"])
            self.assertIn("A1.2 [candidate]", body["state"])

    def test_overlapping_sections_share_only_the_same_source_occurrence(self):
        def section(handle, spans, text):
            return {
                "paper_key": "paper-1",
                "section_id": handle,
                "full_text": text,
                "source_spans": spans,
            }

        parent = section("parent", [(1, 1, 4), (2, 1, 4)], "Same\n\nSame")
        child = section("child", [(2, 1, 4)], "Same")
        focus = {**section("new", [(1, 1, 3)], "New"), "paper_key": "paper-2"}
        state = self.selector().build_request(
            {"scope": {"level": "section"}, "focus": focus, "candidates": [child, parent]}
        )["state"]
        self.assertEqual(state.count("    Same"), 2)
        self.assertIn("A2 [candidate; part of A1]", state)
        self.assertLess(state.index("New"), state.index("Same"))

    def test_full_papers_by_scope_in_both_directions(self):
        ev = Evidence(RoleGraph(None))
        entries = [{"paper_id": k, "title": k, "file": k + ".json"} for k in ("a", "b", "c")]
        manifest = PaperManifest(schema_version=1, max_granularity="section", papers=entries)
        granularity = manifest.max_granularity
        for entry in manifest.papers:
            doc = document()
            for section in doc:
                section["role_statement"] = "Section role."
                for unit in [section, *section["subsections"]]:
                    for paragraph in unit["paragraphs"]:
                        paragraph["text"] = entry.paper_id + " " + paragraph["text"].strip()
                        paragraph["role_statement"] = "Paragraph role."
            doc[0]["subsections"][0]["role_statement"] = "Hidden subsection role."
            path = self.root / entry.file
            write_json(path, doc)
            ev.register(load_paper(path, entry.paper_id, entry.title, granularity))
        for level in ("section", "paragraph"):
            unit = (
                "s0001" if level == "section" else ev.section_lookup["a", "s0001"].paragraphs[0].id
            )
            for src, dst in (("a", "b"), ("b", "a")):
                context = {
                    "scope": {"level": level},
                    "focus": ev.match_unit_context(src, unit, level),
                    "candidates": [ev.match_unit_context(dst, unit, level, selectable=True)],
                }
                context["outline"] = ev.jev_annotations(context, None)
                state = self.selector().build_request(context)["state"]
                focus, remainder = state.removeprefix("Focus\n").split("\n\nContext\n")
                background, options = remainder.split("\n\nCandidates\n")
                self.assertIn(src + " First background paragraph.", focus)
                self.assertIn(dst + " First background paragraph.", options)
                for paper in ("a", "b"):
                    self.assertIn(paper + " First analysis paragraph.", background)
                    for passage in (
                        "First background paragraph.",
                        "First analysis paragraph.",
                        "Subsection evidence.",
                    ):
                        self.assertEqual(state.count(paper + " " + passage), 1)
                self.assertNotIn("c First", state)
                self.assertNotIn("Hidden subsection role.", state)
                if level == "section":
                    self.assertEqual(state.count("Section: "), 4)
                    self.assertNotIn("Detail", state)
                    self.assertNotIn("Paragraph role.", state)
                    self.assertIn("background paragraph. " + src + " Subsection evidence.", focus)
                else:
                    self.assertIn("Paragraph role.", focus)
                    self.assertIn(src + " Subsection evidence.", background)

    def test_focus_first_collocates_role_statements_and_only_lists_offscreen_members_at_end(self):
        req = self.request()
        req.context["focus"]["source_position"] = [1, 1]
        req.context["candidates"][0]["source_position"] = [1, 2]
        req.context["focus"]["next_paragraph"] = {"full_text": "Neighbor."}
        req.context["outline"] = {
            "units": {
                "B1": ("Methods", "Defines the study design."),
                "B1.1": ("", "Introduces recruitment."),
                "B1.2": ("", "Describes the task."),
                "A1.2": ("", "Defines eligibility."),
            },
            "groups": {
                "S1": {
                    "members": {"A1": None, "B1": None},
                    "role_statement": "Describes study methods.",
                },
                "P1": {
                    "members": {"A1.2": "core", "C2.4": "fan_in"},
                    "role_statement": "Explains recruitment.",
                },
                "P2": {
                    "members": {"A9.1": "core", "C4.5": "core"},
                    "role_statement": "Describes evaluation.",
                },
            },
        }
        state = self.selector().build_request(req.context)["state"]
        focus, rest = state.split("\nCandidates\n")
        choices, history = rest.split("\nPrior matches (context only)\n")
        self.assertIn("B1 Methods [in Group S1] | Role: Defines the study design.", focus)
        self.assertIn("B1.1 [focus] | Role: Introduces recruitment.\n    First focus", focus)
        self.assertIn("B1.2 [context only] | Role: Describes the task.\n    Neighbor.", focus)
        self.assertIn("A1.2 [candidate; in Group P1] | Role: Defines eligibility.", choices)
        self.assertEqual(state.count("Describes study methods."), 1)
        self.assertIn("Group P1 also includes C2.4 (fan-in)", history)
        self.assertIn("Group P2: A9.1, C4.5 | Role: Describes evaluation.", history)
        self.assertNotIn("Group S1", history)

    def test_frozen_inputs_without_coordinates_still_put_the_focus_first(self):
        selector = self.selector()
        request = self.request(2)
        original = request.model_copy(deep=True)
        body = selector.build_request(request.context)
        self.assertLess(body["state"].index("First focus"), body["state"].index("Candidates"))
        self.assertEqual(request, original)
        self.assertEqual(set(body["questions"]), {"has_match"})
        rank = selector.build_request(request.context, "match")
        self.assertEqual(body["state"], rank["state"])
        self.assertEqual(set(rank["questions"]), {"match"})
        self.assertNotEqual(
            body["questions"]["has_match"]["instructions"]["example"],
            rank["questions"]["match"]["instructions"]["example"],
        )
        criteria = rank["questions"]["match"]["criteria"]
        self.assertEqual(criteria, {"Option 1": "Option 1", "Option 2": "Option 2"})

    def test_old_verbose_request_cache_is_not_reused_or_modified(self):
        selector = self.selector()
        request = self.request(2)
        compact = selector.build_request(request.context, "match")
        legacy = json.loads(json.dumps(compact))
        legacy["state"] = encode_evidence(
            {
                **request.context,
                "candidates": dict(zip(request.allowed_match_ids, request.context["candidates"])),
            }
        )
        for key, candidate in legacy["state"]["candidates"].items():
            center = candidate.get("paragraph_under_consideration", candidate)
            legacy["questions"]["match"]["criteria"][key] = {
                "evidence": f"`candidates[{json.dumps(key)}]`",
                "role_statement": center.get("role_statement", ""),
                "meaning": "This candidate supports the same source-grounded role as `focus`.",
            }
        self.assertLess(len(encode_request(compact)), len(encode_request(legacy)))
        self.assertNotEqual(compact["state"], legacy["state"])
        selector.cache.mkdir(parents=True)
        path = selector.cache / f"{hashlib.sha256(encode_request(legacy)).hexdigest()}.json"
        saved = json.dumps({"request": legacy, "response": answer(legacy, NO_MATCH)})
        path.write_text(saved, encoding="utf-8")
        with patch.object(selector.client, "choose", side_effect=answer) as client:
            first = selector.select(request)
            second = selector.select(request)
        self.assertFalse(first["calls"][0]["cache_hit"])
        self.assertTrue(second["calls"][0]["cache_hit"])
        self.assertEqual(client.call_count, 2)
        self.assertEqual(client.call_args.args[0], compact)
        self.assertEqual(path.read_text(encoding="utf-8"), saved)

    def test_rank_runs_only_after_positive_gate(self):
        selector = self.selector()
        for probability, expected in (
            (0.0, None),
            (0.5, None),
            (0.51, "candidate-1"),
            (1.0, "candidate-1"),
        ):
            with (
                self.subTest(probability=probability),
                patch.object(
                    selector.client,
                    "choose",
                    side_effect=lambda body: answer(body, "Option 2", probability),
                ) as client,
            ):
                result = selector.select(self.request(2), force=True)
                phases = [next(iter(c.args[0]["questions"])) for c in client.call_args_list]
                self.assertEqual(phases, ["has_match", "match"] if expected else ["has_match"])
                self.assertEqual(result["target_id"], expected)
                self.assertEqual(result["has_match"]["noul"], probability)

    def test_single_candidate_uses_noul_only_and_caches_it(self):
        selector = self.selector()
        with (
            patch("pipeline.providers.jev.load_api_key", return_value="hidden-key"),
            patch(
                "pipeline.providers.jev.urlopen",
                side_effect=lambda req, **kw: io.BytesIO(
                    json.dumps(answer(json.loads(req.data))).encode()
                ),
            ) as network,
        ):
            first = selector.select(self.request())
            second = selector.select(self.request())
            self.assertEqual(first["target_id"], "candidate-0")
            self.assertIsNone(first["choice"])
            self.assertTrue(second["calls"][0]["cache_hit"])
            self.assertEqual(network.call_count, 1)
            body = json.loads(network.call_args.args[0].data)
            self.assertEqual(set(body["questions"]), {"has_match"})

    def test_negative_shards_do_not_rank_and_no_candidate_is_revived(self):
        selector = self.selector()

        def respond(body):
            count = body["state"].count("\nOption ")
            return answer(body, noul=float(count > 255))

        with patch.object(selector.client, "choose", side_effect=respond) as client:
            result = selector.select(self.request(256))
            self.assertIsNone(result["target_id"])
            self.assertEqual(
                [list(c.args[0]["questions"]) for c in client.call_args_list], [["has_match"]] * 3
            )

    def test_failed_rank_reuses_gate_after_restart(self):
        selector = self.selector()
        request = self.request(2)
        gate = selector.build_request(request.context)
        with patch.object(
            selector.client, "choose", side_effect=[answer(gate), RuntimeError("offline")]
        ):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                selector.select(request)
        resumed = self.selector()
        with patch.object(resumed.client, "choose", side_effect=answer) as client:
            result = resumed.select(request)
            self.assertEqual([c["cache_hit"] for c in result["calls"]], [True, False])
            client.assert_called_once_with(resumed.build_request(request.context, "match"))

    def test_paid_gate_is_cached_before_token_overshoot_stops_run(self):
        selector = self.selector(max_input_tokens=50)
        request = self.request(2)
        with (
            patch("pipeline.providers.jev.load_api_key", return_value="offline-key"),
            patch(
                "pipeline.providers.jev.urlopen",
                side_effect=lambda req, **kw: io.BytesIO(
                    json.dumps(answer(json.loads(req.data))).encode()
                ),
            ) as network,
        ):
            with self.assertRaisesRegex(ValueError, "input-token limit exceeded"):
                selector.select(request)
            self.assertEqual(network.call_count, 1)
            result = self.selector(max_input_tokens=200).select(request)
            self.assertEqual(network.call_count, 2)
            self.assertEqual([c["cache_hit"] for c in result["calls"]], [True, False])

    def test_frozen_pool_stops_on_size_error_without_splitting(self):
        selector = self.selector()
        with patch.object(selector.client, "choose", side_effect=JevRequestTooLarge) as client:
            with self.assertRaisesRegex(ValueError, "cannot split candidates"):
                selector.select(self.request(20), allow_splitting=False)
            self.assertEqual(client.call_count, 1)

    def test_noul_response_validates_finite_probability_question_names_and_types(self):
        body = self.selector().build_request(self.request().context)
        for probability in (-0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(probability=probability), self.assertRaises(ValueError):
                validate_response(answer(body, noul=probability), body)
        good = answer(body, noul=0.8)
        self.assertEqual(validate_response(good, body), good)
        with self.assertRaises(ValueError):
            validate_response({**good, "answers": {}}, body)
        with self.assertRaisesRegex(ValueError, "question type"):
            validate_response(good, {**body, "questions": {"has_match": {"type": "choice"}}})

    def test_complete_cache_tracks_jev_prompt_not_budgets(self):
        request = self.request(2)
        provider = self.provider()
        with patch(
            "pipeline.providers.jev.JevClient.choose",
            side_effect=lambda body: answer(body, NO_MATCH),
        ) as client:
            provider.vote(request)
            self.assertTrue(self.provider(max_calls=1000).vote(request).cache_hit)
            provider.jev.instructions += " Changed policy."
            self.assertFalse(provider.vote(request).cache_hit)
            self.assertEqual(client.call_count, 2)

    def test_transport_uses_documented_body_and_never_records_credentials(self):
        selector = self.selector()
        request = self.request()

        def http(req, **kwargs):
            self.assertEqual(req.full_url, "https://api.typesafe.ai/v1/systemone")
            self.assertEqual(req.headers["Authorization"], "Bearer hidden-key")
            self.assertEqual(kwargs["timeout"], 120)
            body = json.loads(req.data)
            self.assertEqual(set(body), {"model", "state", "questions"})
            return io.BytesIO(json.dumps(answer(body)).encode())

        with (
            patch("pipeline.providers.jev.load_api_key", return_value="hidden-key"),
            patch("pipeline.providers.jev.urlopen", side_effect=http) as network,
        ):
            first = selector.select(request)
            second = self.selector().select(request)
            self.assertEqual(first["target_id"], "candidate-0")
            self.assertTrue(second["calls"][0]["cache_hit"])
            self.assertEqual(network.call_count, 1)
        for path in self.root.rglob("*.json"):
            self.assertNotIn("hidden-key", path.read_text(encoding="utf-8"))

    def test_empty_pool_and_abstention(self):
        selector = self.selector()
        with patch.object(
            selector.client, "choose", side_effect=lambda body: answer(body, NO_MATCH)
        ) as client:
            self.assertIsNone(selector.select(self.request(0))["target_id"])
            client.assert_not_called()
            self.assertIsNone(selector.select(self.request())["target_id"])

    def test_oversized_pool_splits_then_reranks_and_preserves_partial_cache(self):
        selector = self.selector()
        with patch.object(selector.client, "choose", side_effect=answer) as client:
            selection = selector.select(self.request(300))
            self.assertEqual(client.call_count, 7)
            bodies = [call.args[0] for call in client.call_args_list]
            self.assertEqual(
                [
                    len(body["questions"]["match"]["criteria"])
                    for body in bodies
                    if "match" in body["questions"]
                ],
                [150, 150, 10],
            )
            self.assertEqual(selection["target_id"], "candidate-0")
            self.assertEqual(len(selection["calls"]), 7)
            selector.select(self.request(300))
            self.assertEqual(client.call_count, 7)
            selector.select(self.request(300), force=True)
            self.assertEqual(client.call_count, 14)

    def test_recursive_splits_do_not_compare_probabilities_across_halves(self):
        selector = self.selector()
        with patch.object(selector.client, "choose", side_effect=answer) as client:
            result = selector.select(self.request(600))
            self.assertEqual(len(result["calls"]), 17)
            self.assertEqual(client.call_count, 17)
            self.assertEqual(result["target_id"], "candidate-0")

    def test_request_above_old_byte_cap_reaches_transport_without_truncation(self):
        selector = self.selector()
        request = self.request()
        source = "Full source evidence. " * 2500
        request.context["focus"]["paragraph_under_consideration"]["full_text"] = source

        def http(req, **kwargs):
            self.assertGreater(len(req.data), 48_228)
            self.assertIn(source, req.data.decode())
            self.assertNotIn("Typesafe-danger-zone-long-context", req.headers)
            return io.BytesIO(json.dumps(answer(json.loads(req.data))).encode())

        with (
            patch("pipeline.providers.jev.load_api_key", return_value="key"),
            patch("pipeline.providers.jev.urlopen", side_effect=http) as network,
        ):
            self.assertEqual(selector.select(request)["target_id"], "candidate-0")
            self.assertEqual(network.call_count, 1)

    def test_provider_context_limit_splits_then_reranks(self):
        selector = self.selector()

        def http(req, **kwargs):
            body = json.loads(req.data)
            if body["state"].count("\nOption ") > 11:
                raise HTTPError(
                    "url",
                    400,
                    "Bad Request",
                    {},
                    io.BytesIO(b'{"detail":{"error_type":"max_tokens_exceeded"}}'),
                )
            return io.BytesIO(json.dumps(answer(body)).encode())

        with (
            patch("pipeline.providers.jev.load_api_key", return_value="key"),
            patch("pipeline.providers.jev.urlopen", side_effect=http) as network,
        ):
            result = selector.select(self.request(20))
            self.assertEqual(network.call_count, 7)
            self.assertEqual(len(result["calls"]), 6)
            self.assertEqual(result["target_id"], "candidate-0")
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (self.root / "jev/responses").glob("*.json")
        ]
        rejected = [record for record in records if record.get("http_status") == 400]
        self.assertEqual(len(rejected), 1)
        self.assertIn("max_tokens_exceeded", rejected[0]["response_text"])

    def test_long_context_retry_resends_a_size_rejection_with_the_header(self):
        selector = self.selector(long_context_retry=True)
        headers = []

        def http(req, **kwargs):
            long_context = req.headers.get("Typesafe-danger-zone-long-context")
            headers.append(long_context)
            body = json.loads(req.data)
            if body["state"].count("\nOption ") > 11 and long_context != "true":
                raise HTTPError(
                    "url", 400, "Bad Request", {},
                    io.BytesIO(b'{"detail":{"error_type":"max_tokens_exceeded"}}'),
                )
            return io.BytesIO(json.dumps(answer(body)).encode())

        with (
            patch("pipeline.providers.jev.load_api_key", return_value="key"),
            patch("pipeline.providers.jev.urlopen", side_effect=http) as network,
        ):
            result = selector.select(self.request(20))
            # Default gate rejected, long-context gate, long-context ranking: no split.
            self.assertEqual(headers, [None, "true", None, "true"])
            self.assertEqual(network.call_count, 4)
            self.assertEqual([c.get("long_context") for c in result["calls"]], [True, True])
            self.assertEqual(result["target_id"], "candidate-0")
            again = selector.select(self.request(20))
            self.assertEqual(network.call_count, 4)
            self.assertTrue(all(c["cache_hit"] and c["long_context"] for c in again["calls"]))
            # Without the setting, the cached rejection still stops before any call.
            plain = self.selector()
            with self.assertRaises(ValueError):
                plain.select(self.request(20), allow_splitting=False)
            self.assertEqual(network.call_count, 4)
        self.assertEqual(selector.settings.result_settings()["long_context_retry"], True)
        self.assertTrue(JevSettings().long_context_retry)  # On by default.
        self.assertNotIn(
            "long_context_retry", JevSettings(long_context_retry=False).result_settings()
        )

    def test_predicted_overflow_goes_straight_to_long_context(self):
        request = self.request()
        source = "Full source evidence. " * 8000  # About 35k estimated tokens.
        request.context["focus"]["paragraph_under_consideration"]["full_text"] = source
        headers = []

        def http(req, **kwargs):
            headers.append(req.headers.get("Typesafe-danger-zone-long-context"))
            return io.BytesIO(json.dumps(answer(json.loads(req.data))).encode())

        with (
            patch("pipeline.providers.jev.load_api_key", return_value="key"),
            patch("pipeline.providers.jev.urlopen", side_effect=http),
        ):
            result = self.selector(long_context_retry=True).select(request)
            self.assertEqual(headers, ["true"])
            self.assertTrue(result["calls"][0]["long_context"])
            # Without the setting the same request goes out with the default window.
            self.selector().select(request, force=True)
            self.assertEqual(headers, ["true", None])

    def test_provider_rejects_single_candidate_without_truncation(self):
        selector = self.selector()
        with patch.object(selector.client, "choose", side_effect=JevRequestTooLarge) as client:
            with self.assertRaisesRegex(ValueError, "no source text was truncated"):
                selector.select(self.request())
            self.assertEqual(client.call_count, 1)

    def test_unshrinkable_context_pool_stops(self):
        selector = self.selector()

        def choose(body):
            if body["state"].count("\nOption ") > 1:
                raise JevRequestTooLarge()
            return answer(body)

        with patch.object(selector.client, "choose", side_effect=choose) as client:
            with self.assertRaisesRegex(ValueError, "no automatic truncation"):
                selector.select(self.request(2))
            self.assertEqual(client.call_count, 3)

    def test_changed_evidence_model_or_policy_cannot_reuse_a_selection(self):
        selector = self.selector()
        request = self.request()
        with patch("pipeline.providers.jev.JevClient.choose", side_effect=answer) as client:
            selector.select(request)
            request.context["focus"]["paper_key"] = "different-source"
            selector.select(request)
            self.selector(model="jev-1.13.0").select(request)
            selector.instructions += " Additional criterion."
            selector.select(request)
            self.assertEqual(client.call_count, 4)

    def test_invalid_responses_are_rejected(self):
        body = {
            "model": "jev-1.14.0",
            "questions": {"match": {"criteria": {"a": "A", NO_MATCH: "None"}}},
        }
        for corruption in (
            "unknown",
            "missing",
            "sum",
            "confidence",
            "model",
            "usage",
        ):
            with self.subTest(corruption=corruption):
                value = answer(body)
                item = value["answers"]["match"]
                if corruption == "unknown":
                    item["choice"] = "unknown"
                elif corruption == "missing":
                    del item["probabilities"][NO_MATCH]
                elif corruption == "sum":
                    item["probabilities"]["a"] = 0.5
                elif corruption == "confidence":
                    item["confidence"] = float("nan")
                elif corruption == "model":
                    value["model"] = "jev-latest"
                elif corruption == "usage":
                    value["usage"]["input_tokens"] = True
                with self.assertRaises(ValueError):
                    validate_response(value, body)

    def test_inconsistent_choice_preserves_raw_response_and_caches_both_phases(self):
        selector = self.selector()
        request = self.request(2)

        def respond(body):
            payload = answer(body, "Option 2")
            if "match" in payload["answers"]:
                payload["answers"]["match"]["probabilities"] = {
                    "Option 1": 0.6,
                    "Option 2": 0.4,
                }
            return payload

        with patch.object(selector.client, "choose", side_effect=respond) as client:
            selector.select(request)
            result = selector.select(request)
        self.assertEqual(client.call_count, 2)
        self.assertTrue(all(c["cache_hit"] for c in result["calls"]))
        self.assertEqual(result["target_id"], "candidate-0")
        ranking = result["calls"][-1]
        self.assertEqual(ranking["response"]["answers"]["match"]["choice"], "Option 2")
        self.assertEqual(ranking["choice_correction"]["effective_choice"], "Option 1")

    def test_probability_choice_ties_are_deterministic(self):
        for reported, expected in (("b", "b"), ("c", "a")):
            for probabilities in ({"b": 0.5, "a": 0.5, "c": 0.0}, {"c": 0.0, "a": 0.5, "b": 0.5}):
                with self.subTest(reported=reported, probabilities=probabilities):
                    self.assertEqual(
                        choice_from_probabilities(
                            {"choice": reported, "probabilities": probabilities}
                        ),
                        expected,
                    )

    def test_probability_rounding_preserves_original_values(self):
        body = {
            "model": "jev-1.14.0",
            "questions": {"match": {"criteria": {"a": "A", NO_MATCH: "None"}}},
        }
        for total in (0.981, 0.99, 1.0, 1.01, 1.02):
            with self.subTest(total=total):
                value = answer(body)
                value["answers"]["match"]["probabilities"] = {"a": 0.6, NO_MATCH: total - 0.6}
                self.assertEqual(validate_response(value, body), value)

    def test_probability_rounding_does_not_accept_invalid_distributions(self):
        body = {
            "model": "jev-1.14.0",
            "questions": {"match": {"criteria": {"a": "A", NO_MATCH: "None"}}},
        }
        for probabilities in (
            {"a": 0.6, NO_MATCH: 0.38},
            {"a": 0.6, NO_MATCH: 0.37},
            {"a": 0.6, NO_MATCH: 0.43},
            {"a": 1.01, NO_MATCH: -0.01},
            {"a": float("inf"), NO_MATCH: 0.0},
            {"a": float("nan"), NO_MATCH: 0.0},
        ):
            with self.subTest(probabilities=probabilities):
                value = answer(body)
                value["answers"]["match"]["probabilities"] = probabilities
                with self.assertRaises(ValueError):
                    validate_response(value, body)

    def test_bad_response_is_saved_but_not_cached(self):
        selector = self.selector()
        with (
            patch("pipeline.providers.jev.load_api_key", return_value="key"),
            patch("pipeline.providers.jev.urlopen", return_value=io.BytesIO(b'{"wrong": true}')),
        ):
            with self.assertRaises(ValueError):
                selector.select(self.request())
        self.assertEqual(len(list((self.root / "jev/responses").glob("*.json"))), 1)
        self.assertEqual(list((self.root / "jev").glob("*.json")), [])

    def test_http_and_connection_errors_do_not_retry_automatically(self):
        for error in (
            HTTPError("url", 429, "rate limit", {}, io.BytesIO(b"")),
            HTTPError("url", 400, "Bad Request", {}, io.BytesIO(b'{"detail":"invalid request"}')),
            HTTPError("url", 400, "Bad Request", {}, io.BytesIO(b"not json")),
            URLError("offline"),
        ):
            with (
                patch("pipeline.providers.jev.load_api_key", return_value="key"),
                patch("pipeline.providers.jev.urlopen", side_effect=error) as network,
            ):
                with self.assertRaises(RuntimeError):
                    self.selector().select(self.request())
                self.assertEqual(network.call_count, 1)

    def test_call_guard_stops_before_request(self):
        client = JevClient(JevSettings(max_calls=1), self.root, self.root)
        client.calls = 1
        body = {"questions": {"match": {"criteria": {"a": "A", "b": "B"}}}}
        with patch("pipeline.providers.jev.urlopen") as network:
            with self.assertRaisesRegex(ValueError, "call limit"):
                client.choose(body)
            network.assert_not_called()

    def test_provider_body_guard_stops_before_request(self):
        client = JevClient(JevSettings(), self.root, self.root)
        body = {"questions": {"match": {"criteria": {"a": "A", "b": "B"}}}}
        with (
            patch("pipeline.providers.jev.MAX_REQUEST_BYTES", 1),
            patch("pipeline.providers.jev.urlopen") as network,
        ):
            with self.assertRaisesRegex(JevRequestTooLarge, "32 MiB"):
                client.choose(body)
            network.assert_not_called()

    def test_only_explicit_provider_size_errors_allow_splitting(self):
        for status, body in (
            (400, b'{"detail":"max_tokens_exceeded"}'),
            (413, b"payload too large"),
        ):
            with (
                self.subTest(status=status),
                patch("pipeline.providers.jev.load_api_key", return_value="key"),
                patch(
                    "pipeline.providers.jev.urlopen",
                    side_effect=HTTPError("url", status, "rejected", {}, io.BytesIO(body)),
                ) as network,
            ):
                # Each status starts without the previous subtest's cached rejection.
                shutil.rmtree(self.root / "jev" / "too-large", ignore_errors=True)
                with self.assertRaisesRegex(ValueError, "no source text was truncated"):
                    self.selector().select(self.request())
                self.assertEqual(network.call_count, 1)
                # The same request is then known to be too large: no second call.
                with self.assertRaisesRegex(ValueError, "no source text was truncated"):
                    self.selector().select(self.request())
                self.assertEqual(network.call_count, 1)

    def test_jev_requires_both_credentials_before_run_creation(self):
        docs = manifest(self.root, ["a", "b"], "source")
        with patch(
            "pipeline.incremental_graph.runs.load_api_key", side_effect=RuntimeError("missing key")
        ):
            with self.assertRaisesRegex(RuntimeError, "missing key"):
                start_graph(docs, self.root / "run", jev=True)
        self.assertFalse((self.root / "run").exists())

    def test_jev_match_has_no_generative_explanation(self):
        provider = self.provider()
        with (
            patch.object(provider.jev.client, "choose") as jev,
            patch("pipeline.incremental_graph.judgments.create_skill_client") as generative,
        ):
            with self.assertRaisesRegex(JudgmentError, "vote"):
                provider.judge(self.request())
            jev.assert_not_called()
            generative.assert_not_called()


if __name__ == "__main__":
    unittest.main()
