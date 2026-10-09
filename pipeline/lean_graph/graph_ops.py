"""Deterministic graph mutations and classification -- no LLM calls anywhere in this
file, and no networkx: the only graph query these functions ever need (does this node
have any edge touching it) is cheap enough to compute directly over a plain list.

This is the Python side of the pseudocode's steps 3 and 4. `reconcile()` takes match
decisions the LLM already made (see judge.py) and updates the graph structurally, exactly
following the table from pipeline 2's own incremental_graph README:

    Neither direction selects a match         -> isolated node
    Exactly one direction selects a match      -> new node + directed alignable_difference edge
    Both directions select each other          -> new member of the existing group

`classify()` then recomputes, from scratch, every node's classification at one level by
walking the graph itself -- coverage vs. paper count (sections) or vs. parent group's own
coverage (paragraphs), same formula pipeline 2 uses.
"""
from __future__ import annotations

from .models import Classification, Edge, Graph, Level, Member, Node


def create_group(
    graph: Graph, *, level: Level, parent_id: str | None, member_paper_id: str, member_unit_id: str
) -> str:
    node_id = f"{level}-{len(graph.nodes)}-{member_paper_id}-{member_unit_id}"
    graph.nodes[node_id] = Node(
        node_id=node_id,
        level=level,
        parent_id=parent_id,
        members=[Member(member_paper_id, member_unit_id)],
    )
    return node_id


def add_member(graph: Graph, node_id: str, paper_id: str, unit_id: str) -> None:
    node = graph.nodes[node_id]
    if any(m.paper_id == paper_id and m.unit_id == unit_id for m in node.members):
        return
    node.members.append(Member(paper_id, unit_id))


def add_edge(graph: Graph, source: str, target: str) -> None:
    graph.edges.append(Edge(source=source, target=target))


def reconcile(
    graph: Graph,
    *,
    level: Level,
    parent_id: str | None,
    paper_id: str,
    new_unit_ids: list[str],
    existing_group_ids: list[str],
    forward: dict[str, str | None],
    reverse: dict[str, str | None],
) -> dict[str, str]:
    """forward: {new_unit_id: chosen existing_group_id or None} -- each new unit's own pick.
    reverse: {existing_group_id: chosen new_unit_id or None} -- each existing group's own pick.
    Returns {new_unit_id: assigned_node_id}.

    A unit is reciprocal exactly when its own forward pick's reverse pick points back at
    it -- every new_unit_id ends up EITHER reciprocal (added as a member of an existing
    group) OR newly created (an isolated/edge-only node), never both and never neither.
    That's what makes the two edge-adding loops below correct without needing to track a
    separate "created" set: "not reciprocal" and "created" are exactly the same set here.
    """
    assignments: dict[str, str] = {}
    reciprocal: set[str] = set()

    for unit_id in new_unit_ids:
        chosen_group = forward.get(unit_id)
        if chosen_group and reverse.get(chosen_group) == unit_id:
            add_member(graph, chosen_group, paper_id, unit_id)
            assignments[unit_id] = chosen_group
            reciprocal.add(unit_id)
        else:
            assignments[unit_id] = create_group(
                graph, level=level, parent_id=parent_id, member_paper_id=paper_id, member_unit_id=unit_id,
            )

    # A new unit's own one-directional pick (it chose a group, but that group didn't
    # reciprocally choose it back) becomes an edge from the unit's own new node to the
    # group it picked.
    for unit_id in new_unit_ids:
        if unit_id in reciprocal:
            continue
        chosen_group = forward.get(unit_id)
        if chosen_group:
            add_edge(graph, assignments[unit_id], chosen_group)

    # An existing group's own one-directional pick (it chose a new unit, but that unit's
    # own forward pick disagreed or found nothing) becomes an edge from the group to
    # that unit's own new node -- but ONLY if the unit ended up isolated. If the unit was
    # instead reciprocally absorbed into some OTHER group, this pick is silently dropped
    # rather than drawn as a group-to-group edge (pipeline 2 logs this as
    # "projected_edge_ignored" provenance; this lean version just drops it, since we're
    # not keeping a provenance log at all).
    for group_id in existing_group_ids:
        chosen_unit = reverse.get(group_id)
        if not chosen_unit or chosen_unit in reciprocal:
            continue
        add_edge(graph, group_id, assignments[chosen_unit])

    return assignments


def _denominator(graph: Graph, node: Node) -> int:
    if node.level == "section":
        return len(graph.paper_order)
    if not node.parent_id or node.parent_id not in graph.nodes:
        return 0
    return len({m.paper_id for m in graph.nodes[node.parent_id].members})


def _degree(graph: Graph, node_id: str) -> int:
    return sum(1 for edge in graph.edges if edge.source == node_id or edge.target == node_id)


def classify(graph: Graph, level: Level) -> None:
    """Recomputes classification for every node at `level`, in place, from scratch --
    same rule as the pseudocode's step 4:

      common_structure:        denominator >= 2 and coverage is a strict majority of it
      alignable_difference:    not common, but coverage >= 2 (multiple papers) or has an edge
      non_alignable_difference: everything else (typically an unconnected singleton)
    """
    for node_id, node in graph.nodes.items():
        if node.level != level:
            continue
        coverage = len({m.paper_id for m in node.members})
        denominator = _denominator(graph, node)
        degree = _degree(graph, node_id)
        classification: Classification
        if denominator >= 2 and coverage > denominator / 2:
            classification = "common_structure"
        elif coverage >= 2 or degree > 0:
            classification = "alignable_difference"
        else:
            classification = "non_alignable_difference"
        node.classification = classification
