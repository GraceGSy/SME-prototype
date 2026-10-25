"""Single-paragraph structural matches require no paragraph matching model calls."""

import json
import tempfile
import unittest
from pathlib import Path

from test_incremental_graph import CANONICAL_MANIFEST, CONFIG_PATH, ScriptedJudge

from pipeline.incremental_graph.configuration import load_pipeline_config
from pipeline.incremental_graph.graph import graph_from_events, stable_id
from pipeline.incremental_graph.input_data import load_manifest
from pipeline.incremental_graph.match_evidence import validate_evidence
from pipeline.incremental_graph.models import Paper, Paragraph, Section
from pipeline.incremental_graph.runner import IncrementalGraphRunner
from pipeline.viewer.package import validate_dataset


def single_unit_paper(paper_id, count=1, subsection=False):
    paragraphs = [
        Paragraph(
            id=f"p{i}",
            text=f"{paper_id} funding paragraph {i}. " * 20,
            question="Who funded it?",
            ordinal=i,
        )
        for i in range(1, count + 1)
    ]
    unit = Section(
        id="s",
        text="\n\n".join(p.text for p in paragraphs),
        paragraphs=paragraphs,
        question="Who funded it?",
        kind="subsection" if subsection else "section",
        parent_id="root" if subsection else None,
    )
    sections = (
        [
            Section(
                id="root", text="Parent framing. " + unit.text, question="What is the context?"
            ),
            unit,
        ]
        if subsection
        else [unit]
    )
    return Paper(paper_id=paper_id, title=paper_id, sections=sections)


