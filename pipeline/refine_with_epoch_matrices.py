"""A variant refinement loop, run for N_EPOCHS = 3 epochs, that differs from
refine_paragraph_groups.py in how the M-step recomputes each group's
overarching_question. Does NOT touch quote_groups.json, refine_paragraph_
groups.py's output, or compute_ranking_matrices.py's output -- everything is
written to its own directory, output/sections/epoch_matrix_refinement/.

Before any epoch runs, the starting point (quote_groups.json's paragraph
groups and their overarching_question) is saved as initial_groups.json.

Each epoch does three phases, each saved to its own file so the whole
process can be replayed/inspected step by step:

1. E-step (reassign): for every paragraph in every paper, one Claude call
   picks the single best-fitting group from the CURRENT candidate list
   (reuses assign_paragraph() from refine_paragraph_groups.py, under its
   own epoch-labeled cache namespace so it never collides with that
   script's own iteration cache). -> epoch<N>/estep.json

2. Ranking matrices: recomputes BOTH ranking matrices from scratch against
   THIS epoch's surviving candidates (groups that kept at least one E-step
   member) -- Matrix 1 (every paragraph's own ranking of the candidate
   questions) and Matrix 2 (every candidate question's ranking of each
   paper's own paragraphs). Reuses the prompt templates and retry/
   validation logic from compute_ranking_matrices.py, but with a fresh
   epoch-scoped cache (that script's own cache has no epoch dimension at
   all, so reusing it here would silently serve stale rankings computed
   against a different candidate set). -> epoch<N>/matrix1.json,
   epoch<N>/matrix2.json

3. M-step (re-summarize): for each surviving group, and for each paper,
   picks that PAPER's #1-ranked paragraph for this group's question --
   from Matrix 2, just computed in phase 2 -- as that paper's
   representative, regardless of what the E-step assigned it to. (Up to 3
   representatives per group, one per paper.) These representatives -- not
   the E-step's broader membership -- are what's fed into summarize_group()
   (same enriched prompt as step 7: each representative's own question,
   its text, and its parent section's question) to get the new
   overarching_question. -> epoch<N>/mstep.json

The next epoch's candidate list is the M-step's surviving group_ids with
their new overarching_question. All calls are cached per item, so a
crashed or interrupted run resumes from exactly where it left off.

Usage:
    python3 refine_with_epoch_matrices.py
"""
from __future__ import annotations

import json
from pathlib import Path

from section_schema import SectionedPaper
from refine_paragraph_groups import assign_paragraph
from summarize_groups import build_paragraph_lookup, build_section_tag_lookup, summarize_group
from compute_ranking_matrices import (
    DEFAULT_MODEL,
    M1_SYSTEM_TEMPLATE,
    M1_USER_TEMPLATE,
    M2_SYSTEM_TEMPLATE,
    M2_USER_TEMPLATE,
    _build_ranking_tool,
    _rank_with_retry,
)

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"
RUN_DIR = OUTPUT_DIR / "epoch_matrix_refinement"
CACHE_DIR = OUTPUT_DIR / "_cache" / "epoch_matrix_refinement"

N_EPOCHS = 3


def _m1_cache_path(epoch: int, paper_id: str, unit_id: str) -> Path:
    return CACHE_DIR / f"epoch{epoch}" / "matrix1" / f"{paper_id}__{unit_id}.json"


def rank_questions_for_paragraph(epoch: int, paper_id: str, unit_id: str, tag: str, text: str, candidates: list[dict], model: str = DEFAULT_MODEL) -> list[str]:
    cache_path = _m1_cache_path(epoch, paper_id, unit_id)
    if cache_path.exists():
        return json.loads(cache_path.read_text())["ranking"]

    group_ids = [c["group_id"] for c in candidates]
    listing = "\n".join(f'- {c["group_id"]}: "{c["overarching_question"]}"' for c in candidates)
    system_prompt = M1_SYSTEM_TEMPLATE.format(listing=listing)
    tool = _build_ranking_tool(group_ids, "a candidate question's group_id")

    ranking = _rank_with_retry(
        system_prompt, M1_USER_TEMPLATE.format(tag=tag, text=text), tool, group_ids, model,
        f"epoch{epoch}:{paper_id}:{unit_id}",
    )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"ranking": ranking}, indent=2))
    return ranking


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
    initial_groups = quote_groups.get("paragraphs", [])
    if not initial_groups or not all(g.get("overarching_question") for g in initial_groups):
        raise RuntimeError("quote_groups.json has no paragraph groups with an overarching_question -- run summarize_groups.py first")

    RUN_DIR.mkdir(parents=True, exist_ok=True)

    # Save the initial groups/questions snapshot before any epoch runs.
    initial_snapshot = [
        {"group_id": g["group_id"], "overarching_question": g["overarching_question"], "members": g["members"]}
        for g in initial_groups
    ]
    (RUN_DIR / "initial_groups.json").write_text(json.dumps(initial_snapshot, indent=2))
    print(f"wrote {RUN_DIR / 'initial_groups.json'} ({len(initial_snapshot)} groups)")

    candidates = [{"group_id": g["group_id"], "overarching_question": g["overarching_question"]} for g in initial_groups]
    prev_assignment: dict[tuple[str, str], str] = {}
    for g in initial_groups:
        for m in g["members"]:
            prev_assignment[(m["paper"], m["unit_id"])] = g["group_id"]

    for epoch in range(1, N_EPOCHS + 1):
        epoch_dir = RUN_DIR / f"epoch{epoch}"
        epoch_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== EPOCH {epoch}: {len(candidates)} candidate groups ===")

        # --- Phase 1: E-step (reassign) ---
        print(f"-- E-step: assigning {N} paragraphs --")
        assignment: dict[tuple[str, str], str] = {}
        for p in all_paragraphs:
            key = (p["paper"], p["unit_id"])
            gid = assign_paragraph(f"epochE{epoch}", p["paper"], p["unit_id"], p["tag"], p["text"], candidates)
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

        # --- Phase 2: ranking matrices (recomputed fresh against this epoch's surviving candidates) ---
        print(f"-- Matrix 1: ranking {len(surviving_candidates)} questions for {N} paragraphs --")
        matrix1: dict[str, list[str]] = {}
        for p in all_paragraphs:
            key = f'{p["paper"]}:{p["unit_id"]}'
            matrix1[key] = rank_questions_for_paragraph(epoch, p["paper"], p["unit_id"], p["tag"], p["text"], surviving_candidates)
        (epoch_dir / "matrix1.json").write_text(json.dumps(matrix1, indent=2))
        print(f"  wrote {epoch_dir / 'matrix1.json'}")

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

        # --- Phase 3: M-step (re-summarize from Matrix-2-selected representatives) ---
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
