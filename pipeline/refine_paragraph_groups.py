"""Iteratively refines the paragraph groups from quote_groups.json (steps
8-10 of the pipeline). Each iteration:

  1. Assigns EVERY paragraph in EVERY paper (not just ones already in a
     group) to whichever CURRENT group's overarching_question it best
     fits, in a single Claude call per paragraph (like the E-step of a
     clustering loop) -- so a previously-ungrouped paragraph can join a
     group here, and a paragraph already in a group can be reassigned to a
     better-fitting one. A tally of how many paragraphs changed group is
     printed.
  2. Recomputes each surviving group's overarching_question from its new
     membership (the M-step), discarding the old question. Groups that lost
     every member are dropped.

Repeated N_ITERATIONS times. Reuses summarize_group() (and its enriched
paragraph-question + content + parent-section-question prompt) from
summarize_groups.py for step 2.

Step 1 asks for a single best-fit choice rather than a score per candidate
group -- one small enum-constrained output field instead of an array with
one entry per candidate, which cuts output tokens substantially and (as a
side effect) removes the failure mode an earlier per-candidate-scores design
had, where the model would occasionally degenerate into a long run of
malformed array entries. The candidate question list lives in the (cached)
system prompt, identical for every paragraph within one iteration, so
Anthropic's prompt cache -- not application code -- is what keeps re-sending
that list cheap across the ~200+ calls in a given iteration.

Every Claude call -- both the per-paragraph assignment calls and the
per-group resummarization calls -- is cached per iteration under
output/sections/_cache/, and each iteration's full result is saved to
output/sections/paragraph_groups_iter<N>.json before moving to the next --
resuming after a crash or a fresh credit top-up skips everything already
done, no re-calls, and re-running the whole script after full completion
makes no Claude calls at all.

quote_groups.json itself is left untouched (it's the step 6/7 baseline);
final refined output is written separately to
output/sections/paragraph_groups_refined.json.

Usage:
    python3 refine_paragraph_groups.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from anthropic import Anthropic

from cache_utils import cached_system, log_cache_usage
from section_schema import SectionedPaper
from summarize_groups import build_paragraph_lookup, build_section_tag_lookup, summarize_group

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"
CACHE_DIR = OUTPUT_DIR / "_cache"

N_ITERATIONS = 5

ASSIGN_SYSTEM_TEMPLATE = """You are matching ONE paragraph from an academic paper to whichever of a \
fixed set of candidate overarching research questions it fits best. Each candidate question summarizes \
a cluster of related paragraphs pulled from multiple different papers.

Candidate overarching questions:
{listing}

You will be given the paragraph's own role-tag question and its actual text. Choose the SINGLE \
candidate question this paragraph fits best, using its exact group_id."""

ASSIGN_USER_TEMPLATE = """Paragraph question: {tag}

Paragraph content:
\"\"\"
{text}
\"\"\"

Choose this paragraph's best-fitting candidate using the record_best_fit tool."""


def _build_assign_tool(group_ids: list[str]) -> dict:
    return {
        "name": "record_best_fit",
        "description": "Record which single candidate overarching question this paragraph fits best.",
        "input_schema": {
            "type": "object",
            "properties": {
                "group_id": {
                    "type": "string",
                    "enum": group_ids,
                    "description": "the group_id of the single best-fitting candidate question",
                },
            },
            "required": ["group_id"],
        },
    }


def _assign_cache_path(iteration: int, paper_id: str, unit_id: str) -> Path:
    return CACHE_DIR / "paragraph_best_fit" / f"iter{iteration}" / f"{paper_id}__{unit_id}.json"


MAX_ASSIGN_ATTEMPTS = 2


def _call_assign_once(system_prompt: str, tag: str, text: str, group_ids: list[str], model: str) -> str | None:
    client = Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=100,
        system=cached_system(system_prompt),
        messages=[{"role": "user", "content": ASSIGN_USER_TEMPLATE.format(tag=tag, text=text)}],
        tools=[_build_assign_tool(group_ids)],
        tool_choice={"type": "tool", "name": "record_best_fit"},
    )
    log_cache_usage(model, response)

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_best_fit":
            data = block.input
            if set(data.keys()) - {"group_id"} and len(data) == 1:
                data = next(iter(data.values()))
            group_id = data.get("group_id") if isinstance(data, dict) else None
            return group_id if group_id in group_ids else None
    return None


def assign_paragraph(
    iteration: int,
    paper_id: str,
    unit_id: str,
    tag: str,
    text: str,
    candidates: list[dict],
    model: str = DEFAULT_MODEL,
) -> str | None:
    cache_path = _assign_cache_path(iteration, paper_id, unit_id)
    if cache_path.exists():
        return json.loads(cache_path.read_text()).get("group_id")

    group_ids = [c["group_id"] for c in candidates]
    listing = "\n".join(f'- {c["group_id"]}: "{c["overarching_question"]}"' for c in candidates)
    system_prompt = ASSIGN_SYSTEM_TEMPLATE.format(listing=listing)

    group_id = None
    for attempt in range(1, MAX_ASSIGN_ATTEMPTS + 1):
        group_id = _call_assign_once(system_prompt, tag, text, group_ids, model)
        if group_id is not None:
            break
        print(f"    [{paper_id}:{unit_id}] attempt {attempt}/{MAX_ASSIGN_ATTEMPTS}: no valid group_id returned"
              + (" -- retrying" if attempt < MAX_ASSIGN_ATTEMPTS else " -- giving up, paragraph unassigned this iteration"))

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"group_id": group_id}, indent=2))
    return group_id