class SingleParagraphInheritanceTest(unittest.TestCase):
    def run_papers(self, papers, matches=None, granularity="section"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        parent = stable_id("section-group", "root", "a", "s")
        if matches is None:
            matches = {
                key: value
                for paper in papers[1:]
                for key, value in (
                    (f"{paper.paper_id}:section_matching:new_to_group:s", parent),
                    (f"{paper.paper_id}:section_matching:group_to_new:{parent}", "s"),
                )
            }
        judge = ScriptedJudge(matches)
        runner = IncrementalGraphRunner(
            load_pipeline_config(CONFIG_PATH),
            judge,
            Path(directory.name) / "revision",
            max_granularity=granularity,
        )
        runner.run(papers)
        return runner, judge

    def paragraph_requests(self, judge):
        return [
            r
            for r in judge.requests
            if r.output_kind == "match" and r.context["scope"]["level"] == "paragraph"
        ]

    def test_inherits_sections_and_subsections_with_auditable_evidence_and_export(self):
        for subsection in (False, True):
            with self.subTest(subsection=subsection):
                runner, judge = self.run_papers(
                    [
                        single_unit_paper("a", subsection=subsection),
                        single_unit_paper("b", subsection=subsection),
                    ],
                    granularity="subsection" if subsection else "section",
                )
                self.assertEqual(self.paragraph_requests(judge), [])
                groups = list(runner.question_graph.nodes("paragraph"))
                self.assertEqual(len(groups), 1)
                self.assertEqual(len(groups[0][1]["members"]), 2)
                attempts = [
                    json.loads(line)
                    for line in runner.journal.attempt_path.read_text(encoding="utf-8").splitlines()
                ]
                inherited = [a for a in attempts if a["model"].get("provider") == "deterministic"]
                self.assertEqual(len(inherited), 2)
                for attempt in inherited:
                    value = attempt["normalized"]
                    validate_evidence(
                        json.loads(attempt["rendered_user"]), value["target_id"], value["evidence"]
                    )
                    self.assertEqual(
                        attempt["raw_response"]["rule"], "single_paragraph_structural_match"
                    )
                    self.assertTrue(
                        all(len(q) == 240 for quotes in value["evidence"].values() for q in quotes)
                    )
                self.assertTrue(
                    validate_dataset(runner.revision_dir / "dataset", "inherited", "Inherited")
                )
                replayed = graph_from_events(runner.journal.events)
                self.assertEqual(set(replayed.nodes), set(runner.question_graph.graph.nodes))
                for node_id in replayed.nodes:
                    self.assertEqual(
                        replayed.nodes[node_id]["members"], runner.question_graph.members(node_id)
                    )
                self.assertEqual(
                    set(replayed.edges(keys=True)),
                    set(runner.question_graph.graph.edges(keys=True)),
                )

    def test_extends_an_existing_multi_paper_single_paragraph_group(self):
        runner, judge = self.run_papers([single_unit_paper(p) for p in ("a", "b", "c")])
        self.assertEqual(self.paragraph_requests(judge), [])
        groups = list(runner.question_graph.nodes("paragraph"))
        self.assertEqual(len(groups), 1)
        self.assertEqual({m["paper_id"] for m in groups[0][1]["members"]}, {"a", "b", "c"})

    def test_either_side_with_multiple_paragraphs_still_uses_matching(self):
        for first, second in ((1, 2), (2, 1), (2, 2)):
            with self.subTest(first=first, second=second):
                _, judge = self.run_papers(
                    [single_unit_paper("a", first), single_unit_paper("b", second)]
                )
                self.assertEqual(len(self.paragraph_requests(judge)), first + second)

    def test_section_with_descendant_text_is_not_a_single_paragraph_unit(self):
        first, second = single_unit_paper("a"), single_unit_paper("b")
        first.sections[0].text += "\n\nAdditional subsection evidence."
        _, judge = self.run_papers([first, second])
        self.assertEqual(len(self.paragraph_requests(judge)), 2)

    def test_one_candidate_group_with_multi_paragraph_sources_still_uses_matching(self):
        parent = stable_id("section-group", "root", "a", "s")
        first = stable_id("paragraph-group", parent, "a", "p1")
        neighbor = stable_id("paragraph-group", parent, "a", "p2")
        matches = {
            "b:section_matching:new_to_group:s": parent,
            f"b:section_matching:group_to_new:{parent}": "s",
            "c:section_matching:new_to_group:s": parent,
            f"c:section_matching:group_to_new:{parent}": "s",
            "b:paragraph_matching:new_to_group:p1": first,
            f"b:paragraph_matching:group_to_new:{first}": "p1",
            f"b:paragraph_matching:group_to_new:{neighbor}": "p1",
        }
        runner, judge = self.run_papers(
            [single_unit_paper("a", 2), single_unit_paper("b"), single_unit_paper("c")], matches
        )
        requests = [
            r
            for r in self.paragraph_requests(judge)
            if r.key.startswith("c:") and r.stage_id == "paragraph_matching"
        ]
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(len(r.allowed_match_ids) == 1 for r in requests))
        self.assertEqual(len(list(runner.question_graph.nodes("paragraph"))), 2)

    def test_canonical_hci_funding_sections_inherit_without_paragraph_judgment(self):
        _, papers = load_manifest(CANONICAL_MANIFEST)
        papers = papers[:2]
        self.assertEqual([p.paper_id for p in papers], ["abstractexplorer", "corpusstudio"])
        for paper in papers:
            paper.sections = [s for s in paper.sections if s.label == "Acknowledgments"]
            self.assertEqual(len(paper.sections), 1)
            self.assertEqual(len(paper.sections[0].paragraphs), 1)
        first, second = papers
        parent = stable_id("section-group", "root", first.paper_id, first.sections[0].id)
        unit_id = second.sections[0].id
        matches = {
            f"{second.paper_id}:section_matching:new_to_group:{unit_id}": parent,
            f"{second.paper_id}:section_matching:group_to_new:{parent}": unit_id,
        }
        runner, judge = self.run_papers(papers, matches, granularity="subsection")
        self.assertEqual(self.paragraph_requests(judge), [])
        groups = list(runner.question_graph.nodes("paragraph"))
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            {m["paper_id"] for m in groups[0][1]["members"]}, {p.paper_id for p in papers}
        )

    def test_paragraph_only_corpus_root_does_not_imply_a_match(self):
        runner, judge = self.run_papers(
            [single_unit_paper("a"), single_unit_paper("b")], granularity="paragraph"
        )
        self.assertEqual(len(self.paragraph_requests(judge)), 2)
        self.assertEqual(len(list(runner.question_graph.nodes("paragraph"))), 2)

    def test_unmatched_sections_do_not_inherit_a_paragraph_match(self):
        runner, judge = self.run_papers(
            [single_unit_paper("a"), single_unit_paper("b")], matches={}
        )
        self.assertEqual(self.paragraph_requests(judge), [])
        self.assertEqual(len(list(runner.question_graph.nodes("paragraph"))), 2)

    def test_structural_recovery_inherits_older_paragraph_match_before_new_paper(self):
        parent = stable_id("section-group", "root", "a", "s")
        recovered = stable_id("section-group", "root", "b", "s")
        matches = {
            "c:section_matching:new_to_group:s": parent,
            f"c:section_matching:group_to_new:{parent}": "s",
            f"c:section_rerepresentation:singleton_to_group:{recovered}": parent,
            f"c:section_rerepresentation:group_to_singleton:{parent}": recovered,
        }
        runner, judge = self.run_papers([single_unit_paper(p) for p in ("a", "b", "c")], matches)
        self.assertEqual(self.paragraph_requests(judge), [])
        groups = list(runner.question_graph.nodes("paragraph"))
        self.assertEqual(len(groups), 1)
        self.assertEqual({m["paper_id"] for m in groups[0][1]["members"]}, {"a", "b", "c"})


if __name__ == "__main__":
    unittest.main()
