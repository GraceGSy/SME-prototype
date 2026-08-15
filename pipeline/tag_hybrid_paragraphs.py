"""Fills in each paragraph's `tag` field for the skills+pipeline hybrid run
(see output/sections_skills_hybrid/) -- a lighter-weight sibling of
extract_fine_grained.py's paragraph extraction that only tags, since the
paragraphs themselves (id, text, section_id) were already produced by the
extract-section-paragraphs skill, not by this pipeline's own segmentation.

No paragraph re-segmentation, no start_text marker, no
prev_relation/next_relation -- all explicitly out of scope for this hybrid
run. Same per-section batched call pattern as extract_fine_grained.py: one
Claude call per section, tagging every one of that section's already-known
paragraphs in one shot (keyed by their existing unit_id, not by response
order, so a reordered or incomplete response can't silently mis-tag a
paragraph).

Usage:
    SME_OUTPUT_DIR=output/sections_skills_hybrid python3 tag_hybrid_paragraphs.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from anthropic import Anthropic

from cache_utils import cached_system, log_cache_usage
from section_schema import Section, SectionedPaper

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
OUTPUT_DIR = Path(os.environ.get("SME_OUTPUT_DIR", str(Path(__file__).resolve().parent / "output" / "sections")))
CACHE_DIR = OUTPUT_DIR / "_cache" / "hybrid_paragraph_tags"

SYSTEM_PROMPT = """You are tagging the paragraphs of one section of an academic paper. The paragraphs \
have already been identified and split out for you -- your only job is to give each one a tag, not to \
re-identify paragraph boundaries or edit their text.

For EVERY paragraph given, ask yourself: what question about the research does this paragraph answer, \
or what role does it play in describing the research (e.g. does it explain why the work is needed, what \
was built, how it was tested, what was found, or what it means)? Answer with a short question or phrase \
that captures that role -- NOT a fixed category label. For example: "Why is this problem worth solving?", \
"What system was built?", "How was the system evaluated?", "What did the study find?". Keep it under \
~10 words, and prefer phrasing it as a question when that reads naturally. A paragraph's tag can differ \
from its neighbors' if it plays a distinct role (e.g. a paragraph in a results-focused section can still \
be tagged "What limitation does this reveal?" if it states a caveat)."""

USER_PROMPT_TEMPLATE = """Section tag: {tag}
Section title: {title}

Paragraphs in this section, in order:
{listing}

Give a tag for EVERY paragraph listed above, using the record_paragraph_tags tool."""


def _build_tool(unit_ids: list[str]) -> dict:
    return {
        "name": "record_paragraph_tags",
        "description": "Record a role-tag question for every paragraph listed, keyed by its unit_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "description": "exactly one entry per paragraph listed, each unit_id appearing exactly once",
                    "items": {
                        "type": "object",
                        "properties": {
                            "unit_id": {"type": "string", "enum": unit_ids},
                            "tag": {
                                "type": "string",
                                "description": "a short question or phrase (not a fixed category) capturing what question about the research this paragraph answers",
                            },
                        },
                        "required": ["unit_id", "tag"],
                    },
                },
            },
            "required": ["tags"],
        },
    }


# Matches extract_fine_grained.py's own safety cutoff -- a section whose
# paragraphs sum past this is almost certainly a references/appendix sweep,
# not something worth a full LLM call.
MAX_CHARS_FOR_LLM = 25_000


def _fallback_tags(section: Section, paragraphs: list[Section]) -> dict[str, str]:
    return {p.id: section.tag for p in paragraphs}


def _cache_path(paper_id: str, section_id: str) -> Path:
    return CACHE_DIR / f"{paper_id}__{section_id}.json"


def tag_section_paragraphs(paper_id: str, section: Section, paragraphs: list[Section], model: str = DEFAULT_MODEL) -> dict[str, str]:
    """Returns {unit_id: tag} for every given paragraph. Cached per (paper_id,
    section_id) -- resume-safe, no re-calls on a re-run."""
    cache_path = _cache_path(paper_id, section.id)
    if cache_path.exists():
        print(f"    section {section.id}: using cached response ({cache_path.name})")
        return json.loads(cache_path.read_text())

    def _save(result: dict[str, str]) -> dict[str, str]:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, indent=2))
        return result

    total_chars = sum(len(p.text) for p in paragraphs)
    if total_chars > MAX_CHARS_FOR_LLM:
        print(f"    section {section.id} paragraphs total {total_chars:,} chars -- skipping LLM call, using section tag as a uniform fallback")
        return _save(_fallback_tags(section, paragraphs))

    unit_ids = [p.id for p in paragraphs]
    listing = "\n".join(f'- {p.id}: "{p.text}"' for p in paragraphs)
    tool = _build_tool(unit_ids)

    client = Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        system=cached_system(SYSTEM_PROMPT),
        messages=[{
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(tag=section.tag, title=section.title, listing=listing),
        }],
        tools=[tool],
        tool_choice={"type": "tool", "name": "record_paragraph_tags"},
    )
    log_cache_usage(section.id, response)

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_paragraph_tags":
            data = block.input
            if set(data.keys()) - {"tags"} and len(data) == 1:
                data = next(iter(data.values()))
            entries = data.get("tags", []) if isinstance(data, dict) else []
            result = {e["unit_id"]: e["tag"] for e in entries if isinstance(e, dict) and e.get("unit_id") in unit_ids}
            missing = [uid for uid in unit_ids if uid not in result]
            if missing:
                print(f"    section {section.id}: model omitted {len(missing)} paragraph(s) ({missing}) -- filling with section tag as fallback")
                for uid in missing:
                    result[uid] = section.tag
            return _save(result)

    print(f"    section {section.id}: model did not call record_paragraph_tags -- using section tag as a uniform fallback")
    return _save(_fallback_tags(section, paragraphs))


def process_paper(sectioned: SectionedPaper) -> SectionedPaper:
    paragraphs_by_section: dict[str, list[Section]] = {}
    for p in sectioned.paragraphs:
        paragraphs_by_section.setdefault(p.section_id, []).append(p)

    tags_by_unit_id: dict[str, str] = {}
    for section in sectioned.sections:
        section_paragraphs = paragraphs_by_section.get(section.id, [])
        if not section_paragraphs:
            continue
        tags = tag_section_paragraphs(sectioned.paper_id, section, section_paragraphs)
        tags_by_unit_id.update(tags)
        print(f"    section {section.id} ({section.tag!r}): tagged {len(tags)} paragraphs")

    new_paragraphs = [
        p.model_copy(update={"tag": tags_by_unit_id.get(p.id, p.tag)})
        for p in sectioned.paragraphs
    ]
    return sectioned.model_copy(update={"paragraphs": new_paragraphs})


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    for m in manifest:
        paper_id = m["paper_id"]
        path = OUTPUT_DIR / m["file"]
        sectioned = SectionedPaper.model_validate(json.loads(path.read_text()))

        print(f"[{paper_id}] tagging {len(sectioned.paragraphs)} paragraphs across {len(sectioned.sections)} sections ...")
        updated = process_paper(sectioned)
        path.write_text(json.dumps(updated.model_dump(), indent=2))
        untagged = sum(1 for p in updated.paragraphs if not p.tag)
        print(f"[{paper_id}] wrote {len(updated.paragraphs)} tagged paragraphs" + (f" ({untagged} still empty!)" if untagged else ""))


if __name__ == "__main__":
    main()