def _iteration_state_path(iteration: int) -> Path:
    return OUTPUT_DIR / f"paragraph_groups_iter{iteration}.json"


def _all_paragraphs(papers: dict[str, SectionedPaper]) -> list[dict]:
    """Every paragraph in every paper, flattened -- the full population step 8
    assigns against, not just paragraphs already in a quote_groups.json group."""
    out = []
    for paper_id, paper in papers.items():
        for p in paper.paragraphs:
            out.append({"paper": paper_id, "unit_id": p.id, "tag": p.tag, "text": p.text})
    return out


def run_iteration(
    iteration: int,
    candidates: list[dict],
    all_paragraphs: list[dict],
    prev_assignment: dict[tuple[str, str], str],
    paragraph_lookup: dict,
    section_tag_lookup: dict,
) -> dict:
    print(f"\n=== iteration {iteration}: assigning {len(all_paragraphs)} paragraphs to their best-fit among {len(candidates)} candidate groups ===")

    new_assignment: dict[tuple[str, str], str] = {}
    for p in all_paragraphs:
        key = (p["paper"], p["unit_id"])
        group_id = assign_paragraph(iteration, p["paper"], p["unit_id"], p["tag"], p["text"], candidates)
        if group_id is not None:
            new_assignment[key] = group_id

    reassigned = sum(1 for key, gid in new_assignment.items() if prev_assignment.get(key) != gid)
    print(f"[iteration {iteration}] {reassigned}/{len(new_assignment)} paragraphs reassigned to a different group")

    members_by_group: dict[str, list[dict]] = {}
    for p in all_paragraphs:
        gid = new_assignment.get((p["paper"], p["unit_id"]))
        if gid is None:
            continue
        members_by_group.setdefault(gid, []).append({"paper": p["paper"], "unit_id": p["unit_id"], "tag": p["tag"]})

    dropped = [c["group_id"] for c in candidates if c["group_id"] not in members_by_group]
    if dropped:
        print(f"[iteration {iteration}] {len(dropped)} group(s) lost all members and were dropped: {dropped}")

    new_groups = []
    for group_id, members in members_by_group.items():
        overarching = summarize_group(
            group_id, members, paragraph_lookup, section_tag_lookup,
            cache_dir=CACHE_DIR / "group_summaries" / f"iter{iteration}",
        )
        new_groups.append({"group_id": group_id, "members": members, "overarching_question": overarching})
        print(f"  {group_id} ({len(members)} members): {overarching!r}")

    new_groups.sort(key=lambda g: -len(g["members"]))
    return {"meta": {"reassigned": reassigned, "total_assigned": len(new_assignment)}, "groups": new_groups}


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    papers = {
        m["paper_id"]: SectionedPaper.model_validate(json.loads((OUTPUT_DIR / m["file"]).read_text()))
        for m in manifest
    }
    paragraph_lookup = build_paragraph_lookup(papers)
    section_tag_lookup = build_section_tag_lookup(papers)
    all_paragraphs = _all_paragraphs(papers)

    quote_groups = json.loads((OUTPUT_DIR / "quote_groups.json").read_text())
    groups = quote_groups.get("paragraphs", [])
    if not groups or not all(g.get("overarching_question") for g in groups):
        raise RuntimeError("quote_groups.json has no paragraph groups with an overarching_question -- run summarize_groups.py first")

    candidates = [{"group_id": g["group_id"], "overarching_question": g["overarching_question"]} for g in groups]
    assignment: dict[tuple[str, str], str] = {}
    for g in groups:
        for m in g["members"]:
            assignment[(m["paper"], m["unit_id"])] = g["group_id"]

    state = None
    for iteration in range(1, N_ITERATIONS + 1):
        state_path = _iteration_state_path(iteration)
        if state_path.exists():
            print(f"iteration {iteration}: already completed, loading {state_path.name}")
            state = json.loads(state_path.read_text())
        else:
            state = run_iteration(iteration, candidates, all_paragraphs, assignment, paragraph_lookup, section_tag_lookup)
            state_path.write_text(json.dumps(state, indent=2))
            print(f"[iteration {iteration}] wrote {state_path.name}")

        assignment = {}
        for g in state["groups"]:
            for m in g["members"]:
                assignment[(m["paper"], m["unit_id"])] = g["group_id"]
        candidates = [{"group_id": g["group_id"], "overarching_question": g["overarching_question"]} for g in state["groups"]]

    final_path = OUTPUT_DIR / "paragraph_groups_refined.json"
    final_path.write_text(json.dumps(state["groups"], indent=2))
    print(f"\nfinal refined paragraph groups (after {N_ITERATIONS} iterations) written to {final_path}")


if __name__ == "__main__":
    main()
