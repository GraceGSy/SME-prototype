"""Center quotations are exact, member-bound evidence, never repaired text."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_incremental_graph import CONFIG_PATH
from test_skill_api import _adapter, _Response

from pipeline.incremental_graph.configuration import PromptRepository, load_pipeline_config
from pipeline.incremental_graph.llm import AnthropicJudgmentProvider, JudgmentError
from pipeline.incremental_graph.models import JudgmentRequest
from pipeline.llm.client import SkillBudgetExceeded, SkillRef


def evidence_request():
    return JudgmentRequest(
        key="p2:paragraph_matching:new_to_group:p1",
        paper_index=2,
        stage_id="paragraph_matching",
        output_kind="match",
        prompt_ref="paragraph-to-group-match/v1",
        context_ref="matching",
        skill_ref="match-role",
        allowed_match_ids=["group"],
        context={
            "scope": {"level": "paragraph"},
            "focus": {
                "paragraph_under_consideration": {"full_text": "We deny the appeal."},
                "next_paragraph": {"full_text": "Costs are awarded."},
            },
            "candidates": [
                {
                    "selection_id": "group",
                    "members": [
                        {
                            "paragraph_under_consideration": {
                                "full_text": "We dismiss the petition."
                            },
                            "next_paragraph": {"full_text": "We deny the appeal."},
                        },
                        {
                            "paragraph_under_consideration": {
                                "full_text": "The judgment is affirmed."
                            }
                        },
                    ],
                }
            ],
        },
    )


def evidence_response():
    return {
        "target_id": "group",
        "basis": "Each center announces the court's disposition.",
        "evidence": {
            "focus": ["deny the appeal"],
            "target": ["dismiss the petition", "judgment is affirmed"],
        },
    }


class MatchEvidenceTest(unittest.TestCase):
    def test_legacy_response_without_evidence_is_rejected(self):
        value = evidence_response()
        del value["evidence"]
        with self.assertRaises(JudgmentError):
            AnthropicJudgmentProvider._validate(evidence_request(), value)

    def test_accepts_exact_quotes_in_member_order_in_both_directions(self):
        request, value = evidence_request(), evidence_response()
        AnthropicJudgmentProvider._validate(request, value)
        request.context["focus"], request.context["candidates"][0] = (
            request.context["candidates"][0],
            request.context["focus"],
        )
        request.context["candidates"][0]["selection_id"] = "group"
        value["evidence"]["focus"], value["evidence"]["target"] = (
            value["evidence"]["target"],
            value["evidence"]["focus"],
        )
        AnthropicJudgmentProvider._validate(request, value)

    def test_rejects_neighbor_quotes_missing_members_order_and_normalization(self):
        for side, quotes in [
            ("focus", ["Costs are awarded"]),
            ("target", ["deny the appeal", "judgment is affirmed"]),
            ("target", ["dismiss the petition"]),
            ("target", ["judgment is affirmed", "dismiss the petition"]),
            ("focus", ["deny  the appeal"]),
            ("focus", ["DENY the appeal"]),
            ("focus", [""]),
            ("focus", [123]),
        ]:
            with self.subTest(side=side, quotes=quotes):
                value = evidence_response()
                value["evidence"][side] = quotes
                with self.assertRaises(JudgmentError):
                    AnthropicJudgmentProvider._validate(evidence_request(), value)

    def test_abstention_requires_empty_evidence_and_structure_uses_actual_unit(self):
        value = {
            "target_id": None,
            "basis": "Different roles.",
            "evidence": {"focus": [], "target": []},
        }
        AnthropicJudgmentProvider._validate(evidence_request(), value)
        value["evidence"]["target"] = ["Invented evidence"]
        with self.assertRaises(JudgmentError):
            AnthropicJudgmentProvider._validate(evidence_request(), value)
        request = evidence_request()
        request.context = {
            "scope": {"level": "section"},
            "focus": {"full_text": "We deny the appeal."},
            "candidates": [
                {
                    "group_id": "group",
                    "members": [
                        {"full_text": "We dismiss the petition."},
                        {"full_text": "The judgment is affirmed."},
                    ],
                }
            ],
        }
        AnthropicJudgmentProvider._validate(request, evidence_response())

    def test_count_feedback_identifies_every_required_member_without_repeating_source(self):
        request, value = evidence_request(), evidence_response()
        value["evidence"]["target"] = ["dismiss the petition"]
        before = copy.deepcopy((request.context, value))
        with self.assertRaises(JudgmentError) as caught:
            AnthropicJudgmentProvider._validate(request, value)
        feedback = str(caught.exception)
        for expected in (
            "evidence.target has 1 quotation; expected exactly 2",
            "evidence.focus: 1", "evidence.target: 2",
            "evidence.target[0]", "candidate 'group'.members[0]",
            "evidence.target[1]", "candidate 'group'.members[1]",
        ):
            self.assertIn(expected, feedback)
        self.assertNotIn("We dismiss the petition.", feedback)
        self.assertEqual((request.context, value), before)
        value["evidence"]["target"].append("judgment is affirmed")
        AnthropicJudgmentProvider._validate(request, value)

    def test_misattribution_feedback_names_selected_section_and_actual_quote_location(self):
        request = evidence_request()
        request.allowed_match_ids = ["s0002", "s0004"]
        request.context = {
            "scope": {"level": "section"},
            "focus": {"full_text": "The interface supports comparison."},
            "candidates": [
                {
                    "section_id": "s0002",
                    "section_label": "Introduction",
                    "full_text": "We implemented a writing environment with two support concepts.",
                },
                {
                    "section_id": "s0004",
                    "section_label": "System Design",
                    "full_text": "The editor displays source passages alongside the draft.",
                },
            ],
        }
        value = {
            "target_id": "s0004",
            "basis": "Both describe the proposed interface.",
            "evidence": {
                "focus": ["interface supports comparison"],
                "target": ["a writing environment with two support concepts"],
            },
        }
        before = copy.deepcopy((request.context, value))
        with self.assertRaises(JudgmentError) as caught:
            AnthropicJudgmentProvider._validate(request, value)
        feedback = str(caught.exception)
        for expected in ("evidence.target[0]", "s0004", "System Design", "s0002", "Introduction"):
            self.assertIn(expected, feedback)
        self.assertIn(value["evidence"]["target"][0], feedback)
        self.assertNotIn(request.context["candidates"][1]["full_text"], feedback)
        self.assertEqual((request.context, value), before)
        value["evidence"]["target"] = ["source passages alongside the draft"]
        AnthropicJudgmentProvider._validate(request, value)

    def test_feedback_distinguishes_neighbors_other_members_and_absent_text(self):
        for side, index, quote, location in (
            ("focus", 0, "Costs are awarded", "focus.next_paragraph"),
            ("target", 0, "judgment is affirmed", "members[1]"),
            ("focus", 0, "DENY the appeal", "No exact occurrence"),
        ):
            with self.subTest(quote=quote):
                value = evidence_response()
                value["evidence"][side][index] = quote
                with self.assertRaises(JudgmentError) as caught:
                    AnthropicJudgmentProvider._validate(evidence_request(), value)
                self.assertIn(location, str(caught.exception))
                self.assertIn(quote, str(caught.exception))

    def test_retries_only_failed_judgment_and_caches_only_valid_evidence(self):
        self.check_retry(failures=1, succeeds=True)

    def test_stops_after_three_failed_evidence_responses(self):
        self.check_retry(failures=3, succeeds=False)

    def check_retry(self, failures, succeeds):
        config = load_pipeline_config(CONFIG_PATH)
        bad = evidence_response()
        bad["evidence"]["focus"] = ["Costs are awarded"]
        responses = [
            SimpleNamespace(value=copy.deepcopy(bad), raw_response={"id": str(i)})
            for i in range(failures)
        ]
        responses.append(SimpleNamespace(value=evidence_response(), raw_response={"id": "good"}))
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("pipeline.incremental_graph.llm.ClaudeSkills") as client,
        ):
            client.return_value.register.return_value = SkillRef(
                "match-role", "skill", "v1", "hash"
            )
            client.return_value.run_json.side_effect = responses
            provider = AnthropicJudgmentProvider(
                PromptRepository(config.prompt_root, config.context_root),
                config.model,
                Path(directory),
                config.skill_root,
            )
            request = evidence_request()
            if succeeds:
                result = provider.judge(request)
                self.assertEqual(result.normalized, evidence_response())
                self.assertTrue(provider.judge(request).cache_hit)
            else:
                with self.assertRaises(JudgmentError):
                    provider.judge(request)
                self.assertEqual(list(Path(directory).glob("*.json")), [])
            self.assertEqual(client.return_value.run_json.call_count, failures + int(succeeds))
            self.assertEqual(len(list((Path(directory) / "rejected").glob("*.json"))), failures)
            calls = client.return_value.run_json.call_args_list
            self.assertEqual(
                calls[0].kwargs["cacheable_context"], calls[-1].kwargs["cacheable_context"]
            )
            self.assertIn("Evidence validation failed", calls[1].args[1])
            self.assertIn("Costs are awarded", calls[1].args[1])
            self.assertIn("focus.next_paragraph", calls[1].args[1])
            self.assertIn("Previous rejected response", calls[1].args[1])
            self.assertIn('"target": ["dismiss the petition", "judgment is affirmed"]', calls[1].args[1])
            self.assertEqual(
                calls[0].kwargs["cacheable_prompt"], calls[-1].kwargs["cacheable_prompt"]
            )

    def test_provider_budget_failures_are_not_retried(self):
        config = load_pipeline_config(CONFIG_PATH)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("pipeline.incremental_graph.llm.ClaudeSkills") as client,
        ):
            client.return_value.register.return_value = SkillRef(
                "match-role", "skill", "v1", "hash"
            )
            client.return_value.run_json.side_effect = SkillBudgetExceeded("budget")
            provider = AnthropicJudgmentProvider(
                PromptRepository(config.prompt_root, config.context_root),
                config.model,
                Path(directory),
                config.skill_root,
            )
            with self.assertRaises(SkillBudgetExceeded):
                provider.judge(evidence_request())
            self.assertEqual(client.return_value.run_json.call_count, 1)

    def test_excerpts_require_exact_ordered_endpoints_in_the_same_center(self):
        opening = "The wolf was blowing loudly"
        ending = "And therefore the pigs survived."
        quote = f"{opening} ... {ending}"
        request, value = evidence_request(), evidence_response()
        request.context["focus"]["paragraph_under_consideration"]["full_text"] = (
            f"{opening} while the brick walls held firm. {ending}"
        )
        value["evidence"]["focus"] = [quote]
        before = copy.deepcopy((request.context, value))
        AnthropicJudgmentProvider._validate(request, value)
        self.assertEqual((request.context, value), before)
        for invalid in (
            f"{ending} ... {opening}",  # Reversed source order.
            "The wolf was blowing ... And therefore the pigs survived.",
            quote.replace("wolf", "Wolf"),
            quote.replace("loudly", "loud"),  # Endpoints cannot stop inside a word.
            quote.replace(" ... ", ".... "),
            quote.replace(" ... ", " ... missing words ... "),
            quote.replace("was blowing", "was  blowing"),
        ):
            with self.subTest(quote=invalid), self.assertRaises(JudgmentError):
                value["evidence"]["focus"] = [invalid]
                AnthropicJudgmentProvider._validate(request, value)
        value["evidence"]["focus"] = [quote]
        for location in ("next_paragraph", "other_member"):
            with self.subTest(location=location):
                request.context["focus"] = (
                    {
                        "members": [
                            {"paragraph_under_consideration": {"full_text": opening}},
                            {"paragraph_under_consideration": {"full_text": ending}},
                        ]
                    }
                    if location == "other_member"
                    else {
                        "paragraph_under_consideration": {"full_text": opening},
                        "next_paragraph": {"full_text": ending},
                    }
                )
                value["evidence"]["focus"] = (
                    [quote, ending] if location == "other_member" else [quote]
                )
                with self.assertRaises(JudgmentError):
                    AnthropicJudgmentProvider._validate(request, value)

    def test_excerpt_accepts_punctuation_boundaries_without_changing_source_text(self):
        request, value = evidence_request(), evidence_response()
        opening = "Prior work on visualizing large"
        ending = "afforded by the data source."
        quote = f"{opening} ... {ending}"
        value["evidence"]["focus"] = [quote]
        for boundary in ("\u2014", ",", ":", ";", "(", " "):
            with self.subTest(boundary=boundary):
                request.context["focus"]["paragraph_under_consideration"]["full_text"] = (
                    f'"{opening} collections spans several data types and opportunities{boundary}{ending}'
                )
                before = copy.deepcopy((request.context, value))
                AnthropicJudgmentProvider._validate(request, value)
                self.assertEqual((request.context, value), before)
        for source in (
            f"{opening} opportunitiesun{ending}",  # A suffix inside a word is not an endpoint.
            f"{opening} {ending}",  # Nothing omitted.
            f"{opening} ... {ending.upper()}",  # No case normalization.
        ):
            request.context["focus"]["paragraph_under_consideration"]["full_text"] = source
            with self.subTest(source=source), self.assertRaises(JudgmentError):
                AnthropicJudgmentProvider._validate(request, value)

    def test_transport_length_failure_gets_bounded_feedback_but_other_schema_errors_do_not(self):
        config = load_pipeline_config(CONFIG_PATH)
        long_quote = (
            "These are the opening words "
            + "supporting evidence " * 20
            + "these are the closing words"
        )
        corrected = evidence_response()
        corrected["evidence"]["focus"] = [
            "These are the opening words ... these are the closing words"
        ]
        for failures, extra_error, succeeds in (
            (1, False, True),
            (3, False, False),
            (1, True, False),
        ):
            with self.subTest(failures=failures, extra_error=extra_error):
                bad = copy.deepcopy(corrected)
                bad["evidence"]["focus"] = [long_quote]
                if extra_error:
                    bad["unexpected"] = True
                adapter, messages = _adapter(
                    *[
                        _Response(str(i), "end_turn", 100, 20, text=json.dumps(value))
                        for i, value in enumerate([bad] * failures + [corrected])
                    ]
                )
                with (
                    tempfile.TemporaryDirectory() as directory,
                    patch.object(
                        adapter,
                        "register",
                        return_value=SkillRef("match-role", "skill", "v1", "hash"),
                    ),
                ):
                    provider = AnthropicJudgmentProvider(
                        PromptRepository(config.prompt_root, config.context_root),
                        config.model,
                        Path(directory),
                        config.skill_root,
                    )
                    provider.skills = adapter
                    request = evidence_request()
                    request.context["focus"]["paragraph_under_consideration"]["full_text"] = (
                        long_quote
                    )
                    if succeeds:
                        self.assertEqual(provider.judge(request).normalized, corrected)
                        self.assertTrue(provider.judge(request).cache_hit)
                    else:
                        with self.assertRaises(ValueError if extra_error else JudgmentError):
                            provider.judge(request)
                        self.assertEqual(list(Path(directory).glob("*.json")), [])
                    self.assertEqual(len(messages.calls), failures + int(succeeds))
                    if not extra_error:
                        first = messages.calls[0]["messages"][0]["content"]
                        retry = messages.calls[1]["messages"][0]["content"]
                        self.assertEqual(first[:-1], retry[:-1])
                        feedback = retry[-1]["text"][len(first[-1]["text"]) :]
                        for expected in ("evidence.focus[0]", str(len(long_quote)), "240", "same"):
                            self.assertIn(expected, feedback)
                        self.assertNotIn(long_quote, feedback)
