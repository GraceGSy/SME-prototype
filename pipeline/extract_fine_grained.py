"""Stage 1c: within each already-tagged section, extract its paragraphs. Each
paragraph's `tag` is a short free-text question/phrase (same style as section
tags -- not a fixed category), PLUS two discourse-relation tags (from a small
fixed vocabulary) that only exist at paragraph granularity.

The model identifies each paragraph's tag plus a short verbatim "start_text"
marker; the paragraph's actual text is then sliced locally from the section's
own text between consecutive markers (same locate-and-slice trick as
attach_section_text.py -- no LLM-generated body text).

Alongside the free-text `tag`, the model also gives:
  - prev_relation: how this paragraph relates to the one immediately before it
    (e.g. "elaboration", "example") -- empty if it's the first in its section.
  - next_relation: how this paragraph relates to the one immediately after it
    (e.g. "motivation", "cause") -- empty if it's the last in its section.
These are section-local: adjacency is only considered within the same
section, not across a section boundary.

Each paragraph also records `section_id`, the id of the section it was
extracted from -- pure local bookkeeping (not part of the model's response),
so re-running this script backfills it onto existing output using the
existing per-section cache, with no new Claude calls.

All of this comes from a single forced tool call per section.

Usage:
    python3 extract_fine_grained.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from anthropic import Anthropic

from cache_utils import cached_system, log_cache_usage
from section_schema import DISCOURSE_TAGS, Section, SectionedPaper
from text_locate import slice_by_markers

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"
CACHE_DIR = OUTPUT_DIR / "_cache" / "fine_grained"

SYSTEM_PROMPT = f"""You are describing the paragraphs of one section of an academic paper.

You will be given the section's full text.

For EVERY paragraph, give three tags:
1. "tag" -- ask yourself: what question about the research does this paragraph answer, or what role \
does it play in describing the research (e.g. does it explain why the work is needed, what was built, \
how it was tested, what was found, or what it means)? Answer with a short question or phrase that \
captures that role -- NOT a fixed category label. For example: "Why is this problem worth solving?", \
"What system was built?", "How was the system evaluated?", "What did the study find?". Keep it under \
~10 words, and prefer phrasing it as a question when that reads naturally. A paragraph's tag can \
differ from its neighbors' if it plays a distinct role (e.g. a paragraph in a results-focused section \
can still be tagged "What limitation does this reveal?" if it states a caveat).
2. "prev_relation" -- how this paragraph relates to the one immediately before it (within this section \
only), one of {DISCOURSE_TAGS} (or a close variant). Leave this "" for the very first paragraph in the \
section, since there is nothing before it.
3. "next_relation" -- how this paragraph relates to the one immediately after it (within this section \
only), one of {DISCOURSE_TAGS} (or a close variant). Leave this "" for the very last paragraph in the \
section, since there is nothing after it.

Identify the section's paragraphs, in order. For each, give "tag", "prev_relation", "next_relation", \
and a "start_text" -- the first 6-10 words of that paragraph, copied VERBATIM from the text (not \
paraphrased), so the exact paragraph boundary can be located afterward."""

USER_PROMPT_TEMPLATE = """Section tag: {tag}
Section title: {title}

Section text:
\"\"\"
{text}
\"\"\"

Extract this section's paragraph tags using the record_fine_grained_tags tool."""


def _build_tool() -> dict:
    return {
        "name": "record_fine_grained_tags",
        "description": "Record paragraph-level tags for one section.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paragraphs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tag": {"type": "string", "description": "a short question or phrase (not a fixed category), e.g. 'What problem does this address?' or 'How was the system evaluated?'"},
                            "start_text": {"type": "string", "description": "first 6-10 words of this paragraph, verbatim"},
                            "prev_relation": {
                                "type": "string",
                                "description": f"relation to the PREVIOUS paragraph, one of {DISCOURSE_TAGS} (or a close variant); \"\" if this is the first paragraph in the section",
                            },
                            "next_relation": {
                                "type": "string",
                                "description": f"relation to the FOLLOWING paragraph, one of {DISCOURSE_TAGS} (or a close variant); \"\" if this is the last paragraph in the section",
                            },
                        },
                        "required": ["tag", "start_text", "prev_relation", "next_relation"],
                    },
                },
            },
            "required": ["paragraphs"],
        },
    }


