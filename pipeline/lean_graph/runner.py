"""Orchestrates the whole paper list through the 7-step pseudocode. This is the only
module that sequences deterministic Python (graph_ops) and LLM judgment (judge.Judge, or
a scripted stand-in in tests) together -- neither of those modules calls the other.

Important, deliberate design point: like pipeline 2's own `run` command, "incremental"
here describes the ALGORITHM (each paper is compared against the groups accumulated so
far, in manifest order), not partial persistence across separate CLI invocations. Every
call to `run()` replays the full paper list from an empty graph. Adding a paper means
adding it to the manifest and running again -- the judgment cache (see judge.py) makes
replaying already-seen content fast and free, so this stays cheap in practice without
needing pipeline 2's revision/journal/replay machinery to make partial resumption safe.
"""
from __future__ import annotations

from typing import Protocol

from .graph_ops import classify, reconcile
from .models import Graph, Paper


class JudgeLike(Protocol):
    def generate_question(self, text: str, kind: str = "passage") -> str: ...
    def match_unit(self, focus_text: str, candidates: dict[str, str], kind: str = "passage") -> str | None: ...


def _run_matching_round(
    graph: Graph,
    judge: JudgeLike,
    *,
    level: str,
    parent_id: str | None,
    paper_id: str,
    units: dict[str, str],
    unit_text: dict[tuple[str, str], str],
) -> dict[str, str]:
    """units: {unit_id: text} for the ONE paper currently being inserted, scoped to this
    round (all of a paper's sections, or one section-group's paragraphs). unit_text is
    the full {(paper_id, unit_id): text} lookup across every paper processed so far (plus
    the current one), needed in step 5 below to regenerate a group's question from ALL of
    its members' text, not just whichever member arrived this round.

    Implements pseudocode steps 1-5 for this one scope.
    """
    existing_ids = [
        node_id for node_id, node in graph.nodes.items() if node.level == level and node.parent_id == parent_id
    ]
    existing_questions = {node_id: graph.nodes[node_id].question for node_id in existing_ids}

    # Step 1: a concise question for every new unit.
    unit_questions = {unit_id: judge.generate_question(text, kind=level) for unit_id, text in units.items()}

    # Step 2: compare every new unit against every existing group, independently in both
    # directions -- a unit's own best-match search, and (separately) each existing
    # group's own best-match search among the new units.
    forward = {unit_id: judge.match_unit(text, existing_questions, kind=level) for unit_id, text in units.items()}
    reverse = {
        node_id: judge.match_unit(existing_questions[node_id], unit_questions, kind=level)
        for node_id in existing_ids
    }

    # Step 3: update the graph from those decisions.
    assignments = reconcile(
        graph,
        level=level,
        parent_id=parent_id,
        paper_id=paper_id,
        new_unit_ids=list(units.keys()),
        existing_group_ids=existing_ids,
        forward=forward,
        reverse=reverse,
    )

    # Step 4: reclassify every node at this level, from scratch.
    classify(graph, level)

    # Step 5: regenerate the question for every node whose membership changed this round
    # (a brand-new node, or an existing group that gained a member) -- using every
    # member's own text, not just this paper's contribution, so a group's question
    # reflects its full accumulated membership.
    touched = set(assignments.values()) | {node_id for node_id in existing_ids if reverse.get(node_id)}
    for node_id in touched:
        node = graph.nodes[node_id]
        member_texts = [unit_text.get((member.paper_id, member.unit_id), "") for member in node.members]
        combined = "\n\n".join(text for text in member_texts if text)
        if combined:
            node.question = judge.generate_question(combined, kind=f"{level} group")

    return assignments


def run(papers: list[Paper], judge: JudgeLike) -> Graph:
    graph = Graph()

    unit_text: dict[tuple[str, str], str] = {}
    for paper in papers:
        for section in paper.sections:
            unit_text[(paper.paper_id, section.id)] = section.text
            for paragraph in section.paragraphs:
                unit_text[(paper.paper_id, paragraph.id)] = paragraph.text

    for paper in papers:
        graph.paper_order.append(paper.paper_id)

        section_units = {section.id: section.text for section in paper.sections}
        section_assignments = _run_matching_round(
            graph, judge,
            level="section", parent_id=None, paper_id=paper.paper_id,
            units=section_units, unit_text=unit_text,
        )

        # Step 6: repeat the same process for paragraphs, independently inside each of
        # this paper's matched section groups -- paragraphs are never compared across
        # section groups.
        for section in paper.sections:
            parent_id = section_assignments[section.id]
            paragraph_units = {paragraph.id: paragraph.text for paragraph in section.paragraphs}
            if not paragraph_units:
                continue
            _run_matching_round(
                graph, judge,
                level="paragraph", parent_id=parent_id, paper_id=paper.paper_id,
                units=paragraph_units, unit_text=unit_text,
            )

    return graph
