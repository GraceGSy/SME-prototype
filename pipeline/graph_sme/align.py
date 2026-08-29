"""Stage 2: SME-style structural alignment between two PaperGraphs.

Mirrors Falkenhainer/Forbus/Gentner's Structure-Mapping Engine, adapted to the
free-text entities/propositions produced by stage 1. This module is deliberately
a pure, deterministic graph algorithm -- no LLM calls -- since SME itself
operates purely on top of representations someone else already produced.

  1. Local match (structurally blind): candidate correspondences are entity
     pairs of the same `kind`, and proposition pairs with the same `predicate`
     and arity. This is deliberately permissive about entity *names* -- entity
     correspondence is not gated on name similarity, since cross-paper analogy
     is exactly the case where the same role is filled by differently-named
     things (EXAMPLORE vs. ParaLib vs. the ChainForge fork, all "system").

  2. Parallel connectivity (structural consistency): a proposition pair only
     survives if, position by position, its arguments correspond too -- an
     entity arg needs an entity candidate pair; a proposition arg needs a
     *surviving* proposition candidate pair (higher-order relations must
     themselves be consistent). Computed by iterating to a fixed point, like
     arc-consistency in a CSP.

  3. Kernels: connected components over the surviving correspondences (a
     proposition correspondence is linked to the correspondences of its own
     arguments), mirroring SME's "small structurally consistent submappings."

  4. Systematicity-weighted greedy merge: kernels are scored by size and by
     how many higher-order (deeply connected) propositions they contain, then
     accepted greedily in that order subject to a global one-to-one
     constraint -- the largest, most deeply connected kernels win first.
"""
from __future__ import annotations

import difflib
import itertools
import json
import re
import sys
from pathlib import Path

from .models import PaperGraph

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set[str]:
    return set(_WORD_RE.findall(s.lower()))


def text_similarity(a: str, b: str) -> float:
    """Cheap, dependency-free lexical similarity in [0, 1]. Used only for
    scoring/reporting -- never as a hard filter on candidate correspondences."""
    ta, tb = _tokens(a), _tokens(b)
    jaccard = len(ta & tb) / len(ta | tb) if (ta or tb) else 0.0
    ratio = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return 0.5 * jaccard + 0.5 * ratio


# ---------------------------------------------------------------------------
# Stage 1: local, structurally blind candidate generation
# ---------------------------------------------------------------------------

KIND_MATCH_BONUS = 0.2


def entity_candidates(graph_a: PaperGraph, graph_b: PaperGraph) -> dict[tuple[str, str], float]:
    """Every entity pair is a candidate -- `kind` is only a scoring bonus, not a
    filter. In practice extraction-time `kind` labels aren't a controlled
    vocabulary shared across independently-extracted papers (e.g. one paper's
    introduced system gets tagged "system", another's gets tagged "tool"), so
    gating on exact kind equality silently kills real correspondences. Letting
    parallel connectivity + kernel size do the real filtering is more faithful
    to how SME actually finds correspondences: through structural role, not a
    category label."""
    cands = {}
    for ea in graph_a.entities:
        for eb in graph_b.entities:
            score = text_similarity(ea.name, eb.name)
            if ea.kind == eb.kind:
                score += KIND_MATCH_BONUS
            cands[(ea.id, eb.id)] = score
    return cands


def proposition_candidates(graph_a: PaperGraph, graph_b: PaperGraph) -> set[tuple[str, str]]:
    by_pred_b: dict[tuple[str, int], list] = {}
    for p in graph_b.propositions:
        by_pred_b.setdefault((p.predicate.lower(), len(p.args)), []).append(p)
    cands = set()
    for pa in graph_a.propositions:
        key = (pa.predicate.lower(), len(pa.args))
        for pb in by_pred_b.get(key, []):
            cands.add((pa.id, pb.id))
    return cands


# ---------------------------------------------------------------------------
# Stage 2: parallel connectivity (arc-consistency style fixed point)
# ---------------------------------------------------------------------------

