"""Offline capacity scenarios using the real evidence encoder and prompt renderer.

Synthetic grouping is NOT a matching result. No judge(), Skill registration,
token-count API, or generation API is called. Reports never seed a real run.
"""

import hashlib
import json
import tempfile
from pathlib import Path

from helpers.run_sherlock_five import sherlock_config
from pipeline.files import write_json
from pipeline.incremental_graph.configuration import PromptRepository
from pipeline.incremental_graph.evidence import Evidence
from pipeline.incremental_graph.graph import QuestionGraph
from pipeline.incremental_graph.input_data import load_manifest
from pipeline.incremental_graph.journal import RevisionJournal
from pipeline.incremental_graph.judgments import CachedJudgments
from pipeline.incremental_graph.models import JudgmentRequest
from pipeline.providers.anthropic import ClaudeSkills

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "datasets/sherlock/famous-five/manifest.yaml"
QUESTION = "What function does this particular passage serve within the unfolding investigation and its proposed explanation of the central mysterious case?"


def scenario(fraction: float) -> dict:
    config = sherlock_config()
    _, papers = load_manifest(MANIFEST)
    pools = []
    with tempfile.TemporaryDirectory() as directory:
        journal = RevisionJournal(Path(directory))
        graph = QuestionGraph(journal)
        evidence = Evidence(graph)
        renderer = CachedJudgments(
            PromptRepository(config.prompt_root, config.context_root),
            config.model,
            Path(directory) / "cache",
            config.skill_root,
        )
        root_id = None
        anchors = []
        for index, paper in enumerate(papers, 1):
            graph.add_paper(paper.paper_id, paper.title, index)
            evidence.register(paper)
            section = paper.sections[0]
            for paragraph in section.paragraphs:
                paragraph.question = QUESTION
            if root_id is None:
                root_id = graph.create_group(
                    level="section",
                    parent_id=None,
                    member_id=section.id,
                    paper_id=paper.paper_id,
                    paper_index=index,
                    ordinal=1,
                )
            existing = graph.group_ids("paragraph", root_id)
            current = [p.id for p in section.paragraphs]
            if existing:
                for direction, focus, candidates, allowed, calls in [
                    (
                        "new_to_group",
                        max(
                            [evidence.paragraph_match_context(paper.paper_id, p) for p in current],
                            key=lambda value: len(json.dumps(value)),
                        ),
                        [
                            evidence.paragraph_group_match_context(g, selection_id=g)
                            for g in existing
                        ],
                        existing,
                        len(current),
                    ),
                    (
                        "group_to_new",
                        max(
                            [evidence.paragraph_group_match_context(g) for g in existing],
                            key=lambda g: len(json.dumps(g)),
                        ),
                        [
                            evidence.paragraph_match_context(paper.paper_id, p, selection_id=p)
                            for p in current
                        ],
                        current,
                        len(existing),
                    ),
                ]:
                    request = JudgmentRequest(
                        key="offline-probe",
                        paper_index=index,
                        stage_id="paragraph_matching",
                        output_kind="match",
                        prompt_ref="paragraph-to-group-match/v1"
                        if direction == "new_to_group"
                        else "group-to-paragraph-match/v1",
                        context_ref="matching",
                        skill_ref="match-role",
                        allowed_match_ids=allowed,
                        context={
                            "scope": evidence.scope_context("paragraph", root_id),
                            "focus": focus,
                            "candidates": candidates,
                        },
                    )
                    rendered = renderer.render_request(request)
                    prefix = rendered.cacheable_context or ""
                    chars = len(rendered.system) + len(rendered.user) + len(prefix)
                    pools.append(
                        {
                            "paper": paper.paper_id,
                            "direction": direction,
                            "calls": calls,
                            "candidates": len(allowed),
                            "prompt_characters": chars,
                            "schema_characters": len(json.dumps(rendered.schema)),
                            "cacheable_characters": len(prefix),
                            "cacheable_sha256": hashlib.sha256(prefix.encode()).hexdigest(),
                            "passes_default_prompt_guard": chars <= 500_000,
                            "passes_prompt_guard": chars <= config.model.max_prompt_characters,
                        }
                    )
            for offset, paragraph in enumerate(section.paragraphs):
                if index > 1 and offset < min(len(anchors), int(len(current) * fraction)):
                    graph.add_member(
                        anchors[offset],
                        paragraph.id,
                        paper.paper_id,
                        index,
                        paragraph.ordinal,
                        unit_kind="paragraph",
                    )
                else:
                    group = graph.create_group(
                        level="paragraph",
                        parent_id=root_id,
                        member_id=paragraph.id,
                        paper_id=paper.paper_id,
                        paper_index=index,
                        ordinal=paragraph.ordinal,
                        unit_kind="paragraph",
                    )
                    graph.set_question(group, QUESTION, index, None)
                    if index == 1:
                        anchors.append(group)
        volume = sum(
            (p["prompt_characters"] + p["schema_characters"]) / 3 * p["calls"] for p in pools
        )
        return {
            "synthetic_alignment_fraction": fraction,
            "matching_calls": sum(p["calls"] for p in pools),
            "estimated_matching_input_cost_2_passes_95pct_reads_usd": round(
                volume * 2 * 0.3 / 1_000_000, 2
            ),
            "estimated_matching_input_cost_3_passes_95pct_reads_usd": round(
                volume * 3 * 0.3 / 1_000_000, 2
            ),
            "pools": pools,
        }


def main():
    from unittest.mock import patch

    # Fail rather than accidentally spending money if this helper is changed.
    with patch.object(
        ClaudeSkills,
        "__init__",
        side_effect=AssertionError("Offline preflight forbids API clients"),
    ):
        _, papers = load_manifest(MANIFEST)
        report = {
            "mode": "offline-capacity-only",
            "question_calls": sum(len(s.paragraphs) for p in papers for s in p.sections),
            "assumptions": "Synthetic 20-word questions; primary matching only. Excludes group questions, realignment, retries and tool fees. Native tool iteration volume is unknown; cost sensitivities assume two or three input passes. Character counts are exact for each probe, not API token counts.",
            "cost_assumptions": "3 characters/token; 2 or 3 input passes; 95% cache reads, 2% five-minute writes, 3% uncached. Input-only sensitivity calculation, NOT an expected total or upper bound.",
            "scenarios": [scenario(fraction) for fraction in [0, 0.5, 1]],
        }
    write_json(ROOT / "output/sherlock-five-preflight.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
