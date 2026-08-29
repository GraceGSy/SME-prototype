"""Iteratively-built cross-paper PARAGRAPH correspondence graph from
closest_paragraph_match_within_section.py passes.

The paragraph-level sibling of `closest_match_graph.py`'s `ClosestMatchGraph`. That
class accumulates evidence per PAPER PAIR, searching one paper's whole
section/subsection candidate pool against the other's. This module accumulates
evidence per SECTION PAIRING instead: given two sections (or subsections) already
believed to correspond -- typically because `ClosestMatchGraph` already flagged them
as confirmed, or as a one-directional edge worth drilling into -- `closest_paragraph_
match_within_section.py` is run TWICE, once in each direction (paper1's paragraphs
searched against paper2's, and vice versa), producing two directional paragraph-match
files. Feeding both files for one section pairing into `ParagraphMatchGraph.
add_section_pairing()` is what "one pairing's two directional passes" means here.

Deliberately a SEPARATE class rather than a generalization of `ClosestMatchGraph`,
for reasons worth stating up front (this was a real design decision, not an
oversight): the two graphs' natural accumulation unit differs (one paper pair vs.
one section pairing), `ClosestMatchGraph` already has real persisted corpus-scale
state and a test suite riding on its exact 2-level (section/subsection) unit
schema, and unifying the two would require re-deriving `_unit_from_row` as a
schema-pluggable abstraction rather than a mechanical extension. See the
`closest_paragraph_match_within_section.py` design conversation this module grew
out of for the fuller tradeoff discussion.

Everything else about the design is a direct, one-level-deeper port of
`ClosestMatchGraph`:

  - A paragraph unit's identity is now a 6-tuple --
    (paper_id, section_name, section_number, subsection_name, subsection_number,
    paragraph_number) -- one field deeper than `ClosestMatchGraph`'s 5-tuple. Every
    query paragraph gets its own node the first time it's seen, keyed on this tuple,
    even if it never matches anything -- so a later section pairing touching that
    same paragraph resolves to the existing node rather than creating a duplicate.
  - If BOTH directions agree (paper A's paragraph X's best match is paper B's
    paragraph Y, AND, independently, paper B's paragraph Y's best match is paper A's
    paragraph X), the two nodes MERGE into one group node -- same `merge_nodes`
    machinery, same "iteratively accumulates confirmed members across many separate
    calls" behavior.
  - If only one direction found the match, a directed `one_directional_match` edge
    is added instead.

Unlike a section/subsection unit, a paragraph's identity alone doesn't tell a graph
reader what the paragraph actually says -- so unlike `ClosestMatchGraph`, each
member here also carries its own `text` (the paragraph's full text, carried straight
through from the closest-paragraph-match-batch row). `text` is payload, not identity
-- it plays no part in `_unit_key`/`stable_node_id`/`_member_key`, purely for
readability of the persisted graph without cross-referencing the source paper JSON.

A paragraph's "family," for `one_to_many_candidates()` purposes, is its enclosing
section/subsection -- (paper_id, section_name, section_number, subsection_name,
subsection_number) -- deliberately identical in shape to a `ClosestMatchGraph` UNIT
key one level up.

Deliberately NO `redundant_edges()` on this class, unlike `ClosestMatchGraph` --
removed after being ported over mechanically and then found to be actively wrong at
this granularity, not merely unnecessary. That method's section-level justification
rests on real containment (a whole section's candidate is literally defined as its
own paragraphs plus every subsection's, concatenated -- see Stage 3's candidate
construction -- so a subsection pointing at an already-confirmed whole-section target
truly is repeating already-counted content). Sibling PARAGRAPHS have no such
containment relationship: paragraph 3 is not part of paragraph 4, so paragraph 4
confirming against a target doesn't mean paragraph 3's content was already
represented there. A mechanical port of the same rule ends up flagging exactly the
cases that are the real finding at this granularity -- paragraph-density mismatch,
where one paper compresses into one paragraph what the other needed several to say
-- as if they were redundant restatements. See the "-- redundancy flagging --"
comment block just above `one_to_many_candidates()` below for the concrete
verification (it filtered out all three real fan-in groups found for the
corpusstudio/examplore_chi18 Introduction pairing).

`one_to_many_candidates()` here answers the paragraph-level version of the same
question `ClosestMatchGraph`'s answers at the section level: does one paragraph's
combined evidence, across however many section pairings it's been searched within,
point at TWO OR MORE DISTINCT enclosing subsections on the other side? A real,
already-observed example of the pattern this looks for (see the corpusstudio/
examplore_chi18 Introduction-vs-Introduction paragraph run): corpusstudio's
Introduction paragraph 4 ("we implemented CorpusStudio...") was independently the
single closest match for THREE different examplore_chi18 Introduction paragraphs
(3, 4, and 5) -- not because it spans multiple roles, but because corpusstudio
compresses into one dense paragraph what examplore_chi18 spreads across three. That
particular case wouldn't trigger a flag here (all three targets share one family --
examplore_chi18's Introduction), but it's exactly the kind of paragraph-density
mismatch this class's evidence-collection makes newly visible, distinct from the
CONTENT-spans-multiple-roles case the flag itself is looking for.

Usage as a library:

    graph = ParagraphMatchGraph()
    graph.add_section_pairing(
        "corpusstudio", "examplore_chi18",
        corpusstudio_to_examplore_rows, examplore_to_corpusstudio_rows,
    )
    graph.save(Path("paragraph_match_graph.json"))

    # later, in a different process/run, drilling into a different section pairing
    # between the same two papers -- or a different paper pair entirely:
    graph = ParagraphMatchGraph.load(Path("paragraph_match_graph.json"))
    graph.add_section_pairing("corpusstudio", "examplore_chi18", ...)
    graph.save(Path("paragraph_match_graph.json"))

Usage from the command line -- see `main()` at the bottom of this file:

    python3 paragraph_match_graph.py \\
        --graph paragraph_match_graph.json \\
        --paper1-id corpusstudio --paper2-id examplore_chi18 \\
        --paper1-to-paper2 corpusstudio-introduction-examplore_chi18-introduction-closest-paragraph-match.json \\
        --paper2-to-paper1 examplore_chi18-introduction-corpusstudio-introduction-closest-paragraph-match.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional

import networkx as nx

UnitKey = tuple[str, Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]
FamilyKey = tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]
UnitDict = dict[str, Any]


def _unit_from_row(row: dict[str, Any], prefix: str) -> Optional[UnitDict]:
    """Extract a {section_name, section_number, subsection_name, subsection_number,
    paragraph_number, text} dict from a closest-paragraph-match-batch.json row's
    paper1_*/paper2_* fields. Returns None if the unit is absent (i.e. prefix ==
    "paper2" and there was no match for that query paragraph)."""
    paragraph_number = row.get(f"{prefix}_paragraph_number")
    if prefix == "paper2" and paragraph_number is None:
        return None
    return {
        "section_name": row.get(f"{prefix}_section_name"),
        "section_number": row.get(f"{prefix}_section_number"),
        "subsection_name": row.get(f"{prefix}_subsection_name"),
        "subsection_number": row.get(f"{prefix}_subsection_number"),
        "paragraph_number": paragraph_number,
        "text": row.get(f"{prefix}_text"),
    }


def stable_node_id(paper_id: str, unit: UnitDict) -> str:
    payload = "\0".join(
        [
            paper_id,
            str(unit.get("section_name")),
            str(unit.get("section_number")),
            str(unit.get("subsection_name")),
            str(unit.get("subsection_number")),
            str(unit.get("paragraph_number")),
        ]
    ).encode("utf-8")
    return f"pnode-{hashlib.sha256(payload).hexdigest()[:16]}"


class ParagraphMatchGraph:
    """A thin domain wrapper around a NetworkX directed multigraph -- the
    paragraph-level sibling of `closest_match_graph.ClosestMatchGraph`. See this
    module's own docstring for the full design rationale and how it differs from
    (and deliberately does not unify with) that class."""

    SCHEMA_VERSION = 1

    def __init__(self) -> None:
        self.graph = nx.MultiDiGraph()
        self._member_to_node: dict[UnitKey, str] = {}
        self.section_pairings_processed: list[tuple[str, str]] = []

    # -- unit/node bookkeeping -------------------------------------------------

    @staticmethod
    def _unit_key(paper_id: str, unit: UnitDict) -> UnitKey:
        return (
            paper_id,
            unit.get("section_name"),
            unit.get("section_number"),
            unit.get("subsection_name"),
            unit.get("subsection_number"),
            unit.get("paragraph_number"),
        )

    @staticmethod
    def _family_key(unit: dict[str, Any]) -> FamilyKey:
        """A paragraph's 'family' identity: its own paper plus its enclosing
        section/subsection, ignoring paragraph_number. Every paragraph sharing the
        same enclosing section/subsection shares this key -- the direct one-level-
        deeper analog of `ClosestMatchGraph._family_key`'s 'top-level section,
        ignoring subsection.' Deliberately identical in shape to a
        `ClosestMatchGraph` unit key -- a paragraph's family IS its enclosing
        section-level unit."""
        return (
            unit["paper_id"],
            unit.get("section_name"),
            unit.get("section_number"),
            unit.get("subsection_name"),
            unit.get("subsection_number"),
        )

    @staticmethod
    def _member_key(member: dict[str, Any]) -> UnitKey:
        return (
            member["paper_id"],
            member.get("section_name"),
            member.get("section_number"),
            member.get("subsection_name"),
            member.get("subsection_number"),
            member.get("paragraph_number"),
        )

    def resolve(self, paper_id: str, unit: UnitDict) -> Optional[str]:
        """Current node_id containing this paragraph unit (post-merges), or None
        if never seen."""
        return self._member_to_node.get(self._unit_key(paper_id, unit))

    def get_or_create_node(self, paper_id: str, unit: UnitDict) -> str:
        key = self._unit_key(paper_id, unit)
        existing = self._member_to_node.get(key)
        if existing is not None:
            return existing
        node_id = stable_node_id(paper_id, unit)
        while node_id in self.graph:
            # Extremely unlikely hash collision -- disambiguate deterministically
            # rather than silently aliasing two different paragraphs onto one node.
            node_id = f"{node_id}-x"
        member = {"paper_id": paper_id, "unit_type": "paragraph", **unit}
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
        survivor chosen deterministically), and return the surviving node_id. Same
        shape as `ClosestMatchGraph.merge_nodes` -- see that method's docstring for
        the self-loop-on-merge handling this mirrors exactly."""
        if node_a == node_b:
            self.graph.nodes[node_a]["confirmations"].append(confirmation)
            return node_a

        survivor, loser = sorted([node_a, node_b])
        survivor_data = self.graph.nodes[survivor]
        loser_data = self.graph.nodes[loser]

        existing_keys = {self._member_key(m) for m in survivor_data["members"]}
        for member in loser_data["members"]:
            member_key = self._member_key(member)
            if member_key not in existing_keys:
                survivor_data["members"].append(member)
                existing_keys.add(member_key)
            self._member_to_node[member_key] = survivor

        survivor_data["confirmations"].extend(loser_data["confirmations"])
        survivor_data["confirmations"].append(confirmation)
        survivor_data["merge_history"].append(
            {"absorbed_node": loser, "absorbed_members": loser_data["members"], "confirmation": confirmation}
        )
        survivor_data["merge_history"].extend(loser_data["merge_history"])

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

    # -- feeding in one section pairing's two directional paragraph passes -----

    def add_section_pairing(
        self,
        paper_a_id: str,
        paper_b_id: str,
        a_to_b_rows: list[dict[str, Any]],
        b_to_a_rows: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Update the graph with one section pairing's two directional paragraph-
        match passes: `a_to_b_rows` from a closest_paragraph_match_within_section.py
        run with --paper1 pointed at paper_a_id's chosen section/subsection,
        `b_to_a_rows` from the reverse run. Same reciprocal-confirmation logic as
        `ClosestMatchGraph.add_pair` -- see that method's docstring for the full
        walkthrough; only the unit shape (paragraphs, one field deeper) differs."""
        self.section_pairings_processed.append((paper_a_id, paper_b_id))
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
                and u1.get("paragraph_number") == u2.get("paragraph_number")
            )

        consumed_b_to_a_indices: set[int] = set()

        # Forward pass: for every A -> B paragraph match, look for reverse confirmation.
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

        # Reverse pass: any B -> A paragraph match not already consumed as a
        # confirmation above is a one-directional edge in the OTHER direction.
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
    #
    # Deliberately NO `redundant_edges()` on this class -- removed after being
    # ported over mechanically from `ClosestMatchGraph` and then found, on real
    # inspection, to be actively wrong at this granularity rather than merely
    # unnecessary. `ClosestMatchGraph.redundant_edges()`'s justification rests on a
    # real CONTAINMENT relationship: a "whole section" candidate is *literally
    # defined* as its own lead-in paragraphs plus every subsection's paragraphs,
    # concatenated (see closest_section_match_batch.py's candidate construction) --
    # so a subsection's content is a strict subset of what the whole section already
    # presented as evidence. If the whole section confirms against target T and the
    # subsection also points at T, that genuinely is redundant: the same content,
    # read twice, at two granularities.
    #
    # Sibling PARAGRAPHS have no such relationship. Paragraph 3 is not part of
    # paragraph 4, and paragraph 4 confirming against T does not mean paragraph 3's
    # content was already represented in that match -- they are independent,
    # coordinate units that can say completely different things. A mechanical port
    # of the same rule (source paragraph's "family" = its enclosing section/
    # subsection's other paragraphs) flags exactly the cases that are actually the
    # real, substantive finding at this granularity: paragraph-density mismatch,
    # where one paper compresses into one paragraph what the other needed several
    # to say. Verified concretely against the corpusstudio/examplore_chi18
    # Introduction pairing: running the ported `redundant_edges()` against that
    # pairing's `fan_in_candidates()` output filtered out ALL THREE real fan-in
    # groups -- including the two already independently confirmed (in the design
    # discussion this class grew out of) to be genuine density-mismatch findings,
    # not noise. A filter whose effect is to erase the exact signal a sibling method
    # exists to surface has failed on its own terms, not merely turned out unneeded
    # -- so it was removed here rather than kept and simply unused.

    def one_to_many_candidates(self) -> list[dict[str, Any]]:
        """Flag paragraph families (a paper's own section/subsection, all its
        paragraphs) whose combined evidence -- confirmed matches AND one-directional
        edges together -- points at TWO OR MORE DISTINCT enclosing sections/
        subsections on the other paper. Direct one-level-deeper port of
        `ClosestMatchGraph.one_to_many_candidates` -- see that method's docstring
        and this module's own docstring for the full rationale, including why a
        paragraph-density mismatch (many paragraphs on one side converging on few
        on the other, all within ONE already-agreed family) does NOT trigger this
        flag on its own -- only distinct far-side FAMILIES count, same discipline
        as the section-level version.

        Returns a list of dicts, one per flagged family:
          - "family": {"paper_id", "section_name", "section_number",
            "subsection_name", "subsection_number"}
          - "far_side_targets": one entry per distinct far-side family this one
            links to, each with that family's identity and the specific evidence
            (confirmed member pairs and/or one-directional edges).
        """
        far_side_links: dict[FamilyKey, dict[FamilyKey, list[dict[str, Any]]]] = {}

        def add_link(source_family: FamilyKey, far_family: FamilyKey, evidence: dict[str, Any]) -> None:
            far_side_links.setdefault(source_family, {}).setdefault(far_family, []).append(evidence)

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
                        "subsection_name": source_family[3],
                        "subsection_number": source_family[4],
                    },
                    "far_side_targets": [
                        {
                            "family": {
                                "paper_id": far_family[0],
                                "section_name": far_family[1],
                                "section_number": far_family[2],
                                "subsection_name": far_family[3],
                                "subsection_number": far_family[4],
                            },
                            "evidence": evidence_list,
                        }
                        for far_family, evidence_list in far_families.items()
                    ],
                }
            )

        flagged.sort(key=lambda f: (f["family"]["paper_id"], f["family"]["section_name"] or "", f["family"]["subsection_name"] or ""))
        return flagged

    def fan_in_candidates(self) -> list[dict[str, Any]]:
        """Flags NODES that TWO OR MORE DISTINCT paragraphs from the SAME other paper
        each independently chose as their own single closest match -- fan-IN onto one
        target, the mirror image of `one_to_many_candidates()`'s fan-OUT (one
        paragraph pointing at 2+ distinct far-side families). Since every paragraph's
        own directional pass can only ever name ONE closest match, at most one of a
        fan-in group's claimants can end up reciprocated (a CONFIRMED member of the
        target's node); the rest are necessarily left as unreciprocated
        `one_directional_match` inbound edges. This shows up often at paragraph
        granularity because papers frequently compress into one paragraph what
        another spreads across several -- see this module's own docstring and the
        README's worked example for real instances (three examplore_chi18 Introduction
        paragraphs (3, 4, 5) all independently choosing corpusstudio's single
        paragraph 4 as their closest match, with only paragraph 4 reciprocated;
        two examplore_chi18 paragraphs (0, 1) both choosing corpusstudio's paragraph 0,
        which reciprocates NEITHER -- its own pick was null).

        Purely a post-hoc read of matches already made; no new API call, no new
        matching logic, and the graph itself is never modified.

        Returns a list of dicts, one per flagged (node, claiming paper) group:
          - "target_members": the node's own member(s) NOT belonging to the claiming
            paper (normally exactly one, in the common two-paper-per-node case; more
            if this node has absorbed confirmed members from more than two papers
            across multiple section pairings).
          - "claiming_paper_id": the paper whose distinct paragraphs are fanning in.
          - "claims": one entry per claiming paragraph -- {"status", "unit", "basis"}.
            `status` is "confirmed" (this specific claim WAS reciprocated -- it's
            itself a member of the target's node) or "one_directional" (left
            stranded). At most one "confirmed" entry ordinarily appears per group;
            often zero, when the target's own pick was null or landed elsewhere
            entirely.
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
                f["target_members"][0].get("paragraph_number") if f["target_members"] else -1,
            )
        )
        return flagged

    def fan_in_correspondence_table(self) -> list[dict[str, Any]]:
        """The paragraph-level sibling of `ClosestMatchGraph.
        fan_in_correspondence_table()` -- see that method's docstring for the shared
        row-inclusion rule (bidirectional node, OR an unreciprocated node still
        flagged by >= 2 distinct claims from the same other paper -- the
        "structurally different" last-row case in the README's own worked example)
        and cell/bold conventions.

        The one structural divergence: NO `redundant_edges()` filtering here. Every
        one-directional claim on a row's node is included as-is -- see this module's
        own "-- redundancy flagging --" comment block for why a ported filter would be
        actively wrong at this granularity (it was verified to erase all three real
        fan-in groups in the corpusstudio/examplore_chi18 Introduction pairing, not
        just redundant noise).

        Returns a list of dicts, UNORDERED, same shape as the section-level sibling:
          - "node_id": the node's graph id.
          - "cells": {paper_id: [(label, is_bidirectional), ...]}, sorted within each
            cell by `paragraph_number` ascending -- unlike the section-level sibling
            (no natural sort order there), a paragraph number gives a real total
            order, and the README's own worked example interleaves the bidirectional
            entry among its unreciprocated neighbors this way (e.g. "¶3, **¶4**, ¶5")
            rather than listing the bidirectional member first.

        A unit's label is always `"¶{paragraph_number}"` -- paragraphs have no
        "(whole)"-vs-subsection distinction to disambiguate, unlike the section-level
        sibling.
        """
        claims_by_node: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for node_id, data in self.graph.nodes(data=True):
            per_paper = claims_by_node.setdefault(node_id, {})
            for member in data["members"]:
                per_paper.setdefault(member["paper_id"], []).append({"status": "bidirectional", "unit": member})
        for _, target_node, _, data in self.graph.edges(keys=True, data=True):
            if data.get("kind") != "one_directional_match":
                continue
            su = data["source_unit"]
            per_paper = claims_by_node.setdefault(target_node, {})
            per_paper.setdefault(su["paper_id"], []).append({"status": "one_directional", "unit": su})

        def unit_label(u: dict[str, Any]) -> str:
            return f"¶{u['paragraph_number']}"

        rows: list[dict[str, Any]] = []
        for node_id, data in self.graph.nodes(data=True):
            members = data["members"]
            is_bidirectional_node = len(members) > 1
            per_paper = claims_by_node.get(node_id, {})
            has_fan_in = any(len(claim_list) >= 2 for claim_list in per_paper.values())
            if not is_bidirectional_node and not has_fan_in:
                continue

            # (paragraph_number, label, is_bidirectional) per cell, sorted
            # numerically, then stripped to the (label, is_bidirectional) shape the
            # renderer wants.
            raw_cells: dict[str, list[tuple[Optional[int], str, bool]]] = {}
            for m in members:
                raw_cells.setdefault(m["paper_id"], []).append(
                    (m.get("paragraph_number"), unit_label(m), is_bidirectional_node)
                )
            for claiming_paper, claim_list in per_paper.items():
                for c in claim_list:
                    if c["status"] != "one_directional":
                        continue
                    u = c["unit"]
                    raw_cells.setdefault(claiming_paper, []).append(
                        (u.get("paragraph_number"), unit_label(u), False)
                    )

            cells: dict[str, list[tuple[str, bool]]] = {}
            for pid, entries in raw_cells.items():
                entries.sort(key=lambda e: (e[0] is None, e[0]))
                cells[pid] = [(label, is_bidirectional) for _, label, is_bidirectional in entries]
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
            "section_pairings_processed": [list(pair) for pair in self.section_pairings_processed],
            "nodes": nodes,
            "edges": edges,
        }

    def save(self, path: Path) -> None:
        path = Path(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.serialize(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "ParagraphMatchGraph":
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError(
                f"{path} has schema_version={payload.get('schema_version')!r}, "
                f"expected {cls.SCHEMA_VERSION!r}"
            )
        instance = cls()
        instance.section_pairings_processed = [tuple(pair) for pair in payload["section_pairings_processed"]]
        for node in payload["nodes"]:
            node_id = node["node_id"]
            data = {k: v for k, v in node.items() if k != "node_id"}
            instance.graph.add_node(node_id, **data)
            for member in data["members"]:
                instance._member_to_node[cls._member_key(member)] = node_id
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
            "section_pairings_processed": len(self.section_pairings_processed),
            "total_nodes": self.graph.number_of_nodes(),
            "merged_nodes": merged_nodes,
            "singleton_nodes": self.graph.number_of_nodes() - merged_nodes,
            "one_directional_edges": self.graph.number_of_edges(),
            "fan_in_groups": len(self.fan_in_candidates()),
        }


def _load_rows(path: Path) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", type=Path, required=True, help="Path to the persistent paragraph-graph JSON file (created if it doesn't exist yet)")
    parser.add_argument("--paper1-id", required=True, help="Literal paper id used as --paper1 in the FIRST directional closest_paragraph_match_within_section.py run")
    parser.add_argument("--paper2-id", required=True, help="Literal paper id used as --paper2 in the FIRST directional run")
    parser.add_argument("--paper1-to-paper2", type=Path, required=True, help="closest-paragraph-match.json from --paper1=paper1-id's chosen section --paper2=paper2-id's chosen section")
    parser.add_argument("--paper2-to-paper1", type=Path, required=True, help="closest-paragraph-match.json from the reverse run (--paper1=paper2-id's chosen section --paper2=paper1-id's chosen section)")
    args = parser.parse_args()

    if args.graph.exists():
        print(f"Loading existing graph: {args.graph}")
        graph = ParagraphMatchGraph.load(args.graph)
    else:
        print(f"No existing graph at {args.graph} -- starting a new one")
        graph = ParagraphMatchGraph()

    if (args.paper1_id, args.paper2_id) in graph.section_pairings_processed:
        print(
            f"NOTE: a section pairing between ({args.paper1_id}, {args.paper2_id}) has already been "
            "added to this graph before. That's expected if you're drilling into multiple different "
            "section pairings between the same two papers -- but re-adding the exact same pairing's "
            "files again will double-count edges/merges.",
            file=sys.stderr,
        )

    a_to_b_rows = _load_rows(args.paper1_to_paper2)
    b_to_a_rows = _load_rows(args.paper2_to_paper1)

    stats = graph.add_section_pairing(args.paper1_id, args.paper2_id, a_to_b_rows, b_to_a_rows)
    graph.save(args.graph)

    print(
        f"Added section pairing ({args.paper1_id}, {args.paper2_id}): "
        f"{stats['merges']} confirmed merges, {stats['one_directional_edges']} one-directional edges"
    )
    print(f"Graph summary after this update: {graph.summary()}")
    print(f"Saved to {args.graph}")


if __name__ == "__main__":
    main()