def enforce_parallel_connectivity(
    graph_a: PaperGraph,
    graph_b: PaperGraph,
    prop_cands: set[tuple[str, str]],
    entity_cands: dict[tuple[str, str], float],
) -> set[tuple[str, str]]:
    a_props = {p.id: p for p in graph_a.propositions}
    b_props = {p.id: p for p in graph_b.propositions}
    a_entity_ids = {e.id for e in graph_a.entities}
    b_entity_ids = {e.id for e in graph_b.entities}
    entity_cand_set = set(entity_cands.keys())

    surviving = set(prop_cands)
    changed = True
    while changed:
        changed = False
        for pa_id, pb_id in list(surviving):
            pa, pb = a_props[pa_id], b_props[pb_id]
            consistent = True
            for arg_a, arg_b in zip(pa.args, pb.args):
                a_is_entity = arg_a in a_entity_ids
                b_is_entity = arg_b in b_entity_ids
                if a_is_entity != b_is_entity:
                    consistent = False
                    break
                if a_is_entity:
                    if (arg_a, arg_b) not in entity_cand_set:
                        consistent = False
                        break
                else:
                    if (arg_a, arg_b) not in surviving:
                        consistent = False
                        break
            if not consistent:
                surviving.discard((pa_id, pb_id))
                changed = True
    return surviving


# ---------------------------------------------------------------------------
# Stage 3: kernels (each surviving proposition correspondence's own
# structurally-required closure)
# ---------------------------------------------------------------------------

def build_kernels(
    graph_a: PaperGraph,
    graph_b: PaperGraph,
    prop_cands: set[tuple[str, str]],
) -> list[list[tuple[str, str, str]]]:
    """One kernel per surviving proposition correspondence: the correspondence
    itself plus everything its own specific arguments require (entity
    correspondences directly, or -- recursively -- the closures of whichever
    other proposition correspondences fill its higher-order argument slots).

    This is deliberately *not* "connected components over all shared
    arguments": two proposition correspondences that both happen to touch the
    same entity are not necessarily compatible -- e.g. four different
    `measures(study, X)` candidates in B all share the same `study` argument
    but disagree, pairwise, on what X is. Grouping by naive shared-argument
    connectivity would silently merge those mutually exclusive alternatives
    into one kernel and violate one-to-one correspondence. Building one
    self-contained closure per top-level correspondence keeps each kernel
    internally consistent by construction (each argument slot has exactly one
    concrete binding); reconciling *competing* kernels that all try to bind
    the same id to different partners is left to the merge step.
    """
    a_props = {p.id: p for p in graph_a.propositions}
    b_props = {p.id: p for p in graph_b.propositions}
    a_entity_ids = {e.id for e in graph_a.entities}

    def closure(pa_id: str, pb_id: str, seen: frozenset) -> set[tuple[str, str, str]]:
        node = ("proposition", pa_id, pb_id)
        if node in seen:
            return set()
        seen = seen | {node}
        nodes = {node}
        pa, pb = a_props[pa_id], b_props[pb_id]
        for arg_a, arg_b in zip(pa.args, pb.args):
            if arg_a in a_entity_ids:
                nodes.add(("entity", arg_a, arg_b))
            else:
                nodes |= closure(arg_a, arg_b, seen)
        return nodes

    return [list(closure(pa_id, pb_id, frozenset())) for pa_id, pb_id in prop_cands]


# ---------------------------------------------------------------------------
# Stage 4: systematicity-weighted greedy merge (global one-to-one)
# ---------------------------------------------------------------------------

ENTITY_SIM_WEIGHT = 0.3


def score_kernel(
    kernel: list[tuple[str, str, str]],
    orders_a: dict[str, int],
    orders_b: dict[str, int],
    entity_cands: dict[tuple[str, str], float] | None = None,
) -> float:
    """Reward both size and depth: a proposition correspondence is worth more
    the higher its order on either side (the systematicity principle -- prefer
    deeply interconnected structure over a pile of first-order attributes).
    A small entity-name-similarity term breaks ties between otherwise
    structurally-equal competing kernels (e.g. picking which of several
    `measures(study, ?)` candidates is the *best* one) without ever gating
    correspondence on name similarity outright."""
    score = 0.0
    n_entities = 0
    for kind, a_id, b_id in kernel:
        if kind == "proposition":
            score += 1 + orders_a.get(a_id, 0) + orders_b.get(b_id, 0)
        else:
            n_entities += 1
            if entity_cands is not None:
                score += ENTITY_SIM_WEIGHT * entity_cands.get((a_id, b_id), 0.0)
    score += 0.5 * n_entities
    return score


