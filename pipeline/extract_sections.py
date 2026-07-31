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

from cache_utils import cached_system, log_cache_usage
from pdf_text import extract_pdf_text
from section_schema import SectionedPaper

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
MAX_CHARS = 60_000

SME_DIR = Path(__file__).resolve().parent.parent
PAPERS_DIR = SME_DIR / "papers"
OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "sections"

DEFAULT_PAPERS = [
    PAPERS_DIR / "examplore_chi18.pdf",
    PAPERS_DIR / "mesotext.pdf",
    PAPERS_DIR / "paralib_uist22.pdf",
]

SYSTEM_PROMPT = """You identify the high-level sections of an academic paper, in reading order, \
and describe the role each one plays.

Use the paper's OWN section structure -- do not invent sections it doesn't have, and do not split \
or merge sections beyond how the paper itself is organized. Use the paper's actual heading text \
(e.g. "4. Evaluation") for each section's title. A typical paper has 6-12 top-level sections.

For each section, ask yourself: what question about the research does this section answer, or what \
role does it play in describing the research (e.g. does it explain why the work is needed, what was \
built, how it was tested, what was found, or what it means)? Answer with a short question or phrase \
that captures that role -- NOT a fixed category label. For example: "Why is this problem worth \
solving?", "What system was built?", "How was the system evaluated?", "What did the study find?", \
"What does this result mean?". Keep it under ~10 words, and prefer phrasing it as a question when \
that reads naturally. Give exactly one such tag per section."""

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
        "input_schema": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "title": {"type": "string", "description": "the paper's own title, as it appears on the paper itself (not a section title)"},
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "short stable id, e.g. 's1'"},
                            "title": {"type": "string", "description": "the section's own heading text"},
                            "tag": {
                                "type": "string",
                                "description": "a short question or phrase (not a fixed category), e.g. 'What problem does this address?' or 'How was the system evaluated?'",
                            },
                        },
                        "required": ["id", "title", "tag"],
                    },
                },
            },
            "required": ["paper_id", "title", "sections"],
        },
    }


def extract_sections(paper_id: str, text: str, model: str = DEFAULT_MODEL) -> SectionedPaper:
    client = Anthropic()
    truncated = text[:MAX_CHARS]

    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=cached_system(SYSTEM_PROMPT),
        messages=[{"role": "user", "content": USER_PROMPT_TEMPLATE.format(paper_id=paper_id, text=truncated)}],
        tools=[_build_tool()],
        tool_choice={"type": "tool", "name": "record_sections"},
    )
    log_cache_usage(paper_id, response)

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_sections":
            data = block.input
            if set(data.keys()) - {"paper_id", "title", "sections"} and len(data) == 1:
                data = next(iter(data.values()))
            data.setdefault("title", paper_id)  # defensive: model has occasionally omitted the top-level title
            return SectionedPaper.model_validate(data)

    raise RuntimeError(f"Model did not call record_sections for paper_id={paper_id!r}")


def run_one(pdf_path: Path) -> None:
    paper_id = pdf_path.stem
    print(f"[{paper_id}] extracting text from {pdf_path.name} ...")
    text = extract_pdf_text(str(pdf_path))
    print(f"[{paper_id}] {len(text):,} chars of text; calling model ...")

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
        entries.append({"paper_id": data["paper_id"], "title": data["title"], "file": path.name})
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
