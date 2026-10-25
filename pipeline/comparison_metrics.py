"""Deterministic agreement metrics, not an estimator of semantic correctness."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from itertools import combinations

import networkx as nx


def project_groups(run: dict, level: str, common: set[str]) -> list[dict]:
    parents = {node["group_id"]: node["source_members"] for node in run["groups"]["section"]}
    groups = []
    for node in run["groups"][level]:
        members = sorted(common.intersection(node["source_members"]))
        if not members:
            continue
        parent = node["parent_group_id"]
        if parent is not None and parent not in parents:
            raise ValueError(f"Unknown parent scope: {parent}")
        groups.append(
            {
                "id": node["group_id"],
                "members": members,
                "full_members": node["source_members"],
                "scope": parents[parent] if parent is not None else [],
                "question": node["overarching_question"],
            }
        )
    return sorted(groups, key=lambda group: group["members"])


def _words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold().replace("\u2019", "'")
    return re.findall(r"[^\W_]+(?:'[^\W_]+)?", text)


def question_similarity(rows: list[dict]) -> dict:
    """Fit lexical TF-IDF on these question pairs; no embeddings or model calls."""
    documents = [_words(row[side]) for row in rows for side in ("left", "right")]
    nonempty = [words for words in documents if words]
    frequency = Counter(word for words in nonempty for word in set(words))
    idf = {
        word: math.log((len(nonempty) + 1) / (count + 1)) + 1 for word, count in frequency.items()
    }
    scores = []
    for index, row in enumerate(rows):
        left, right = documents[index * 2 : index * 2 + 2]
        exact = jaccard = cosine = None
        if left and right:
            a, b = set(left), set(right)
            jaccard = len(a & b) / len(a | b)
            exact = left == right
            va, vb = (
                {word: count * idf[word] for word, count in Counter(words).items()}
                for words in (left, right)
            )
            dot = math.fsum(va[word] * vb[word] for word in sorted(a & b))
            norm = math.sqrt(math.fsum(va[word] ** 2 for word in sorted(a))) * math.sqrt(
                math.fsum(vb[word] ** 2 for word in sorted(b))
            )
            cosine = min(1.0, dot / norm)
        scores.append(
            {**row, "normalized_exact": exact, "token_jaccard": jaccard, "tfidf_cosine": cosine}
        )
    valid = [row for row in scores if row["tfidf_cosine"] is not None]
    return {
        "compared": len(valid),
        "missing_left": sum(not _words(row["left"]) for row in rows),
        "missing_right": sum(not _words(row["right"]) for row in rows),
        "normalized_exact_fraction": sum(row["normalized_exact"] for row in valid) / len(valid)
        if valid
        else None,
        "mean_token_jaccard": math.fsum(row["token_jaccard"] for row in valid) / len(valid)
        if valid
        else None,
        "mean_tfidf_cosine": math.fsum(row["tfidf_cosine"] for row in valid) / len(valid)
        if valid
        else None,
        "rows": scores,
    }


def _cross_paper(group: dict, sources: dict) -> bool:
    return len({sources[key]["paper"] for key in group["members"]}) > 1


def _match_graph(groups: list[dict], sources: dict) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from((key, {"source_id": key}) for key in sorted(sources))
    for group in groups:
        graph.add_edges_from(
            (a, b)
            for a, b in combinations(group["members"], 2)
            if sources[a]["paper"] != sources[b]["paper"]
        )
    return graph


def _coverage(graph: nx.Graph, groups: list[dict], sources: dict) -> dict:
    matched = {key for key, degree in graph.degree if degree}
    by_paper = {}
    for paper in sorted({source["paper"] for source in sources.values()}):
        units = {key for key, source in sources.items() if source["paper"] == paper}
        by_paper[paper] = {
            "matched": len(units & matched),
            "total": len(units),
            "fraction": len(units & matched) / len(units),
        }
    return {
        "matched_units": len(matched),
        "total_units": len(sources),
        "fraction": len(matched) / len(sources) if sources else None,
        "cross_paper_groups": sum(_cross_paper(group, sources) for group in groups),
        "cross_paper_pairs": graph.number_of_edges(),
        "by_paper": by_paper,
    }


def _align_groups(left: list[dict], right: list[dict], sources: dict) -> dict:
    """Maximize shared source membership in a one-to-one group alignment."""
    a = [group for group in left if _cross_paper(group, sources)]
    b = [group for group in right if _cross_paper(group, sources)]
    graph = nx.Graph()
    offset = len(a)
    graph.add_nodes_from(range(offset + len(b)))
    for i, old in enumerate(a):
        for j, new in enumerate(b):
            overlap = len(set(old["members"]) & set(new["members"]))
            if overlap:
                graph.add_edge(i, offset + j, weight=overlap)
    # Sorted source memberships and integer node/edge weights make ties repeatable
    # with the pinned NetworkX version; generated group IDs never determine scores.
    matching = nx.max_weight_matching(graph, weight="weight")
    mapping = {min(i, j): max(i, j) - offset for i, j in matching}
    rows = []
    for i, old in enumerate(a):
        new = b[mapping[i]] if i in mapping else None
        shared = sorted(set(old["members"]) & set(new["members"])) if new else []
        union = set(old["members"]) | set(new["members"]) if new else set(old["members"])
        rows.append(
            {
                "left": old,
                "right": new,
                "shared_members": shared,
                "member_jaccard": len(shared) / len(union),
                "left_overlap_count": graph.degree[i],
                "right_overlap_count": graph.degree[offset + mapping[i]] if new else 0,
            }
        )
    for j, new in enumerate(b):
        if j not in mapping.values():
            rows.append(
                {
                    "left": None,
                    "right": new,
                    "shared_members": [],
                    "member_jaccard": 0.0,
                    "left_overlap_count": 0,
                    "right_overlap_count": graph.degree[offset + j],
                }
            )
    questions = question_similarity(
        [
            {
                "members_left": row["left"]["members"],
                "members_right": row["right"]["members"],
                "same_membership": row["left"]["members"] == row["right"]["members"],
                "left": row["left"]["question"],
                "right": row["right"]["question"],
            }
            for row in rows
            if row["left"] and row["right"]
        ]
    )
    return {
        "method": "NetworkX max_weight_matching; maximize shared-member count, not question wording",
        "aligned_groups": len(mapping),
        "unmatched_left": len(a) - len(mapping),
        "unmatched_right": len(b) - len(mapping),
        "left_groups_overlapping_multiple_right": sum(graph.degree[i] > 1 for i in range(offset)),
        "right_groups_overlapping_multiple_left": sum(
            graph.degree[offset + j] > 1 for j in range(len(b))
        ),
        "mean_member_jaccard_with_unmatched_zero": math.fsum(row["member_jaccard"] for row in rows)
        / len(rows)
        if rows
        else None,
        "rows": rows,
        "questions": questions,
    }


def membership_metrics(left: list[dict], right: list[dict], sources: dict) -> dict:
    a, b = _match_graph(left, sources), _match_graph(right, sources)
    shared = nx.intersection(a, b)
    edits = nx.symmetric_difference(a, b)
    old = {tuple(sorted(edge)) for edge in a.edges}
    new = {tuple(sorted(edge)) for edge in b.edges}
    union = old | new
    active = [key for key in sorted(sources) if a.degree[key] or b.degree[key]]
    peer_agreement = [
        len(set(a[key]) & set(b[key])) / len(set(a[key]) | set(b[key])) for key in active
    ]
    return {
        "coverage": {"left": _coverage(a, left, sources), "right": _coverage(b, right, sources)},
        "graph": {
            "networkx_version": nx.__version__,
            "definition": "Fixed source IDs are nodes; an edge means cross-paper co-membership",
            "identity_isomorphic": nx.is_isomorphic(
                a, b, node_match=nx.algorithms.isomorphism.categorical_node_match("source_id", None)
            ),
            "fixed_identity_edge_edits": edits.number_of_edges(),
            "unchanged_pairs": shared.number_of_edges(),
            "added_pairs": sorted(new - old),
            "removed_pairs": sorted(old - new),
            "pair_jaccard": shared.number_of_edges() / len(union) if union else None,
            "pair_f1_agreement": 2 * shared.number_of_edges() / (len(old) + len(new))
            if old or new
            else None,
            "baseline_pair_retention": shared.number_of_edges() / len(old) if old else None,
            "new_pair_overlap_with_baseline": shared.number_of_edges() / len(new) if new else None,
            "active_units": len(active),
            "mean_peer_jaccard_active_units": math.fsum(peer_agreement) / len(peer_agreement)
            if peer_agreement
            else None,
            "gained_coverage": sorted(
                key for key in sources if not a.degree[key] and b.degree[key]
            ),
            "lost_coverage": sorted(key for key in sources if a.degree[key] and not b.degree[key]),
        },
        "group_alignment": _align_groups(left, right, sources),
    }
