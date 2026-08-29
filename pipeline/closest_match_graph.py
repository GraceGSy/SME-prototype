"""Iteratively-built cross-paper correspondence graph from closest-section-match-batch
passes.

For one paper pair (A, B), `closest_section_match_batch.py` is run TWICE -- once with
--paper1=A --paper2=B, once with --paper1=B --paper2=A -- producing two directional
match files. Feeding both files for a pair into `ClosestMatchGraph.add_pair()` is what
"a pair of directional closest match passes" means here.

For every query row in either direction:
  - the query unit gets its own graph node the first time it's seen anywhere, keyed on
    (paper_id, section_name, section_number, subsection_name, subsection_number) via
    `ClosestMatchGraph._member_to_node`. Units with no match still get a node -- so a
    later pair touching that same unit resolves to it rather than creating a duplicate.
  - if BOTH directions agree on a correspondence (A's unit X's best match is B's unit Y,
    AND, independently, B's unit Y's best match is A's unit X), the two units' nodes are
    MERGED into one group node (see `merge_nodes`). Every future pair that touches either
    original unit resolves to the merged node automatically -- group nodes keep absorbing
    further confirmed members as more paper pairs are processed over time. This is the
    "iteratively updated" behavior: the graph is meant to persist across many separate
    calls to `add_pair`, one call per paper pair, not be rebuilt from scratch each time.
  - if only one direction found the match (no reverse confirmation for that specific
    correspondence), a directed `one_directional_match` edge is added between the two
    (unmerged) nodes instead -- weaker evidence, kept visible rather than discarded.

A confirmed match is collapsed into a single node (not just linked by an edge) because
the whole point of running this over many paper pairs is to accumulate a shared
cross-paper structure -- a section that's confirmed-equivalent in papers A and B, and
later confirmed-equivalent in papers B and C, should end up as ONE node with three
members, not three separate nodes daisy-chained by edges.

Uses networkx (`nx.MultiDiGraph`) -- already a project dependency, see
`pipeline/requirements.txt`. No new dependency needed.

Node identity is NOT the original per-unit key once a merge happens -- use
`ClosestMatchGraph.resolve(paper_id, unit)` to look up a unit's current (possibly
merged) node_id.

Usage as a library:

    graph = ClosestMatchGraph()
    graph.add_pair("examplore_chi18", "corpusstudio", a_to_b_rows, b_to_a_rows)
    graph.add_pair("corpusstudio", "mesotext", b_to_c_rows, c_to_b_rows)
    graph.save(Path("closest_match_graph.json"))

    # later, in a different process/run:
    graph = ClosestMatchGraph.load(Path("closest_match_graph.json"))
    graph.add_pair("mesotext", "paralib_uist22", ...)
    graph.save(Path("closest_match_graph.json"))

Usage from the command line -- see `main()` at the bottom of this file:

    python3 build_closest_match_graph.py \\
        --graph closest_match_graph.json \\
        --paper1-id examplore_chi18 --paper2-id corpusstudio \\
        --paper1-to-paper2 examplore_chi18-corpusstudio-closest-section-match-batch.json \\
        --paper2-to-paper1 corpusstudio-examplore_chi18-closest-section-match-batch.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional

import networkx as nx

UnitKey = tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]
UnitDict = dict[str, Optional[str]]


def _unit_from_row(row: dict[str, Any], prefix: str) -> Optional[UnitDict]:
    """Extract a {section_name, section_number, subsection_name, subsection_number}
    dict from a closest-section-match-batch.json row's paper1_*/paper2_* fields.
    Returns None if the unit is absent (i.e. prefix == "paper2" and there was no match)."""
    name = row.get(f"{prefix}_section_name")
    if prefix == "paper2" and name is None and row.get(f"{prefix}_subsection_name") is None:
        return None
    return {
        "section_name": row.get(f"{prefix}_section_name"),
        "section_number": row.get(f"{prefix}_section_number"),
        "subsection_name": row.get(f"{prefix}_subsection_name"),
        "subsection_number": row.get(f"{prefix}_subsection_number"),
    }


def _unit_type(unit: UnitDict) -> str:
    return "subsection" if unit.get("subsection_name") is not None else "section"


def stable_node_id(paper_id: str, unit: UnitDict) -> str:
    payload = "\0".join(
        [
            paper_id,
            str(unit.get("section_name")),
            str(unit.get("section_number")),
            str(unit.get("subsection_name")),
            str(unit.get("subsection_number")),
        ]
    ).encode("utf-8")
    return f"node-{hashlib.sha256(payload).hexdigest()[:16]}"


class ClosestMatchGraph:
    """A thin domain wrapper around a NetworkX directed multigraph, mirroring the shape
    of `pipeline/incremental_graph/graph.py`'s `QuestionGraph` but built post-hoc from
    `closest_section_match_batch.py` output rather than in-process during matching."""

    SCHEMA_VERSION = 1

    def __init__(self) -> None:
        self.graph = nx.MultiDiGraph()
        self._member_to_node: dict[UnitKey, str] = {}
        self.paper_pairs_processed: list[tuple[str, str]] = []

    # -- unit/node bookkeeping -------------------------------------------------

    @staticmethod
    def _unit_key(paper_id: str, unit: UnitDict) -> UnitKey:
        return (
            paper_id,
            unit.get("section_name"),
            unit.get("section_number"),
            unit.get("subsection_name"),
            unit.get("subsection_number"),
        )

    def resolve(self, paper_id: str, unit: UnitDict) -> Optional[str]:
        """Current node_id containing this unit (post-merges), or None if never seen."""
        return self._member_to_node.get(self._unit_key(paper_id, unit))

    def get_or_create_node(self, paper_id: str, unit: UnitDict) -> str:
        key = self._unit_key(paper_id, unit)
        existing = self._member_to_node.get(key)
        if existing is not None:
            return existing
        node_id = stable_node_id(paper_id, unit)
        while node_id in self.graph:
            # Extremely unlikely hash collision -- disambiguate deterministically
            # rather than silently aliasing two different units onto one node.
            node_id = f"{node_id}-x"
        member = {"paper_id": paper_id, "unit_type": _unit_type(unit), **unit}
        self.graph.add_node(
            node_id,
            members=[member],
            confirmations=[],
            merge_history=[],
        )
        self._member_to_node[key] = node_id
        return node_id

    def merge_nodes(self, node_a: str, node_b: str, *, confirmation: dict[str, Any]) -> str:
        """Fold node_b's members and incident edges into node_a (or vice versa,
        survivor chosen deterministically), and return the surviving node_id.
        A no-op (besides recording the confirmation) if the two are already the
        same node -- that happens when a unit gets reconfirmed by a later pair."""
        if node_a == node_b:
            self.graph.nodes[node_a]["confirmations"].append(confirmation)
            return node_a

        survivor, loser = sorted([node_a, node_b])
        survivor_data = self.graph.nodes[survivor]
        loser_data = self.graph.nodes[loser]

        existing_keys = {
            (m["paper_id"], m["section_name"], m["section_number"], m["subsection_name"], m["subsection_number"])
            for m in survivor_data["members"]
        }
        for member in loser_data["members"]:
            member_key = (
                member["paper_id"],
                member["section_name"],
                member["section_number"],
                member["subsection_name"],
                member["subsection_number"],
            )
            if member_key not in existing_keys:
                survivor_data["members"].append(member)
                existing_keys.add(member_key)
            self._member_to_node[
                (member["paper_id"], member["section_name"], member["section_number"], member["subsection_name"], member["subsection_number"])
            ] = survivor

        survivor_data["confirmations"].extend(loser_data["confirmations"])
        survivor_data["confirmations"].append(confirmation)
        survivor_data["merge_history"].append(
            {"absorbed_node": loser, "absorbed_members": loser_data["members"], "confirmation": confirmation}
        )
        survivor_data["merge_history"].extend(loser_data["merge_history"])

        # Re-home every edge incident to `loser` onto `survivor`. Skip anything
        # that would become a self-loop (the two units were already linked by a
        # one-directional edge before this pair confirmed them as the same node) --
        # note it in merge_history instead of silently dropping it, so a graph
        # reader can still see that weaker edge existed pre-merge.
        dropped_self_loop_edges = []
        for source, target, key, data in list(self.graph.in_edges(loser, keys=True, data=True)):
            new_source = survivor if source == loser else source
            if new_source == survivor:
                dropped_self_loop_edges.append({"source": new_source, "target": survivor, **data})
                continue
            self.graph.add_edge(new_source, survivor, key=key, **data)
        for source, target, key, data in list(self.graph.out_edges(loser, keys=True, data=True)):
            new_target = survivor if target == loser else target
            if new_target == survivor:
                dropped_self_loop_edges.append({"source": survivor, "target": new_target, **data})
                continue
            self.graph.add_edge(survivor, new_target, key=key, **data)
        if dropped_self_loop_edges:
            survivor_data["merge_history"][-1]["superseded_edges"] = dropped_self_loop_edges

        self.graph.remove_node(loser)
        return survivor

    # -- feeding in one paper pair's two directional passes ---------------------

    def add_pair(
        self,
        paper_a_id: str,
        paper_b_id: str,
        a_to_b_rows: list[dict[str, Any]],
        b_to_a_rows: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Update the graph with one paper pair's two directional closest-match
        passes: `a_to_b_rows` from a run with --paper1=paper_a_id --paper2=paper_b_id,
        `b_to_a_rows` from the reverse run. Returns a small stats dict."""
        self.paper_pairs_processed.append((paper_a_id, paper_b_id))
        stats = {"nodes_created": 0, "merges": 0, "one_directional_edges": 0}

        nodes_before = self.graph.number_of_nodes()

        a_to_b: list[tuple[UnitDict, Optional[UnitDict], str]] = []
        for row in a_to_b_rows:
            a_unit = _unit_from_row(row, "paper1")
            assert a_unit is not None, f"a_to_b row missing paper1 unit: {row!r}"
            b_unit = _unit_from_row(row, "paper2")
            a_to_b.append((a_unit, b_unit, row.get("basis", "")))

        b_to_a: list[tuple[UnitDict, Optional[UnitDict], str]] = []
        for row in b_to_a_rows:
            b_unit = _unit_from_row(row, "paper1")
            assert b_unit is not None, f"b_to_a row missing paper1 unit: {row!r}"
            a_unit = _unit_from_row(row, "paper2")
            b_to_a.append((b_unit, a_unit, row.get("basis", "")))

        def units_equal(u1: Optional[UnitDict], u2: Optional[UnitDict]) -> bool:
            if u1 is None or u2 is None:
                return False
            return (
                u1.get("section_name") == u2.get("section_name")
                and u1.get("section_number") == u2.get("section_number")
                and u1.get("subsection_name") == u2.get("subsection_name")
                and u1.get("subsection_number") == u2.get("subsection_number")
            )

        consumed_b_to_a_indices: set[int] = set()

        # Forward pass: for every A -> B match, look for reverse confirmation.
        for a_unit, b_unit, basis_fwd in a_to_b:
            node_a = self.get_or_create_node(paper_a_id, a_unit)
            if b_unit is None:
                continue
            node_b = self.get_or_create_node(paper_b_id, b_unit)

            confirmed_index = None
            for i, (rev_b_unit, rev_a_unit, basis_rev) in enumerate(b_to_a):
                if i in consumed_b_to_a_indices:
                    continue
                if units_equal(rev_b_unit, b_unit) and units_equal(rev_a_unit, a_unit):
                    confirmed_index = i
                    break

            if confirmed_index is not None:
                consumed_b_to_a_indices.add(confirmed_index)
                confirmation = {
                    "pair": [paper_a_id, paper_b_id],
                    "a_unit": a_unit,
                    "b_unit": b_unit,
                    "basis_a_to_b": basis_fwd,
                    "basis_b_to_a": b_to_a[confirmed_index][2],
                }
                self.merge_nodes(node_a, node_b, confirmation=confirmation)
                stats["merges"] += 1
            else:
                self.graph.add_edge(
                    node_a,
                    node_b,
                    kind="one_directional_match",
                    direction=f"{paper_a_id}->{paper_b_id}",
                    pair=[paper_a_id, paper_b_id],
                    source_unit={"paper_id": paper_a_id, **a_unit},
                    target_unit={"paper_id": paper_b_id, **b_unit},
                    basis=basis_fwd,
                )
                stats["one_directional_edges"] += 1

        # Reverse pass: any B -> A match not already consumed as a confirmation
        # above is a one-directional edge in the OTHER direction.
        for i, (b_unit, a_unit, basis_rev) in enumerate(b_to_a):
            node_b = self.get_or_create_node(paper_b_id, b_unit)
            if a_unit is None:
                continue
            if i in consumed_b_to_a_indices:
                continue
            node_a = self.get_or_create_node(paper_a_id, a_unit)
            self.graph.add_edge(
                node_b,
                node_a,
                kind="one_directional_match",
                direction=f"{paper_b_id}->{paper_a_id}",
                pair=[paper_a_id, paper_b_id],
                source_unit={"paper_id": paper_b_id, **b_unit},
                target_unit={"paper_id": paper_a_id, **a_unit},
                basis=basis_rev,
            )
            stats["one_directional_edges"] += 1

        stats["nodes_created"] = self.graph.number_of_nodes() - nodes_before + stats["merges"]
        return stats

    # -- redundancy flagging ---------------------------------------------------

    @staticmethod
    def _family_key(unit: dict[str, Any]) -> tuple[str, Optional[str], Optional[str]]:
        """A unit's 'section family' identity: its own paper plus its top-level
        section (ignoring subsection). Every subsection under the same top-level
        section, and the top-level section itself, share this key -- so looking
        up this key finds a unit's parent section and all its sibling
        subsections, from its own paper's hierarchy only."""
        return (unit["paper_id"], unit["section_name"], unit["section_number"])

    @staticmethod
    def _member_key(member: dict[str, Any]) -> tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]:
        return (
            member["paper_id"],
            member["section_name"],
            member["section_number"],
            member["subsection_name"],
            member["subsection_number"],
        )

    def redundant_edges(self) -> list[dict[str, Any]]:
        """Flag (without removing) one-directional edges that are redundant given
        an already-CONFIRMED (bidirectionally merged) match elsewhere in the
        edge's own source unit's section family -- its parent section and/or
        sibling subsections, within its own paper. Returns a list of dicts
        describing each flagged edge; the graph itself is never modified, so
        flagged edges stay fully inspectable rather than silently disappearing.

        An edge (S -> T) is flagged when some node F:
          - contains a member belonging to S's family (S itself, S's parent
            section, or a sibling subsection under that same parent), AND
          - is CONFIRMED, i.e. has more than one member (survived a
            bidirectional merge), AND
          - has a member that is EXACTLY T -- the same paper, section, and
            subsection identity, not merely "close to T."

        This deliberately does NOT flag an edge whose target is T's parent or a
        sibling of T rather than T itself, even when that parent/sibling is
        confirmed elsewhere. That case is a genuine finer-grained refinement of
        an already-confirmed whole-section match (e.g. proposing which specific
        subsection on one side best matches a specific subsection on the other,
        within a pair of sections already confirmed at the whole-section level)
        -- it adds new information rather than restating an existing
        correspondence, so it is intentionally left unflagged. Only an EXACT
        repeated target counts as redundant.

        Symmetric in practice despite only scanning the source's family: a
        unit's family already contains both its parent and its children (from
        its own paper), so this single-sided scan catches both "a subsection is
        redundant because its parent is already confirmed to this exact
        target" and "a parent is redundant because one of its own children is
        already confirmed to this exact target" -- see the module's own tests
        for concrete examples of both directions.
        """
        family_index: dict[tuple[str, Optional[str], Optional[str]], set[str]] = {}
        for node_id, data in self.graph.nodes(data=True):
            for member in data["members"]:
                family_index.setdefault(self._family_key(member), set()).add(node_id)

        flagged: list[dict[str, Any]] = []
        for source, target, key, data in self.graph.edges(keys=True, data=True):
            if data.get("kind") != "one_directional_match":
                continue
            source_unit = data["source_unit"]
            target_unit = data["target_unit"]
            target_key = self._member_key(target_unit)

            covering_node = None
            for node_id in family_index.get(self._family_key(source_unit), ()):
                node_data = self.graph.nodes[node_id]
                if len(node_data["members"]) <= 1:
                    continue  # not a confirmed/merged node
                if any(self._member_key(member) == target_key for member in node_data["members"]):
                    covering_node = node_id
                    break

            if covering_node is not None:
                flagged.append(
                    {
                        "source_node": source,
                        "target_node": target,
                        "edge_key": key,
                        "source_unit": source_unit,
                        "target_unit": target_unit,
                        "pair": data.get("pair"),
                        "basis": data.get("basis"),
                        "covering_confirmed_node": covering_node,
                        "reason": (
                            "target is already the confirmed bidirectional match of "
                            "another member of the source unit's own section family"
                        ),
                    }
                )
        return flagged

    def one_to_many_candidates(self) -> list[dict[str, Any]]:
        """Flag families (a paper's own top-level section plus all its subsections)
        whose combined evidence -- confirmed matches AND one-directional edges
        together -- points at TWO OR MORE DISTINCT top-level sections on the other
        paper. Purely a post-hoc read of matches already made; no new API call and
        no new matching logic. The graph is never modified.

        This is the automated version of the "Corpus Studio bundles three
        examplore_chi18 sections into one" pattern found by hand for the
        examplore_chi18/corpusstudio pair (see README-sme2-restart.md): when a
        section's own subsections and whole-section candidate collectively link to
        multiple genuinely different sections elsewhere, that's often a sign the
        section's real content spans more than one role the other paper keeps
        separate -- a real candidate for a one-to-many correspondence, not
        something a single-best-match-per-query design can represent cleanly.

        A family's links come from two sources, both counted as coverage evidence
        toward the same question ("what does this family correspond to over
        there?"):
          - CONFIRMED matches: every member of a merged (>1-member) node implies a
            link between that member's family and every other member's family.
          - ONE-DIRECTIONAL edges: every `one_directional_match` edge implies a
            link between its source's family and its target's family (counted from
            both families' point of view).

        Two links into the SAME far-side family (e.g. three different subsections
        of one section all linking into different subsections of one already-
        confirmed far-side section) do NOT trigger a flag -- that's ordinary
        subsection-level refinement or disagreement within an already-matched pair
        of sections (see `redundant_edges` for the exact-duplicate-target case of
        this), not evidence of spanning multiple sections. Only distinct far-side
        TOP-LEVEL sections count.

        Returns a list of dicts, one per flagged family:
          - "family": {"paper_id", "section_name", "section_number"}
          - "far_side_targets": one entry per distinct far-side family this one
            links to, each with that family's identity and the specific evidence
            (confirmed member pairs and/or one-directional edges, each carrying
            its own `status` ("confirmed" or "one_directional"), the specific
            linking/target units, and -- for one-directional evidence -- the
            original `basis` text).
        """
        # far_side_links[source_family][far_family] = [evidence, ...]
        far_side_links: dict[
            tuple[str, Optional[str], Optional[str]],
            dict[tuple[str, Optional[str], Optional[str]], list[dict[str, Any]]],
        ] = {}

        def add_link(
            source_family: tuple[str, Optional[str], Optional[str]],
            far_family: tuple[str, Optional[str], Optional[str]],
            evidence: dict[str, Any],
        ) -> None:
            far_side_links.setdefault(source_family, {}).setdefault(far_family, []).append(evidence)

        # Confirmed matches: every pair of members in a merged node links their
        # two families to each other (this is symmetric evidence -- both families
        # learn about each other from the same confirmed pairing).
        for _, data in self.graph.nodes(data=True):
            members = data["members"]
            if len(members) <= 1:
                continue
            for member in members:
                member_family = self._family_key(member)
                for other in members:
                    if other is member:
                        continue
                    other_family = self._family_key(other)
                    if other_family == member_family:
                        continue  # same paper -- shouldn't happen, guard anyway
                    add_link(
                        member_family,
                        other_family,
                        {"status": "confirmed", "linking_unit": member, "target_unit": other, "basis": None},
                    )

        # One-directional edges: link source's family to target's family, and the
        # reverse, so both sides' families see the evidence.
        for _, _, _, data in self.graph.edges(keys=True, data=True):
            if data.get("kind") != "one_directional_match":
                continue
            source_unit = data["source_unit"]
            target_unit = data["target_unit"]
            source_family = self._family_key(source_unit)
            target_family = self._family_key(target_unit)
            add_link(
                source_family,
                target_family,
                {
                    "status": "one_directional",
                    "linking_unit": source_unit,
                    "target_unit": target_unit,
                    "basis": data.get("basis"),
                },
            )
            add_link(
                target_family,
                source_family,
                {
                    "status": "one_directional",
                    "linking_unit": target_unit,
                    "target_unit": source_unit,
                    "basis": data.get("basis"),
                },
            )

        flagged: list[dict[str, Any]] = []
        for source_family, far_families in far_side_links.items():
            if len(far_families) < 2:
                continue
            flagged.append(
                {
                    "family": {
                        "paper_id": source_family[0],
                        "section_name": source_family[1],
                        "section_number": source_family[2],
                    },
                    "far_side_targets": [
                        {
                            "family": {
                                "paper_id": far_family[0],
                                "section_name": far_family[1],
                                "section_number": far_family[2],
                            },
                            "evidence": evidence_list,
                        }
                        for far_family, evidence_list in far_families.items()
                    ],
                }
            )

        flagged.sort(key=lambda f: (f["family"]["paper_id"], f["family"]["section_name"] or ""))
        return flagged

    def fan_in_candidates(self) -> list[dict[str, Any]]:
        """Flags NODES that TWO OR MORE DISTINCT sections/subsections from the SAME
        other paper each independently chose as their own single closest match --
        fan-IN onto one target, the mirror image of `one_to_many_candidates()`'s
        fan-OUT (one section/subsection pointing at 2+ distinct far-side families).
        Since every unit's own directional pass can only ever name ONE closest match,
        at most one of a fan-in group's claimants can end up reciprocated (a
        CONFIRMED member of the target's node); the rest are necessarily left as
        unreciprocated `one_directional_match` inbound edges.

        This is the section-level sibling of `paragraph_match_graph.
        ParagraphMatchGraph.fan_in_candidates` -- same discipline, one level up. A
        real instance, verified by running this method against the examplore_chi18/
        corpusstudio corpus: corpusstudio's "Implementation Details" (3.4) subsection
        AND its whole "Data & Processing" section are both independently the closest
        match for examplore_chi18's whole SYSTEM ARCHITECTURE AND IMPLEMENTATION
        section (no subsection) -- two distinct corpusstudio units converging on the
        exact same examplore_chi18 target, neither one confirmed. (An earlier draft of
        this docstring guessed a different pair for this same target from an
        un-reverified recollection of an edge's direction -- corrected here against
        this method's own actual output rather than left standing on a guess.)

        Note this checks something genuinely different from `one_to_many_candidates`,
        not a stricter/looser version of it: that method coarsens the TARGET side to
        family granularity (top-level section, ignoring subsection) and pools the
        SOURCE side into one family's combined evidence; this method sharpens the
        TARGET to one exact unit and keeps the claiming SOURCE units individuated,
        with no requirement that they share a family at all. The two can both fire on
        the same underlying data (as in the example above) without either implying
        the other.

        Purely a post-hoc read of matches already made; no new API call, no new
        matching logic, and the graph itself is never modified.

        Returns a list of dicts, one per flagged (node, claiming paper) group:
          - "target_members": the node's own member(s) NOT belonging to the claiming
            paper (normally exactly one, in the common two-paper-per-node case; more
            if this node has absorbed confirmed members from more than two papers
            across multiple pairs).
          - "claiming_paper_id": the paper whose distinct units are fanning in.
          - "claims": one entry per claiming unit -- {"status", "unit", "basis"}.
            `status` is "confirmed" (this specific claim WAS reciprocated -- it's
            itself a member of the target's node) or "one_directional" (left
            stranded). At most one "confirmed" entry ordinarily appears per group;
            often zero.
        """
        claims_by_node: dict[str, dict[str, list[dict[str, Any]]]] = {}

        for node_id, data in self.graph.nodes(data=True):
            per_paper: dict[str, list[dict[str, Any]]] = claims_by_node.setdefault(node_id, {})
            for member in data["members"]:
                per_paper.setdefault(member["paper_id"], []).append(
                    {"status": "confirmed", "unit": member, "basis": None}
                )

        for _, target_node, _, data in self.graph.edges(keys=True, data=True):
            if data.get("kind") != "one_directional_match":
                continue
            source_unit = data["source_unit"]
            per_paper = claims_by_node.setdefault(target_node, {})
            per_paper.setdefault(source_unit["paper_id"], []).append(
                {"status": "one_directional", "unit": source_unit, "basis": data.get("basis")}
            )

        flagged: list[dict[str, Any]] = []
        for node_id, per_paper in claims_by_node.items():
            members = self.graph.nodes[node_id]["members"]
            for claiming_paper_id, claim_list in per_paper.items():
                if len(claim_list) < 2:
                    continue
                flagged.append(
                    {
                        "target_members": [m for m in members if m["paper_id"] != claiming_paper_id],
                        "claiming_paper_id": claiming_paper_id,
                        "claims": claim_list,
                    }
                )

        flagged.sort(
            key=lambda f: (
                f["claiming_paper_id"],
                f["target_members"][0]["paper_id"] if f["target_members"] else "",
                f["target_members"][0].get("section_name") or "" if f["target_members"] else "",
            )
        )
        return flagged

    def fan_in_correspondence_table(self) -> list[dict[str, Any]]:
        """Build the row data behind the README's "Bidirectional and (even unrequited)
        Fan_In Correspondence Table" for sections/subsections: one row per node that is
        either BIDIRECTIONAL (both directions agree, i.e. merged, len(members) > 1) or
        the target of a `fan_in_candidates()`-style convergence (>= 2 distinct claims
        from the same other paper) even when never reciprocated -- the same
        "structurally different, unreciprocated" row the README's paragraph-level
        worked example calls out (e.g. a target whose own directional pass picked
        something else, or nothing). Every non-redundant one-directional claim on a
        row's node is folded into the same row, in the cell of whichever paper made
        the claim.

        Filters every one-directional claim through `redundant_edges()` first -- a
        claim whose source unit is already covered by a sibling's bidirectional match
        to the exact same target is dropped, same discipline as the README's own "Step
        2: filter out every extra claim that redundant_edges() already flags" worked
        example. This is the one place this method structurally diverges from its
        `ParagraphMatchGraph` sibling: that class has no `redundant_edges()` to filter
        through (see its own module docstring for why), so its version of this table
        includes every non-empty fan-in claim, unfiltered.

        Returns a list of dicts, UNORDERED -- row order is a presentation choice (e.g.
        one paper's own document order) this method has no way to make on its own:
          - "node_id": the node's graph id, for cross-referencing.
          - "cells": {paper_id: [(label, is_bidirectional), ...]}. `is_bidirectional`
            is True for every entry only when the node itself is bidirectional
            (len(members) > 1); on an unreciprocated node (single member, flagged only
            via fan-in), even that lone member renders unbolded, matching the README's
            "last row has no bold at all, since nothing there reciprocated" convention.
            Feed straight into `fan_in_table.render_correspondence_table_markdown` for
            the README's exact rendering, or consume the structured form directly.

        A unit's label is `"{section_name} > {subsection_name}"` for a subsection, or
        `"{section_name} (whole)"` for a top-level section IF that (paper_id,
        section_name) has at least one subsection-level unit anywhere in this graph
        (as a bidirectional member or one-directional edge endpoint) -- otherwise just
        `"{section_name}"`, no "(whole)" tag. Derived entirely from this graph's own
        contents, never by re-reading the source paper JSON.

        Within a cell, a bidirectional member (if any) is listed first, followed by
        non-redundant one-directional claims in whatever order `fan_in_candidates()`-
        style iteration encountered them -- no additional sort. This is a deliberate
        difference from the paragraph-level sibling's numeric-by-paragraph-number sort;
        section/subsection labels have no natural total order to sort by.
        """
        has_subsections: set[tuple[str, str]] = set()

        def note_subsections(u: dict[str, Any]) -> None:
            if u.get("subsection_name"):
                has_subsections.add((u["paper_id"], u["section_name"]))

        for _, data in self.graph.nodes(data=True):
            for m in data["members"]:
                note_subsections(m)
        for _, _, data in self.graph.edges(data=True):
            if data.get("kind") != "one_directional_match":
                continue
            note_subsections(data["source_unit"])
            note_subsections(data["target_unit"])

        def unit_label(u: dict[str, Any]) -> str:
            if u.get("subsection_name"):
                return f"{u['section_name']} > {u['subsection_name']}"
            if (u["paper_id"], u["section_name"]) in has_subsections:
                return f"{u['section_name']} (whole)"
            return u["section_name"]

        redundant_keys = {
            (self._member_key(r["source_unit"]), self._member_key(r["target_unit"]))
            for r in self.redundant_edges()
        }

        claims_by_node: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for node_id, data in self.graph.nodes(data=True):
            per_paper = claims_by_node.setdefault(node_id, {})
            for member in data["members"]:
                per_paper.setdefault(member["paper_id"], []).append({"status": "bidirectional", "unit": member})
        for source, target, key, data in self.graph.edges(keys=True, data=True):
            if data.get("kind") != "one_directional_match":
                continue
            su = data["source_unit"]
            per_paper = claims_by_node.setdefault(target, {})
            per_paper.setdefault(su["paper_id"], []).append(
                {"status": "one_directional", "unit": su, "target_unit": data["target_unit"]}
            )

        rows: list[dict[str, Any]] = []
        for node_id, data in self.graph.nodes(data=True):
            members = data["members"]
            is_bidirectional_node = len(members) > 1
            per_paper = claims_by_node.get(node_id, {})
            has_fan_in = any(len(claim_list) >= 2 for claim_list in per_paper.values())
            if not is_bidirectional_node and not has_fan_in:
                continue

            cells: dict[str, list[tuple[str, bool]]] = {}
            for m in members:
                cells.setdefault(m["paper_id"], []).append((unit_label(m), is_bidirectional_node))
            for claiming_paper, claim_list in per_paper.items():
                for c in claim_list:
                    if c["status"] != "one_directional":
                        continue
                    if (self._member_key(c["unit"]), self._member_key(c["target_unit"])) in redundant_keys:
                        continue
                    cells.setdefault(claiming_paper, []).append((unit_label(c["unit"]), False))
            rows.append({"node_id": node_id, "cells": cells})
        return rows

    # -- persistence --------------------------------------------------------

    def serialize(self) -> dict[str, Any]:
        nodes = [
            {"node_id": node_id, **{k: data[k] for k in sorted(data)}}
            for node_id, data in sorted(self.graph.nodes(data=True))
        ]
        edges = [
            {"source": source, "target": target, "key": key, **{k: data[k] for k in sorted(data)}}
            for source, target, key, data in sorted(
                self.graph.edges(keys=True, data=True), key=lambda e: (e[0], e[1], str(e[2]))
            )
        ]
        return {
            "schema_version": self.SCHEMA_VERSION,
            "paper_pairs_processed": [list(pair) for pair in self.paper_pairs_processed],
            "nodes": nodes,
            "edges": edges,
        }

    def save(self, path: Path) -> None:
        path = Path(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.serialize(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "ClosestMatchGraph":
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError(
                f"{path} has schema_version={payload.get('schema_version')!r}, "
                f"expected {cls.SCHEMA_VERSION!r}"
            )
        instance = cls()
        instance.paper_pairs_processed = [tuple(pair) for pair in payload["paper_pairs_processed"]]
        for node in payload["nodes"]:
            node_id = node["node_id"]
            data = {k: v for k, v in node.items() if k != "node_id"}
            instance.graph.add_node(node_id, **data)
            for member in data["members"]:
                key = (
                    member["paper_id"],
                    member["section_name"],
                    member["section_number"],
                    member["subsection_name"],
                    member["subsection_number"],
                )
                instance._member_to_node[key] = node_id
        for edge in payload["edges"]:
            source = edge["source"]
            target = edge["target"]
            key = edge["key"]
            data = {k: v for k, v in edge.items() if k not in ("source", "target", "key")}
            instance.graph.add_edge(source, target, key=key, **data)
        return instance

    # -- convenience ----------------------------------------------------------

    def summary(self) -> dict[str, int]:
        merged_nodes = sum(1 for _, data in self.graph.nodes(data=True) if len(data["members"]) > 1)
        return {
            "pairs_processed": len(self.paper_pairs_processed),
            "total_nodes": self.graph.number_of_nodes(),
            "merged_nodes": merged_nodes,
            "singleton_nodes": self.graph.number_of_nodes() - merged_nodes,
            "one_directional_edges": self.graph.number_of_edges(),
            "redundant_one_directional_edges": len(self.redundant_edges()),
            "fan_in_groups": len(self.fan_in_candidates()),
        }


def _load_rows(path: Path) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", type=Path, required=True, help="Path to the persistent graph JSON file (created if it doesn't exist yet)")
    parser.add_argument("--paper1-id", required=True, help="Literal paper id used as --paper1 in the FIRST directional run")
    parser.add_argument("--paper2-id", required=True, help="Literal paper id used as --paper2 in the FIRST directional run")
    parser.add_argument("--paper1-to-paper2", type=Path, required=True, help="closest-section-match-batch.json from --paper1=paper1-id --paper2=paper2-id")
    parser.add_argument("--paper2-to-paper1", type=Path, required=True, help="closest-section-match-batch.json from --paper1=paper2-id --paper2=paper1-id")
    args = parser.parse_args()

    if args.graph.exists():
        print(f"Loading existing graph: {args.graph}")
        graph = ClosestMatchGraph.load(args.graph)
    else:
        print(f"No existing graph at {args.graph} -- starting a new one")
        graph = ClosestMatchGraph()

    if (args.paper1_id, args.paper2_id) in graph.paper_pairs_processed:
        print(
            f"WARNING: pair ({args.paper1_id}, {args.paper2_id}) has already been added to this "
            "graph. Re-adding will re-run confirmation logic and may double-count edges/merges "
            "if the input files are the same as before.",
            file=sys.stderr,
        )

    a_to_b_rows = _load_rows(args.paper1_to_paper2)
    b_to_a_rows = _load_rows(args.paper2_to_paper1)

    stats = graph.add_pair(args.paper1_id, args.paper2_id, a_to_b_rows, b_to_a_rows)
    graph.save(args.graph)

    print(
        f"Added pair ({args.paper1_id}, {args.paper2_id}): "
        f"{stats['merges']} confirmed merges, {stats['one_directional_edges']} one-directional edges"
    )
    print(f"Graph summary after this update: {graph.summary()}")
    print(f"Saved to {args.graph}")


if __name__ == "__main__":
    main()
