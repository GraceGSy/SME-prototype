"""Simpler stage 1: identify a paper's high-level sections (in reading order)
and describe each one with a short question/phrase capturing its role, via a
forced tool call to Claude.

Usage:
    python3 extract_sections.py                     # run on the default example papers
    python3 extract_sections.py my_paper.pdf ...     # run on specific PDF paths
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from anthropic import Anthropic
from pydantic import ValidationError

from cache_utils import cached_system, log_cache_usage
from pdf_text import extract_pdf_text
from pipeline_paths import output_dir, papers_dir
from section_schema import SectionedPaper

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
SECTION_CONTEXT_MAX_CHARS = int(os.environ.get("SME_SECTION_CONTEXT_MAX_CHARS", "0"))

PAPERS_DIR = papers_dir()
OUTPUT_DIR = output_dir()

DEFAULT_PAPERS = sorted(PAPERS_DIR.glob("*.pdf"))

SYSTEM_PROMPT = """You identify the high-level sections of an academic paper, in reading order, \
and describe the role each one plays.

Use the paper's OWN section structure -- do not invent sections it doesn't have, and do not split \
or merge sections beyond how the paper itself is organized. Use the paper's actual heading text \
(e.g. "4. Evaluation") for each section's title. A typical paper has 6-12 top-level sections.

For each section, ask yourself: what question about the research does this section answer (e.g. does \
it explain why the work is needed, what was built, how it was tested, what was found, or what it \
means)? Answer with one grammatical, standalone question ending in a question mark -- NOT a fixed \
category label or noun phrase. For example: "Why is this problem worth \
solving?", "What system was built?", "How was the system evaluated?", "What did the study find?", \
"What does this result mean?". Keep it under ~14 words. Give exactly one such question per section."""

USER_PROMPT_TEMPLATE = """Paper id: {paper_id}

Paper text:
\"\"\"
{text}
\"\"\"

Identify this paper's high-level sections and their tags using the record_sections tool."""


def _build_tool() -> dict:
    return {
        "name": "record_sections",
        "description": "Record the paper's high-level sections and their role tags, in reading order.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "paper_id": {"type": "string"},
                "title": {
                    "type": "string",
                    "description": "the paper's own title, as it appears on the paper itself (not a section title)",
                },
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "short stable id, e.g. 's1'",
                            },
                            "title": {
                                "type": "string",
                                "description": "the section's own heading text",
                            },
                            "tag": {
                                "type": "string",
                                "description": "one grammatical standalone question ending in '?', e.g. 'What problem does this address?'",
                            },
                        },
                        "required": ["id", "title", "tag"],
                    },
                },
            },
            "required": ["paper_id", "title", "sections"],
        },
    }


def extract_sections(
    paper_id: str, text: str, model: str = DEFAULT_MODEL
) -> SectionedPaper:
    client = Anthropic()
    context = (
        text if SECTION_CONTEXT_MAX_CHARS <= 0 else text[:SECTION_CONTEXT_MAX_CHARS]
    )
    base_prompt = USER_PROMPT_TEMPLATE.format(paper_id=paper_id, text=context)
    last_error = "Model did not call record_sections"

    # Even forced tool calls can occasionally arrive malformed at the provider
    # boundary. Retry with explicit repair guidance instead of losing the whole run.
    for attempt in range(3):
        repair = ""
        if attempt:
            repair = (
                "\n\nYour previous tool call failed schema validation. Call record_sections "
                "again with sections as a JSON array of objects, not XML or a string."
            )
        response = client.messages.create(
            model=model,
            max_tokens=4000,
            system=cached_system(SYSTEM_PROMPT),
            messages=[{"role": "user", "content": base_prompt + repair}],
            tools=[_build_tool()],
            tool_choice={"type": "tool", "name": "record_sections"},
        )
        log_cache_usage(f"{paper_id} attempt {attempt + 1}", response)

        for block in response.content:
            if block.type != "tool_use" or block.name != "record_sections":
                continue
            data = block.input
            if not isinstance(data, dict):
                last_error = f"tool input was {type(data).__name__}, not an object"
                continue
            if set(data.keys()) - {"paper_id", "title", "sections"} and len(data) == 1:
                data = next(iter(data.values()))
            if not isinstance(data, dict):
                last_error = "wrapped tool input was not an object"
                continue
            data.setdefault("title", paper_id)
            try:
                return SectionedPaper.model_validate(data)
            except ValidationError as exc:
                last_error = str(exc)

        print(
            f"[{paper_id}] invalid section tool response on attempt {attempt + 1}; retrying ..."
        )

    raise RuntimeError(
        f"Could not validate sections for paper_id={paper_id!r}: {last_error}"
    )


def run_one(pdf_path: Path) -> None:
    paper_id = pdf_path.stem
    print(f"[{paper_id}] extracting text from {pdf_path.name} ...")
    text = extract_pdf_text(str(pdf_path))
    context_chars = (
        len(text)
        if SECTION_CONTEXT_MAX_CHARS <= 0
        else min(len(text), SECTION_CONTEXT_MAX_CHARS)
    )
    context_note = (
        "full paper" if context_chars == len(text) else f"first {context_chars:,} chars"
    )
    print(
        f"[{paper_id}] {len(text):,} chars of text; calling model with {context_note} ..."
    )

    sectioned = extract_sections(paper_id=paper_id, text=text)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{paper_id}.json"
    out_path.write_text(json.dumps(sectioned.model_dump(), indent=2))

    tags = [s.tag for s in sectioned.sections]
    print(f"[{paper_id}] wrote {out_path} ({len(sectioned.sections)} sections: {tags})")


def write_manifest() -> None:
    entries = []
    for path in sorted(OUTPUT_DIR.glob("*.json")):
        if path.name in {"manifest.json", "links.json"}:
            continue
        data = json.loads(path.read_text())
        if "paper_id" not in data or "sections" not in data:
            continue  # not a paper file (e.g. some other artifact dropped in output/sections/)
        entries.append(
            {"paper_id": data["paper_id"], "title": data["title"], "file": path.name}
        )
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(entries, indent=2))


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]] or DEFAULT_PAPERS
    for path in paths:
        if not path.exists():
            print(f"skipping {path}: not found", file=sys.stderr)
            continue
        run_one(path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_manifest()


if __name__ == "__main__":
    main()
