"""A variant refinement loop, run for N_EPOCHS = 3 epochs, that differs from
refine_with_epoch_matrices.py in two ways:

1. Pre-epoch seeding: instead of using quote_groups.json's already-computed
   overarching_question (computed by summarize_groups.py from EVERY member
   of a bidirectional-link connected component), this randomly selects only
   ONE paragraph per paper within each connected-component group, and
   recomputes the overarching_question from just those representatives
   (reusing summarize_group() -- already implemented, unchanged -- with its
   same enriched prompt: each representative's own question, its text, and
   its parent section's question). The random pick is seeded deterministically
   (RANDOM_SEED) so re-runs select the same representatives every time --
   summarize_group()'s cache key is the group_id alone, not the members
   passed, so a differently-seeded pick on a later run would otherwise
   silently return a stale cached question for that group_id.

2. Each epoch's ranking-matrix phase computes ONLY Matrix 2 (each
   candidate question's ranking of each paper's own paragraphs) -- Matrix 1
   (each paragraph's own ranking of the candidate questions) is dropped
   entirely, since the M-step never consulted it anyway, cutting ~236
   Claude calls per epoch.

The E-step and M-step themselves are unchanged from
refine_with_epoch_matrices.py: E-step reassigns every paragraph via a
single best-fit choice (assign_paragraph(), reused, under its own
epoch-labeled cache namespace so it never collides with that script's, or
refine_paragraph_groups.py's own, iteration caches); M-step recomputes each
surviving group's question from each paper's Matrix-2 #1-ranked paragraph.

Does NOT touch quote_groups.json or either sibling script's output --
everything is written to its own directory,
output/sections/epoch_random_seed_refinement/.

Usage:
    python3 refine_with_epoch_random_seed.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from section_schema import SectionedPaper
from refine_paragraph_groups import assign_paragraph
from summarize_groups import build_paragraph_lookup, build_section_tag_lookup, summarize_group
from compute_ranking_matrices import (
    DEFAULT_MODEL,
    M2_SYSTEM_TEMPLATE,
    M2_USER_TEMPLATE,
    _build_ranking_tool,
    _rank_with_retry,
)

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"
RUN_DIR = OUTPUT_DIR / "epoch_random_seed_refinement"
CACHE_DIR = OUTPUT_DIR / "_cache" / "epoch_random_seed_refinement"

N_EPOCHS = 3
RANDOM_SEED = 42  # fixed so the pre-epoch random pick -- and therefore its
                  # cached overarching_question -- stays stable across re-runs


def _m2_cache_path(epoch: int, group_id: str, paper_id: str) -> Path:
    return CACHE_DIR / f"epoch{epoch}" / "matrix2" / f"{group_id}__{paper_id}.json"


def rank_paragraphs_for_question(epoch: int, group_id: str, question: str, paper_id: str, paragraphs: list, model: str = DEFAULT_MODEL) -> list[str]:
    cache_path = _m2_cache_path(epoch, group_id, paper_id)
    if cache_path.exists():
        return json.loads(cache_path.read_text())["ranking"]

    unit_ids = [p.id for p in paragraphs]
    listing = "\n".join(
        f'- {p.id}: "{p.tag}" -- "{(p.text or "").replace(chr(10), " ").strip()}"' for p in paragraphs
    )
    system_prompt = M2_SYSTEM_TEMPLATE.format(listing=listing)
    tool = _build_ranking_tool(unit_ids, "a paragraph's unit_id")

    ranking = _rank_with_retry(
        system_prompt, M2_USER_TEMPLATE.format(question=question), tool, unit_ids, model,
        f"epoch{epoch}:{group_id}:{paper_id}",
    )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"ranking": ranking}, indent=2))
    return ranking


def _pick_one_per_paper(members: list[dict], rng: random.Random) -> list[dict]:
    """One randomly-chosen member per paper represented in this group."""
    by_paper: dict[str, list[dict]] = {}
    for m in members:
        by_paper.setdefault(m["paper"], []).append(m)
    return [rng.choice(paper_members) for paper_members in by_paper.values()]


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    paper_ids_in_order = [m["paper_id"] for m in manifest]
    papers = {
        m["paper_id"]: SectionedPaper.model_validate(json.loads((OUTPUT_DIR / m["file"]).read_text()))
        for m in manifest
    }

    paragraph_lookup = build_paragraph_lookup(papers)
    section_tag_lookup = build_section_tag_lookup(papers)

    all_paragraphs = []
    for paper_id in paper_ids_in_order:
        for p in papers[paper_id].paragraphs:
            all_paragraphs.append({"paper": paper_id, "unit_id": p.id, "tag": p.tag, "text": p.text})
    N = len(all_paragraphs)

    quote_groups = json.loads((OUTPUT_DIR / "quote_groups.json").read_text())
    # Only the bidirectional-link connected components (group_id + members)
    # are needed here -- summarize_groups.py's own overarching_question for
    # each group is ignored; a fresh one is computed below from a random
    # single-paragraph-per-paper subsample instead.
    linked_groups = quote_groups.get("paragraphs", [])
    if not linked_groups:
        raise RuntimeError("quote_groups.json has no paragraph groups -- run group_matches.py first")

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(RANDOM_SEED)

    # --- Pre-epoch: random one-paragraph-per-paper seeding ---
    print(f"=== Pre-epoch: seeding {len(linked_groups)} groups from a random paragraph per paper ===")
    initial_snapshot = []
    for group in linked_groups:
        gid = group["group_id"]
        representative_members = _pick_one_per_paper(group["members"], rng)
        overarching = summarize_group(
            gid, representative_members, paragraph_lookup, section_tag_lookup,
            cache_dir=CACHE_DIR / "initial" / "summarize",
        )
        initial_snapshot.append({
            "group_id": gid,
            "overarching_question": overarching,
            "members": group["members"],
            "representative_members": representative_members,
        })
        print(f"  {gid} ({len(group['members'])} members, {len(representative_members)} sampled): {overarching!r}")

    (RUN_DIR / "initial_groups.json").write_text(json.dumps(initial_snapshot, indent=2))
    print(f"wrote {RUN_DIR / 'initial_groups.json'} ({len(initial_snapshot)} groups)")

    candidates = [{"group_id": g["group_id"], "overarching_question": g["overarching_question"]} for g in initial_snapshot]
    prev_assignment: dict[tuple[str, str], str] = {}
    for g in initial_snapshot:
        for m in g["members"]:
            prev_assignment[(m["paper"], m["unit_id"])] = g["group_id"]

    for epoch in range(1, N_EPOCHS + 1):
        epoch_dir = RUN_DIR / f"epoch{epoch}"
        epoch_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== EPOCH {epoch}: {len(candidates)} candidate groups ===")

        # --- Phase 1: E-step (reassign) -- unchanged ---
        print(f"-- E-step: assigning {N} paragraphs --")
        assignment: dict[tuple[str, str], str] = {}
        for p in all_paragraphs:
            key = (p["paper"], p["unit_id"])
            gid = assign_paragraph(f"randomSeedEpochE{epoch}", p["paper"], p["unit_id"], p["tag"], p["text"], candidates)
            if gid is not None:
                assignment[key] = gid

        reassigned = sum(1 for key, gid in assignment.items() if prev_assignment.get(key) != gid)

        members_by_group: dict[str, list[dict]] = {}
        for p in all_paragraphs:
            gid = assignment.get((p["paper"], p["unit_id"]))
            if gid is None:
                continue
            members_by_group.setdefault(gid, []).append({"paper": p["paper"], "unit_id": p["unit_id"], "tag": p["tag"]})

        surviving_candidates = [c for c in candidates if c["group_id"] in members_by_group]
        dropped = [c["group_id"] for c in candidates if c["group_id"] not in members_by_group]
        if dropped:
            print(f"  {len(dropped)} group(s) lost all members and were dropped: {dropped}")

        estep_output = {
            "meta": {"reassigned": reassigned, "total_assigned": len(assignment), "dropped_groups": dropped},
            "candidates_used": candidates,
            "groups": [{"group_id": c["group_id"], "members": members_by_group[c["group_id"]]} for c in surviving_candidates],
        }
        (epoch_dir / "estep.json").write_text(json.dumps(estep_output, indent=2))
        print(f"  E-step: {reassigned}/{len(assignment)} reassigned; wrote {epoch_dir / 'estep.json'}")

        # --- Phase 2: ranking matrix (Matrix 2 only) ---
        print(f"-- Matrix 2: ranking paragraphs for {len(surviving_candidates)} questions across {len(paper_ids_in_order)} papers --")
        matrix2: dict[str, dict[str, list[str]]] = {}
        for paper_id in paper_ids_in_order:
            paper_paragraphs = papers[paper_id].paragraphs
            for c in surviving_candidates:
                gid = c["group_id"]
                ranking = rank_paragraphs_for_question(epoch, gid, c["overarching_question"], paper_id, paper_paragraphs)
                matrix2.setdefault(gid, {})[paper_id] = ranking
        (epoch_dir / "matrix2.json").write_text(json.dumps(matrix2, indent=2))
        print(f"  wrote {epoch_dir / 'matrix2.json'}")

        # --- Phase 3: M-step (re-summarize from Matrix-2-selected representatives) -- unchanged ---
        print(f"-- M-step: recomputing questions for {len(surviving_candidates)} groups --")
        mstep_groups = []
        for c in surviving_candidates:
            gid = c["group_id"]
            representative_members = []
            for paper_id in paper_ids_in_order:
                ranking = matrix2.get(gid, {}).get(paper_id, [])
                if not ranking:
                    continue
                top_unit_id = ranking[0]
                unit = paragraph_lookup.get((paper_id, top_unit_id))
                representative_members.append({"paper": paper_id, "unit_id": top_unit_id, "tag": unit.tag if unit else ""})

            overarching = summarize_group(
                gid, representative_members, paragraph_lookup, section_tag_lookup,
                cache_dir=CACHE_DIR / f"epoch{epoch}" / "mstep",
            )
            mstep_groups.append({"group_id": gid, "overarching_question": overarching, "representative_members": representative_members})
            print(f"  {gid}: {overarching!r} (representatives: {[m['unit_id'] for m in representative_members]})")

        (epoch_dir / "mstep.json").write_text(json.dumps({"groups": mstep_groups}, indent=2))
        print(f"  wrote {epoch_dir / 'mstep.json'}")

        candidates = [{"group_id": g["group_id"], "overarching_question": g["overarching_question"]} for g in mstep_groups]
        prev_assignment = assignment

    print(f"\nDone: {N_EPOCHS} epochs written to {RUN_DIR}")


if __name__ == "__main__":
    main()
