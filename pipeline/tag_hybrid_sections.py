"""Fills in each section's `tag` field for the papers3 rebuild (see
output/sections_skills_hybrid_papers3/) by implementing the
annotate-section-questions-given-paragraphs skill directly: for every
section, read ALL of its already-extracted paragraphs and compose one
role-based question the section exists to answer in the paper's argument --
never a restatement of its title, never a content/topic summary.

One Claude call per section (same per-item granularity as
tag_hybrid_paragraphs.py), giving that section's full attention rather than
batching many sections' worth of paragraphs into one call.

Usage:
    SME_OUTPUT_DIR=output/sections_skills_hybrid_papers3 python3 tag_hybrid_sections.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from anthropic import Anthropic

from cache_utils import cached_system, log_cache_usage
from section_schema import SectionedPaper

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
OUTPUT_DIR = Path(os.environ.get("SME_OUTPUT_DIR", str(Path(__file__).resolve().parent / "output" / "sections")))
CACHE_DIR = OUTPUT_DIR / "_cache" / "hybrid_section_tags"

SYSTEM_PROMPT = """You are composing one role-based question for a section of an academic paper, using \
ONLY the section's already-extracted paragraphs -- you are not given the raw PDF, and none is needed.

Read every paragraph in the section, not just the first or most prominent one. Then write one question \
this section exists to answer in the paper's argument -- ask "what job is this section doing -- what \
does the reader need answered before moving to the next part of the paper?" not "what topic does this \
section cover?"

- Frame the question around the section's function in the paper's arc, not a restatement of its title or \
a content summary.
- The question must span ALL of the section's paragraphs, not just the first or most prominent one. If \
the paragraphs cover several related jobs (e.g. separate paragraphs for different system components, or \
different sub-studies), find the broader question that covers all of them. If the paragraphs are \
different enough that no single question honestly covers all of them, say so explicitly in the question \
rather than silently narrowing it.
- Watch for a single connecting verb-frame that's topically complete but type-narrow. A section can name \
every sub-topic and still silently exclude a different kind of content coexisting with it -- e.g. a \
qualitative-results section built from interview coding often reports both what participants did \
(behavior/usage) and how they felt about it (confidence, satisfaction, perception), sometimes in the \
same paragraph. Before finalizing, check each paragraph for what TYPE of finding it reports (behavior \
vs. attitude/experience vs. both), not just which topic it belongs to.
- Keep the question short and genuinely open -- don't embed the answer inside the question itself. A \
question padded with an em-dash aside or parenthetical listing out specifics has stopped being a \
question; it's an answer wearing a question mark. If you're tempted to reach for a dash, colon, or \
parenthetical full of specifics, that detail belongs in your own understanding of the section, not in \
the question text -- a genuine question doesn't give away its own answer.
- Even thin sections with only one or two short paragraphs (Acknowledgments, a one-paragraph Abstract) \
get a real, honest question rather than being skipped.
- This question should be usable on its own, without the reader having the section's content in front of \
them -- write it so it stands alone."""

USER_PROMPT_TEMPLATE = """Section title: {title}

Paragraphs in this section, in order:
{listing}

Compose the one question this section exists to answer, using the record_section_question tool."""


def _build_tool() -> dict:
    return {
        "name": "record_section_question",
        "description": "Record the one role-based question this section exists to answer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "a short, genuinely open question capturing this section's role in the paper's argument -- not a topic summary, not self-answering",
                },
            },
            "required": ["question"],
        },
    }


def _cache_path(paper_id: str, section_id: str) -> Path:
    return CACHE_DIR / f"{paper_id}__{section_id}.json"


def tag_section(paper_id: str, section_id: str, title: str, paragraphs: list, model: str = DEFAULT_MODEL) -> str:
    cache_path = _cache_path(paper_id, section_id)
    if cache_path.exists():
        print(f"    section {section_id}: using cached response")
        return json.loads(cache_path.read_text())["question"]

    listing = "\n\n".join(p.text for p in paragraphs)
    client = Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=300,
        system=cached_system(SYSTEM_PROMPT),
        messages=[{
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(title=title, listing=listing),
        }],
        tools=[_build_tool()],
        tool_choice={"type": "tool", "name": "record_section_question"},
    )
    log_cache_usage(section_id, response)

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_section_question":
            data = block.input
            if set(data.keys()) - {"question"} and len(data) == 1:
                data = next(iter(data.values()))
            question = data.get("question", "") if isinstance(data, dict) else ""
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"question": question}, indent=2))
            return question

    raise RuntimeError(f"Model did not call record_section_question for section {section_id!r}")


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    for m in manifest:
        paper_id = m["paper_id"]
        path = OUTPUT_DIR / m["file"]
        sectioned = SectionedPaper.model_validate(json.loads(path.read_text()))

        paragraphs_by_section: dict[str, list] = {}
        for p in sectioned.paragraphs:
            paragraphs_by_section.setdefault(p.section_id, []).append(p)

        print(f"[{paper_id}] tagging {len(sectioned.sections)} sections ...")
        new_sections = []
        for section in sectioned.sections:
            section_paragraphs = paragraphs_by_section.get(section.id, [])
            if not section_paragraphs:
                print(f"    section {section.id} ({section.title!r}): no paragraphs -- leaving tag empty")
                new_sections.append(section)
                continue
            question = tag_section(paper_id, section.id, section.title, section_paragraphs)
            new_sections.append(section.model_copy(update={"tag": question}))
            print(f"    section {section.id} ({section.title!r}): {question!r}")

        updated = sectioned.model_copy(update={"sections": new_sections})
        path.write_text(json.dumps(updated.model_dump(), indent=2))
        print(f"[{paper_id}] wrote {len(updated.sections)} tagged sections\n")


if __name__ == "__main__":
    main()
