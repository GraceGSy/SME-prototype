"""From the third paper on, each new unit asks Jev a yes/no question per node."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from test_jev import answer
from test_jev_pipeline import ScriptedSkills

from pipeline.document import ROLE_FIELD
from pipeline.files import read_json, write_json
from pipeline.incremental_graph.close_calls import close_options
from pipeline.incremental_graph.runs import start_graph
from pipeline.viewer.package_catalog import package_catalog

ROLES = {"water supply": "mechanism", "small sample": "limitation", "high price": "cost"}


def section(name, text, role):
    return {
        "section_name": name,
        "section_number": None,
        ROLE_FIELD: role,
        "paragraphs": [{"paragraph_number": 0, "text": text, ROLE_FIELD: role}],
        "subsections": [],
    }


def paper(word, sections):
    return [
        section(name, f"{word} {text}", f"Role of the {name.lower()} section.")
        for name, text in sections
    ]


STANDARD = [
    ("Method", "explains how closing a valve cuts the water supply."),
    ("Limits", "notes that a small sample limits generalization."),
]


def roles(text):
    return {role for phrase, role in ROLES.items() if phrase in text}


class ScriptedJev:
    """Score by shared keyword role; record every request body."""

    def __init__(self, reject_over=None):
        self.bodies = []
        self.reject_over = reject_over  # Reject larger rankings as over Jev's context.

    def __call__(self, request, **kwargs):
        body = json.loads(request.data)
        self.bodies.append(body)
        options = body["questions"].get("match", {}).get("criteria", [])
        if self.reject_over and "Gamma paper" in body["state"] and len(options) > self.reject_over:
            error = b'{"detail":{"error_type":"max_tokens_exceeded"}}'
            raise HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(error))
        texts, block, key = {}, None, None
        for line in body["state"].splitlines():
            if line in {"Focus", "Context", "Candidates"}:
                block, key = line, None
            elif line.startswith("Section: ") and block != "Context":
                key = "focus" if block == "Focus" else line.split()[1]
                if "(member of " in line:
                    key = line.split("(member of ", 1)[1].rstrip(")")
                texts.setdefault(key, "")
            elif key and line.startswith("Content: "):
                texts[key] += " " + line
        focus = roles(texts.pop("focus"))
        matching = [k for k, text in texts.items() if roles(text) & focus]
        noul = 0.9 if matching else 0.1
        return io.BytesIO(
            json.dumps(answer(body, matching[0] if matching else None, noul)).encode()
        )


class CloseJev(ScriptedJev):
    """Give third-paper rankings fixed shares by option count, in criteria order."""

    def __init__(self, shares, reject_over=None):
        super().__init__(reject_over=reject_over)
        self.shares = shares
        self.first_ranking = None

    def __call__(self, request, **kwargs):
        body = json.loads(request.data)
        options = list(body["questions"].get("match", {}).get("criteria", []))
        fits = not self.reject_over or len(options) <= self.reject_over
        if "Gamma paper" not in body["state"] or not options or not fits:
            return super().__call__(request, **kwargs)
        self.bodies.append(body)
        self.first_ranking = self.first_ranking or options
        probabilities = dict(zip(options, self.shares[len(options)], strict=True))
        n = len(options)
        top = max(probabilities.values())
        response = answer(body, options[0])
        response["answers"]["match"].update(
            probabilities=probabilities, confidence=round((top - 1 / n) / (1 - 1 / n), 4)
        )
        return io.BytesIO(json.dumps(response).encode())


class RecordingSkills(ScriptedSkills):
    def __init__(self):
        super().__init__()
        self.users = []

    def run_json(self, skills, user, schema, **kwargs):
        self.users.append(user)
        return super().run_json(skills, user, schema, **kwargs)


class PairwiseNodeMatchingTest(unittest.TestCase):
    def run_three(
        self,
        third_sections,
        beta_sections=STANDARD,
        alpha_sections=STANDARD,
        jev=None,
        section_fan_in=False,
        close_call_margin=None,
        sections_only=True,
    ):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        docs = {
            "alpha": paper("Alpha", alpha_sections),
            "beta": paper("Beta", beta_sections),
            "gamma": paper("Gamma", third_sections),
        }
        for name, doc in docs.items():
            write_json(root / f"{name}.json", doc)
        write_json(
            root / "manifest.yaml",
            {
                "schema_version": 1,
                "max_granularity": "section",
                "papers": [
                    {"paper_id": n, "title": n.title() + " paper", "file": n + ".json"}
                    for n in docs
                ],
            },
        )
        jev, skills = jev or ScriptedJev(), RecordingSkills()
        with (
            patch("pipeline.incremental_graph.runs.load_api_key", return_value="offline-key"),
            patch("pipeline.providers.jev.load_api_key", return_value="offline-key"),
            patch("pipeline.providers.jev.urlopen", side_effect=jev),
            patch("pipeline.incremental_graph.judgments.create_skill_client", return_value=skills),
        ):
            result = start_graph(
                root / "manifest.yaml",
                root / "run",
                jev=True,
                sections_only=sections_only,
                section_fan_in=section_fan_in,
                close_call_margin=close_call_margin,
            )
        # A section checkpoint reports its revision; a full run reports its dataset.
        revision = Path(result.get("revision_dir") or Path(result["dataset_dir"]).parent)
        return jev, skills, revision

    THREE = [*STANDARD, ("Cost", "warns that a high price slows adoption.")]
    ALL = [("All", "ties the water supply, a small sample, and a high price together.")]

    @staticmethod
    def rankings(jev):
        return [
            len(b["questions"]["match"]["criteria"])
            for b in jev.bodies
            if "Gamma paper" in b["state"] and "match" in b["questions"]
        ]

    @staticmethod
    def gamma_group_size(revision):
        groups = read_json(revision / "section-checkpoint.json")["section_groups"].values()
        return next(
            len(g["members"]) for g in groups if any(m["paper_id"] == "gamma" for m in g["members"])
        )

    def test_close_ranking_is_reasked_among_the_close_options(self):
        # 0.40 vs 0.35 is close; 0.25 is not. The two-way re-ask is decisive.
        jev = CloseJev({3: [0.40, 0.35, 0.25], 2: [0.80, 0.20]})
        _, _, revision = self.run_three(
            self.ALL, self.THREE, self.THREE, jev=jev, close_call_margin=0.10
        )
        self.assertEqual(self.rankings(jev), [3, 2])
        reask = jev.bodies[-1]["questions"]["match"]["criteria"]
        self.assertEqual(list(reask), list(jev.first_ranking)[:2])  # The far option is dropped.
        [call] = [e for e in read_json(revision / "events.json") if e["action"] == "close_call"]
        self.assertEqual(call["outcome"], "resolved")
        self.assertEqual(len(call["first"]["close_ids"]), 2)
        self.assertEqual(len(call["reask"]["close_ids"]), 1)
        self.assertEqual(call["target_id"], call["reask"]["close_ids"][0])
        self.assertEqual(self.gamma_group_size(revision), 3)
        report = read_json(revision / "reports/close-calls.json")
        self.assertEqual((report["reasked"], report["resolved_by_reask"], report["held"]), (1, 1, 0))

    def test_still_close_after_reask_leaves_the_section_alone_and_reports_it(self):
        jev = CloseJev({3: [0.40, 0.35, 0.25], 2: [0.52, 0.48]})
        _, _, revision = self.run_three(
            self.ALL, self.THREE, self.THREE, jev=jev, close_call_margin=0.10
        )
        calls = [e for e in read_json(revision / "events.json") if e["action"] == "close_call"]
        # Insertion holds it; singleton recovery asks again and holds it again.
        self.assertEqual(
            [(c["direction"], c["outcome"]) for c in calls],
            [("new_to_group", "held"), ("singleton_to_group", "held")],
        )
        self.assertIsNone(calls[0]["target_id"])
        self.assertEqual((calls[0]["paper_id"], calls[0]["unit_id"]), ("gamma", "s0001"))
        self.assertEqual(self.gamma_group_size(revision), 1)
        report = read_json(revision / "reports/close-calls.json")
        self.assertEqual((report["held"], report["held_still_alone"]), (2, 2))
        self.assertTrue(report["calls"][0]["final"]["still_alone"])

    def test_two_way_close_ranking_is_held_without_a_repeat_question(self):
        jev = CloseJev({2: [0.52, 0.48]})
        _, _, revision = self.run_three(
            [("Both", "covers the water supply and a small sample in one section.")],
            jev=jev,
            close_call_margin=0.10,
        )
        # Singleton recovery repeats the identical ranking, answered from the cache.
        self.assertEqual(self.rankings(jev), [2])
        calls = [e for e in read_json(revision / "events.json") if e["action"] == "close_call"]
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("reask" not in c and c["outcome"] == "held" for c in calls))
        self.assertEqual(self.gamma_group_size(revision), 1)

    def test_close_options_use_a_strict_margin(self):
        self.assertEqual(close_options({"a": 0.55, "b": 0.45}, 0.10), ["a"])
        self.assertEqual(close_options({"a": 0.5, "b": 0.41, "c": 0.09}, 0.10), ["a", "b"])
        self.assertEqual(close_options({"a": 0.34, "b": 0.33, "c": 0.33}, 0.10), ["a", "b", "c"])

    def test_close_rankings_are_ignored_without_a_margin(self):
        jev = CloseJev({2: [0.52, 0.48]})
        _, _, revision = self.run_three(
            [("Both", "covers the water supply and a small sample in one section.")], jev=jev
        )
        self.assertEqual(self.rankings(jev), [2])
        events = read_json(revision / "events.json")
        self.assertFalse(any(e["action"] == "close_call" for e in events))
        self.assertFalse((revision / "reports/close-calls.json").exists())
        self.assertEqual(self.gamma_group_size(revision), 3)

    def test_a_close_half_of_a_split_ranking_still_sends_its_winner_on(self):
        jev = CloseJev({2: [0.52, 0.48]}, reject_over=2)
        _, _, revision = self.run_three(
            self.ALL, self.THREE, self.THREE, jev=jev, close_call_margin=0.10
        )
        # Three-way rejected in both windows, the two-option half (close but not held),
        # then the final (held). Singleton recovery repeats them from the cache.
        self.assertEqual(self.rankings(jev), [3, 3, 2, 2])
        calls = [e for e in read_json(revision / "events.json") if e["action"] == "close_call"]
        self.assertEqual([c["outcome"] for c in calls], ["held", "held"])

    def test_third_paper_scores_each_node_with_two_complete_papers(self):
        jev, skills, revision = self.run_three(
            [
                ("Method", "describes how a blocked water supply stops the pump."),
                ("Limits", "reports that its small sample prevents broad claims."),
            ]
        )
        third = [b for b in jev.bodies if "Gamma paper" in b["state"]]
        # Two new sections times two nodes; no node competes with another node.
        self.assertEqual(len(third), 4)
        self.assertTrue(all(list(b["questions"]) == ["has_match"] for b in third))
        for body in third:
            state = body["state"]
            candidates = state.split("\nCandidates\n", 1)[1]
            self.assertEqual(candidates.count("Group "), 3)  # Role line plus two members.
            self.assertIn("Role: ", candidates.splitlines()[0])
            # Latest member paper (Beta) is complete; Alpha keeps only its member section.
            self.assertEqual(state.count("Beta paper"), 2)
            self.assertEqual(state.count("Alpha paper"), 1)
            self.assertEqual(state.count("Gamma paper"), 2)

        events = read_json(revision / "events.json")
        self.assertEqual(sum(e["action"] == "pair_scored" for e in events), 4)
        groups = read_json(revision / "section-checkpoint.json")["section_groups"].values()
        self.assertEqual(sorted(len(g["members"]) for g in groups), [3, 3])

        group_roles = [json.loads(u) for u in skills.users if '"latest_paper"' in u]
        latest = [c["latest_paper"] for c in group_roles if len(c["group"]["members"]) == 3]
        self.assertEqual(len(latest), 2)
        for paper_context in latest:
            self.assertEqual(paper_context["title"], "Gamma paper")
            member = [s for s in paper_context["sections"] if s.get("group_member")]
            self.assertEqual(len(member), 1)
            self.assertNotIn("Alpha", json.dumps(paper_context))

    def test_two_passing_nodes_go_to_one_ranking_question(self):
        jev, _, revision = self.run_three(
            [("Both", "covers the water supply and a small sample in one section.")]
        )
        third = [b for b in jev.bodies if "Gamma paper" in b["state"]]
        self.assertEqual([list(b["questions"]) for b in third], [["has_match"]] * 2 + [["match"]])
        ranking = third[-1]["state"].split("\nCandidates\n", 1)[1]
        self.assertEqual(ranking.count(" Role: "), 2)  # Both passing nodes with their roles.
        self.assertEqual(ranking.count("Beta paper"), 2)
        recorded = [
            e
            for e in read_json(revision / "events.json")
            if e["action"] == "match_recorded" and e["paper_index"] == 3
        ]
        forward = next(e for e in recorded if e["direction"] == "new_to_group")
        self.assertEqual(len(forward["choice_ids"]), 2)
        groups = read_json(revision / "section-checkpoint.json")["section_groups"].values()
        self.assertEqual(sorted(len(g["members"]) for g in groups), [2, 3])

    def test_ranking_shows_only_the_focus_paper_in_full(self):
        jev, _, _ = self.run_three(
            [
                ("Both", "covers the water supply and a small sample in one section."),
                ("Intro", "opens the paper."),
            ],
            beta_sections=[*STANDARD, ("Notes", "thanks the funders.")],
        )
        third = [b for b in jev.bodies if "Gamma paper" in b["state"]]
        gates = [b["state"] for b in third if list(b["questions"]) == ["has_match"]]
        [ranking] = [b["state"] for b in third if list(b["questions"]) == ["match"]]
        # Yes/no questions carry the node's latest paper; the ranking does not.
        self.assertTrue(any("Beta thanks the funders." in state for state in gates))
        self.assertNotIn("Beta thanks the funders.", ranking)
        before, candidates = ranking.split("\nCandidates\n")
        self.assertIn("Gamma opens the paper.", before)  # The focus paper stays complete.
        self.assertEqual(candidates.count("(member of Group "), 4)

    def test_oversized_ranking_is_split_in_half_then_ranked_again(self):
        sections = [*STANDARD, ("Cost", "warns that a high price slows adoption.")]
        jev = ScriptedJev(reject_over=2)
        _, _, revision = self.run_three(
            [("All", "ties the water supply, a small sample, and a high price together.")],
            beta_sections=sections,
            alpha_sections=sections,
            jev=jev,
        )
        third = [b for b in jev.bodies if "Gamma paper" in b["state"]]
        rankings = [
            len(b["questions"]["match"]["criteria"]) for b in third if "match" in b["questions"]
        ]
        # The three-way ranking rejected in the default and long-context windows, one half
        # of two, then the final of two.
        self.assertEqual(rankings, [3, 3, 2, 2])
        forward = next(
            e
            for e in read_json(revision / "events.json")
            if e["action"] == "match_recorded"
            and e["paper_index"] == 3
            and e["direction"] == "new_to_group"
        )
        self.assertEqual(len(forward["choice_ids"]), 3)
        self.assertIsNotNone(forward["target_id"])
        # A new run from this cache replays the size rejection without another call.
        run = revision.parents[1]
        replay = ScriptedJev(reject_over=2)
        with (
            patch("pipeline.incremental_graph.runs.load_api_key", return_value="offline-key"),
            patch("pipeline.providers.jev.load_api_key", return_value="offline-key"),
            patch("pipeline.providers.jev.urlopen", side_effect=replay),
            patch(
                "pipeline.incremental_graph.judgments.create_skill_client",
                return_value=RecordingSkills(),
            ),
        ):
            again = start_graph(
                run.parent / "manifest.yaml",
                run.parent / "again",
                jev=True,
                sections_only=True,
                cache_from=run,
            )
        self.assertEqual(replay.bodies, [])
        self.assertEqual(
            read_json(Path(again["revision_dir"]) / "section-checkpoint.json")["section_groups"],
            read_json(revision / "section-checkpoint.json")["section_groups"],
        )

    class TightJev(ScriptedJev):
        """Reject third-paper yes/no questions that show Beta complete, as over 32k."""

        def __init__(self, long_context_fits):
            super().__init__()
            self.long_context_fits = long_context_fits
            self.long_context = []

        def __call__(self, request, **kwargs):
            body = json.loads(request.data)
            # Beta's Notes and Method appear together only when Beta is shown complete.
            gate = list(body["questions"]) == ["has_match"]
            full_beta = "Beta thanks" in body["state"] and "Beta explains" in body["state"]
            long = request.get_header("Typesafe-danger-zone-long-context") == "true"
            if gate and "Gamma paper" in body["state"] and full_beta:
                self.long_context.append(long)
                if not (long and self.long_context_fits):
                    self.bodies.append(body)
                    error = b'{"detail":{"error_type":"max_tokens_exceeded"}}'
                    raise HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(error))
            return super().__call__(request, **kwargs)

    BETA_WITH_NOTES = [*STANDARD, ("Notes", "thanks the funders.")]

    def test_oversized_yes_no_is_resent_with_long_context_and_keeps_both_papers(self):
        jev = self.TightJev(long_context_fits=True)
        _, _, revision = self.run_three(STANDARD, beta_sections=self.BETA_WITH_NOTES, jev=jev)
        # Two Gamma sections times three nodes (two shared, Beta's Notes singleton):
        # each is rejected once, then answered in the long-context window.
        self.assertEqual(jev.long_context.count(False), 6)
        self.assertEqual(jev.long_context.count(True), 6)
        gates = [
            b["state"]
            for b in jev.bodies
            if "Gamma paper" in b["state"] and list(b["questions"]) == ["has_match"]
        ]
        # Every third-paper yes/no question that reached Jev showed Beta complete.
        self.assertTrue(gates and all("Beta thanks" in s and "Beta explains" in s for s in gates))
        events = read_json(revision / "events.json")
        self.assertFalse(any(e["action"] == "pair_context_reduced" for e in events))
        groups = read_json(revision / "section-checkpoint.json")["section_groups"].values()
        self.assertEqual(sorted(len(g["members"]) for g in groups if len(g["members"]) > 1), [3, 3])

    def test_yes_no_too_large_even_for_long_context_stops_instead_of_dropping_text(self):
        jev = self.TightJev(long_context_fits=False)
        with self.assertRaisesRegex(Exception, "complete participating papers"):
            self.run_three(STANDARD, beta_sections=self.BETA_WITH_NOTES, jev=jev)
        self.assertEqual(jev.long_context, [False, True])  # One question, then stop.
        # No smaller version of the question was ever sent.
        gates = [b for b in jev.bodies if "Gamma paper" in b["state"]]
        self.assertTrue(all("Beta thanks" in b["state"] for b in gates))

    def test_section_fan_in_admits_a_one_way_neighbor_only_when_enabled(self):
        beta = [
            ("Method", "explains how closing a valve cuts the water supply."),
            ("Pump", "adds that a dry pump also cuts the water supply."),
            ("Limits", "notes that a small sample limits generalization."),
        ]
        for enabled in (False, True):
            with self.subTest(section_fan_in=enabled):
                _, _, revision = self.run_three(STANDARD, beta_sections=beta, section_fan_in=enabled)
                groups = read_json(revision / "section-checkpoint.json")["section_groups"]
                method = next(
                    g for g in groups.values() if {"beta", "alpha"} <= {m["paper_id"] for m in g["members"]}
                    and any(m["unit_id"] == "s0001" and m["paper_id"] == "beta" for m in g["members"])
                )
                beta_members = {
                    m["unit_id"]: m.get("membership_role")
                    for m in method["members"]
                    if m["paper_id"] == "beta"
                }
                fan_in_events = [
                    e
                    for e in read_json(revision / "events.json")
                    if e["action"] == "section_fan_in_added"
                ]
                if enabled:
                    # The second water-supply section sits beside the reciprocal core.
                    self.assertEqual(beta_members, {"s0001": "core", "s0002": "fan_in"})
                    self.assertEqual(len(fan_in_events), 1)
                    self.assertEqual(fan_in_events[0]["reciprocal_unit_id"], "s0001")
                else:
                    self.assertEqual(beta_members, {"s0001": None})
                    self.assertEqual(fan_in_events, [])

    def test_paragraphs_match_once_per_section_group_when_fan_in_shares_it(self):
        # Beta's Method and Pump share one section group (core plus fan-in). Their
        # paragraphs must be matched as one batch: two batches over the same paragraph
        # nodes let one node be merged away by the first and then targeted by the second.
        beta = [
            ("Method", "explains how closing a valve cuts the water supply."),
            ("Pump", "adds that a dry pump also cuts the water supply."),
            ("Limits", "notes that a small sample limits generalization."),
        ]
        class AgreeableJev(ScriptedJev):
            """Sections by shared keyword; every paragraph question: yes, first option."""

            def __call__(self, request, **kwargs):
                body = json.loads(request.data)
                if "[focus]" not in body["state"]:
                    return super().__call__(request, **kwargs)
                self.bodies.append(body)
                return io.BytesIO(json.dumps(answer(body, None, 0.9)).encode())

        _, _, revision = self.run_three(
            STANDARD,
            beta_sections=beta,
            section_fan_in=True,
            sections_only=False,
            jev=AgreeableJev(),
        )
        groups = read_json(revision / "dataset/final_snapshot.json")
        placed = [
            (m["paper"], m["unit_id"])
            for g in groups["groups"] + groups["singletons"]
            for m in g["members"]
        ]
        beta_paragraphs = [u for p, u in placed if p == "beta"]
        self.assertEqual(sorted(beta_paragraphs), ["s0001.p0001", "s0002.p0001", "s0003.p0001"])
        self.assertEqual(len(placed), len(set(placed)))
        # Alpha's Method paragraph node takes one Beta paragraph back, not one per section.
        alpha_method = next(
            g
            for g in groups["groups"]
            if any(m["paper"] == "alpha" and m["unit_id"] == "s0001.p0001" for m in g["members"])
        )
        self.assertEqual(sum(m["paper"] == "beta" for m in alpha_method["members"]), 1)
        stage = read_json(revision / "stages/0002-paragraph_matching.json")
        self.assertEqual(
            sorted(entry["section_ids"] for entry in stage.values()), [["s0001", "s0002"], ["s0003"]]
        )

    def test_section_absorbed_by_reverse_fan_in_brings_its_paragraphs(self):
        # Alpha's Pump group picks Beta's Method, which is reciprocal with Alpha's Method;
        # Pump sits next to that core, so it is absorbed while Beta is reconciled. Its
        # paragraph node must move under the destination and be matched there again.
        alpha = [
            ("Method", "explains how closing a valve cuts the water supply."),
            ("Pump", "adds that a dry pump also cuts the water supply."),
            ("Limits", "notes that a small sample limits generalization."),
        ]

        class AgreeableJev(ScriptedJev):
            def __call__(self, request, **kwargs):
                body = json.loads(request.data)
                if "[focus]" not in body["state"]:
                    return super().__call__(request, **kwargs)
                self.bodies.append(body)
                return io.BytesIO(json.dumps(answer(body, None, 0.9)).encode())

        _, _, revision = self.run_three(
            STANDARD,
            alpha_sections=alpha,
            section_fan_in=True,
            sections_only=False,
            jev=AgreeableJev(),
        )
        events = read_json(revision / "events.json")
        [absorbed] = [
            e
            for e in events
            if e["action"] == "section_fan_in_added" and e["direction"] == "group_to_new"
        ]
        self.assertEqual((absorbed["paper_id"], absorbed["unit_id"]), ("alpha", "s0002"))
        recursion = read_json(revision / "stages/0002-recursive_paragraph_matching.json")
        self.assertEqual(
            [(r["paper_id"], r["section_ids"], r["parent_id"]) for r in recursion],
            [("alpha", ["s0002"], absorbed["node_id"])],
        )
        reparented = [
            e for e in events if e["action"] == "node_reparented" and e["parent_id"] == absorbed["node_id"]
        ]
        self.assertEqual(len(reparented), 1)  # Alpha's Pump paragraph node.
        snapshot = read_json(revision / "dataset/final_snapshot.json")
        pump = next(
            g
            for g in snapshot["groups"] + snapshot["singletons"]
            if any(m["paper"] == "alpha" and m["unit_id"] == "s0002.p0001" for m in g["members"])
        )
        self.assertEqual(pump["parent_group_id"], absorbed["node_id"])

    def test_public_catalog_keeps_source_text_only_for_approved_collections(self):
        _, _, revision = self.run_three(STANDARD)
        run = revision.parents[1]
        for label, keeps_text in (("HCI | Section test", True), ("Legal | Section test", False)):
            with self.subTest(label=label):
                site = run.parent / ("site-" + label.split()[0])
                [entry] = package_catalog(run.parent, site, {run.name: label})
                self.assertEqual(entry["sectionRevisions"], [revision.name])
                self.assertIn("sections only", entry["revisionLabels"][revision.name])
                self.assertEqual(
                    entry.get("sourceTextRevisions", []), [revision.name] if keeps_text else []
                )
                published = site / "public/runs" / run.name / revision.name / "section-map.json"
                section_map = read_json(published)
                self.assertEqual(len(section_map["papers"]), 3)
                text = published.read_text(encoding="utf-8")
                self.assertEqual("water supply" in text, keeps_text)
                self.assertEqual(
                    "Source text is not included in this results viewer." in text, not keeps_text
                )
                self.assertEqual(sorted(len(g["members"]) for g in section_map["groups"]), [3, 3])


if __name__ == "__main__":
    unittest.main()