def merge_kernels(
    kernels: list[list[tuple[str, str, str]]],
    scores: list[float],
) -> list[list[tuple[str, str, str]]]:
    """Greedily accept kernels in descending score order, subject to a global
    one-to-one constraint. Unlike a plain "used ids" set, this tracks actual
    *bindings* (a_id -> b_id): a kernel that only reuses ids with the exact
    same partner as an already-accepted kernel is compatible (convergent
    evidence for the same correspondence) and gets merged in; a kernel that
    would bind an already-used id to a *different* partner is a genuine
    conflict and is rejected."""
    order = sorted(range(len(kernels)), key=lambda i: scores[i], reverse=True)
    a_to_b: dict[str, str] = {}
    b_to_a: dict[str, str] = {}
    accepted = []
    for i in order:
        kernel = kernels[i]
        compatible = True
        for _, a_id, b_id in kernel:
            if a_to_b.get(a_id, b_id) != b_id or b_to_a.get(b_id, a_id) != a_id:
                compatible = False
                break
        if not compatible:
            continue
        accepted.append(kernel)
        for _, a_id, b_id in kernel:
            a_to_b[a_id] = b_id
            b_to_a[b_id] = a_id
    return accepted


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def align(graph_a: PaperGraph, graph_b: PaperGraph) -> dict:
    entity_cands = entity_candidates(graph_a, graph_b)
    prop_cands_raw = proposition_candidates(graph_a, graph_b)
    prop_cands = enforce_parallel_connectivity(graph_a, graph_b, prop_cands_raw, entity_cands)
    kernels = build_kernels(graph_a, graph_b, prop_cands)

    orders_a = graph_a.proposition_orders()
    orders_b = graph_b.proposition_orders()
    scores = [score_kernel(k, orders_a, orders_b, entity_cands) for k in kernels]
    accepted = merge_kernels(kernels, scores)

    # Accepted kernels can legitimately overlap (convergent, *consistent* evidence
    # for the same correspondence from multiple angles), so dedupe by (a, b) before
    # reporting -- otherwise the same correspondence could be listed more than once.
    entity_seen: dict[str, dict] = {}
    prop_seen: dict[str, dict] = {}
    for kernel in accepted:
        for kind, a_id, b_id in kernel:
            if kind == "entity":
                entity_seen[a_id] = {"a": a_id, "b": b_id, "name_similarity": round(entity_cands.get((a_id, b_id), 0.0), 3)}
            else:
                prop_seen[a_id] = {"a": a_id, "b": b_id, "order_a": orders_a.get(a_id, 0), "order_b": orders_b.get(b_id, 0)}
    entity_map = sorted(entity_seen.values(), key=lambda x: -x["name_similarity"])
    prop_map = sorted(prop_seen.values(), key=lambda x: -(x["order_a"] + x["order_b"]))

    total_score = sum(1 + p["order_a"] + p["order_b"] for p in prop_map) + 0.5 * len(entity_map)
    denom = min(len(graph_a.propositions), len(graph_b.propositions)) or 1
    avg_name_sim = (sum(e["name_similarity"] for e in entity_map) / len(entity_map)) if entity_map else 0.0

    return {
        "paper_a": graph_a.paper_id,
        "paper_b": graph_b.paper_id,
        "entity_correspondences": entity_map,
        "proposition_correspondences": prop_map,
        "num_kernels_considered": len(kernels),
        "num_kernels_accepted": len(accepted),
        "systematicity_score": round(total_score, 2),
        "normalized_score": round(total_score / denom, 3),
        "avg_entity_name_similarity": round(avg_name_sim, 3),
        # rough illustrative cut: high average name similarity across the matched
        # entities suggests a literal-similarity match; low similarity with real
        # structural overlap suggests a purely relational analogy (Gentner's
        # literal-similarity vs. analogy distinction is one dial, not two mechanisms)
        "classification": "literal-similarity" if avg_name_sim >= 0.35 else "analogy",
    }


def _load_graph(output_dir: Path, filename: str) -> PaperGraph:
    return PaperGraph.model_validate(json.loads((output_dir / filename).read_text()))


def main() -> None:
    output_dir = Path(__file__).resolve().parent / "output"
    manifest = json.loads((output_dir / "manifest.json").read_text())
    graphs = {m["paper_id"]: _load_graph(output_dir, m["file"]) for m in manifest}

    ids = list(graphs.keys())
    if len(sys.argv) > 1:
        ids = sys.argv[1:]

    results = []
    for id_a, id_b in itertools.combinations(ids, 2):
        result = align(graphs[id_a], graphs[id_b])
        results.append(result)
        print(
            f"{id_a} <-> {id_b}: {result['num_kernels_accepted']}/{result['num_kernels_considered']} kernels accepted, "
            f"systematicity={result['systematicity_score']} (normalized {result['normalized_score']}), "
            f"{len(result['entity_correspondences'])} entity + {len(result['proposition_correspondences'])} proposition "
            f"correspondences, avg name similarity={result['avg_entity_name_similarity']} -> {result['classification']}"
        )

    out_path = output_dir / "alignments.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