# Sections this long (chars) usually mean a references/appendix list got swept in with no
# following heading to bound it (e.g. "Acknowledgments" or the last content section running to
# EOF) -- hundreds of citation-line "paragraphs" would blow past the output budget and add no
# real signal, so these get a uniform fallback tag instead of a full LLM call.
MAX_CHARS_FOR_LLM = 25_000


def _fallback_result(section: Section) -> dict:
    return {
        "paragraphs": [{"tag": section.tag, "start_text": section.text[:60], "prev_relation": "", "next_relation": ""}],
    }


def _cache_path(paper_id: str, section_id: str) -> Path:
    return CACHE_DIR / f"{paper_id}__{section_id}.json"


def extract_fine_grained(paper_id: str, section: Section, model: str = DEFAULT_MODEL) -> dict:
    """Raw per-section results are cached to disk under a stable (paper_id,
    section_id) key -- rerunning the script (e.g. after a crash, a rate limit,
    or running out of credit mid-batch) reuses every already-paid-for call
    instead of hitting the API again, and only calls for sections not yet
    cached."""
    cache_path = _cache_path(paper_id, section.id)
    if cache_path.exists():
        print(f"    section {section.id}: using cached response ({cache_path.name})")
        return json.loads(cache_path.read_text())

    def _save(result: dict) -> dict:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, indent=2))
        return result

    if len(section.text) > MAX_CHARS_FOR_LLM:
        print(f"    section {section.id} is {len(section.text):,} chars -- skipping LLM call, using a uniform fallback tag")
        return _save(_fallback_result(section))

    client = Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=cached_system(SYSTEM_PROMPT),
        messages=[{
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(tag=section.tag, title=section.title, text=section.text),
        }],
        tools=[_build_tool()],
        tool_choice={"type": "tool", "name": "record_fine_grained_tags"},
    )
    log_cache_usage(section.id, response)

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_fine_grained_tags":
            data = block.input
            if set(data.keys()) - {"paragraphs"} and len(data) == 1:
                data = next(iter(data.values()))
            if "paragraphs" not in data:
                print(f"    section {section.id}: incomplete tool response (got keys {list(data.keys())}) -- using a uniform fallback tag")
                return _save(_fallback_result(section))
            return _save(data)

    raise RuntimeError(f"Model did not call record_fine_grained_tags for section {section.id!r}")


def build_paragraphs(section: Section, result: dict, id_start: int) -> tuple[list[Section], int]:
    markers = [p["start_text"] for p in result["paragraphs"]]
    slices = slice_by_markers(section.text, markers)
    paragraphs = []
    next_id = id_start
    for p, sliced in zip(result["paragraphs"], slices):
        text = sliced if sliced is not None else p["start_text"]
        paragraphs.append(Section(
            id=f"pa{next_id}", tag=p["tag"], text=text,
            prev_relation=p.get("prev_relation", ""), next_relation=p.get("next_relation", ""),
            section_id=section.id,
        ))
        next_id += 1
    return paragraphs, next_id


def process_paper(sectioned: SectionedPaper) -> SectionedPaper:
    all_paragraphs: list[Section] = []
    para_id = 1

    for section in sectioned.sections:
        result = extract_fine_grained(sectioned.paper_id, section)
        paragraphs, para_id = build_paragraphs(section, result, para_id)
        all_paragraphs.extend(paragraphs)
        print(f"    section {section.id} ({section.tag}): {len(paragraphs)} paragraphs")

    return sectioned.model_copy(update={"paragraphs": all_paragraphs})


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    for m in manifest:
        paper_id = m["paper_id"]
        path = OUTPUT_DIR / m["file"]
        sectioned = SectionedPaper.model_validate(json.loads(path.read_text()))

        print(f"[{paper_id}] extracting paragraphs for {len(sectioned.sections)} sections ...")
        updated = process_paper(sectioned)
        path.write_text(json.dumps(updated.model_dump(), indent=2))
        print(f"[{paper_id}] wrote {len(updated.paragraphs)} paragraphs")


if __name__ == "__main__":
    main()
