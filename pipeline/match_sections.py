"""Simpler stage 2: for every pair of papers, link units (sections, or --
now -- paragraphs) whose combined entity + content similarity make them each
other's closest match -- and only keep the link if it holds in both
directions (reciprocal / mutual best match). No relational structure, no
arc-consistency, no kernels: just a per-unit similarity score.

Matching always happens within one granularity at a time: sections only
match other sections, paragraphs only match paragraphs. Cross-granularity
matching is never done.

"Entity similarity" is computed differently depending on granularity:
  - sections have only one tag, so they use fuzzy text similarity on it
    (near-synonyms like "related-work" vs. "background" still score partial
    credit).
  - paragraphs carry three tags (role `tag`, `prev_relation`, `next_relation`),
    so entity similarity there is literally "what percentage of these three
    tags match exactly" -- see entity_similarity() below.
"""
from __future__ import annotations

import itertools
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

from align_graphs import text_similarity
from section_schema import GRANULARITIES, SectionedPaper

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"

TAG_WEIGHT = 0.5
CONTENT_WEIGHT = 0.5

_WORD_RE = re.compile(r"[a-z0-9]+")
# common academic-prose words filtered out so content similarity reflects shared
# topic vocabulary rather than shared grammar
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "were",
    "be", "been", "being", "this", "that", "these", "those", "with", "as", "by", "we", "our",
    "it", "its", "which", "from", "at", "also", "can", "could", "have", "has", "had", "not",
    "but", "such", "using", "use", "used", "based", "other", "more", "most", "one", "two",
    "three", "between", "both", "than", "into", "how", "what", "each", "their", "they", "them",
}


@lru_cache(maxsize=None)
def _content_tokens(text: str) -> frozenset[str]:
    return frozenset(w for w in _WORD_RE.findall(text.lower()) if w not in STOPWORDS and len(w) > 2)


def content_similarity(text_a: str, text_b: str) -> float:
    ta, tb = _content_tokens(text_a), _content_tokens(text_b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def entity_similarity(sa, sb, granularity: str) -> float:
    """Sections: fuzzy similarity on the single role tag. Paragraphs: the
    fraction of the three tags (tag, prev_relation, next_relation) that match
    exactly, compared positionally (role vs. role, prev vs. prev, next vs.
    next) -- an empty slot on either side never counts as a match."""
    if granularity == "sections":
        return text_similarity(sa.tag, sb.tag)

    slots_a = (sa.tag, sa.prev_relation, sa.next_relation)
    slots_b = (sb.tag, sb.prev_relation, sb.next_relation)
    matches = sum(
        1 for x, y in zip(slots_a, slots_b)
        if x and y and x.strip().lower() == y.strip().lower()
    )
    return matches / len(slots_a)


def unit_similarity(sa, sb, granularity: str) -> tuple[float, float, float]:
    """Returns (combined, entity_similarity, content_similarity)."""
    entity_sim = entity_similarity(sa, sb, granularity)
    content_sim = content_similarity(sa.text, sb.text)
    combined = TAG_WEIGHT * entity_sim + CONTENT_WEIGHT * content_sim
    return combined, entity_sim, content_sim


def best_matches(units_a: list, units_b: list, granularity: str) -> dict[str, set[str]]:
    """For each unit in A, the set of B-unit ids tied for the highest combined similarity."""
    result = {}
    for sa in units_a:
        if not units_b:
            result[sa.id] = set()
            continue
        scored = [(sb.id, unit_similarity(sa, sb, granularity)[0]) for sb in units_b]
        best_score = max(score for _, score in scored)
        result[sa.id] = {sid for sid, score in scored if score == best_score}
    return result


def match_units(paper_a: SectionedPaper, paper_b: SectionedPaper, granularity: str) -> list[dict]:
    units_a = getattr(paper_a, granularity)
    units_b = getattr(paper_b, granularity)
    a_by_id = {s.id: s for s in units_a}
    b_by_id = {s.id: s for s in units_b}
    a_best = best_matches(units_a, units_b, granularity)
    b_best = best_matches(units_b, units_a, granularity)

    links = []
    for sa_id, candidates in a_best.items():
        for sb_id in candidates:
            # keep only if the match is mutual: sb's own best match(es) include sa back
            if sa_id in b_best.get(sb_id, set()):
                sa, sb = a_by_id[sa_id], b_by_id[sb_id]
                combined, entity_sim, content_sim = unit_similarity(sa, sb, granularity)
                links.append({
                    "paper_a": paper_a.paper_id, "section_a": sa.id, "title_a": sa.title, "tag_a": sa.tag,
                    "paper_b": paper_b.paper_id, "section_b": sb.id, "title_b": sb.title, "tag_b": sb.tag,
                    "similarity": round(combined, 3),
                    "entity_similarity": round(entity_sim, 3),
                    "content_similarity": round(content_sim, 3),
                })
    return links


def _load(path: Path) -> SectionedPaper:
    return SectionedPaper.model_validate(json.loads(path.read_text()))


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    papers = {m["paper_id"]: _load(OUTPUT_DIR / m["file"]) for m in manifest}

    ids = list(papers.keys())
    if len(sys.argv) > 1:
        ids = sys.argv[1:]

    all_links: dict[str, list[dict]] = {}
    for granularity in GRANULARITIES:
        links_for_granularity = []
        for id_a, id_b in itertools.combinations(ids, 2):
            links = match_units(papers[id_a], papers[id_b], granularity)
            links_for_granularity.append(links)
            print(f"[{granularity}] {id_a} <-> {id_b}: {len(links)} mutual links")
            if granularity == "sections":  # only the small, human-readable granularity gets full printout
                for link in links:
                    print(
                        f"    [{link['tag_a']}] {link['title_a']!r}  <->  [{link['tag_b']}] {link['title_b']!r}  "
                        f"(combined={link['similarity']}, entity={link['entity_similarity']}, content={link['content_similarity']})"
                    )
        all_links[granularity] = [link for links in links_for_granularity for link in links]

    out_path = OUTPUT_DIR / "links.json"
    out_path.write_text(json.dumps(all_links, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
