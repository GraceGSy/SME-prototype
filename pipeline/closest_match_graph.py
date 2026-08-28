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
