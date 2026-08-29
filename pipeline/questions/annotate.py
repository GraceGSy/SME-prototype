"""Annotate nested section JSON with one role-question per section, subsection,
and paragraph, via a forced Claude tool call.

Walks a skills-pipeline extraction file (section_name, paragraphs, subsections),
sends each unit as a paper-order text block, and writes the result back onto
that same object as question_this_text_answers.

Usage:
    python3 annotate_text_questions.py
    python3 annotate_text_questions.py path/to/sections.json
    python3 annotate_text_questions.py --dry-run path/to/sections.json
    python3 annotate_text_questions.py --force path/to/sections.json
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
from typing import Any, Callable, Optional

from pipeline.cache_utils import cached_system, log_cache_usage

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")
DEFAULT_CACHE_DIR = REPO_ROOT / "runs" / "_cache" / "text_questions"
DEFAULT_INPUT = (
    REPO_ROOT
    / "datasets"
    / "hci-five-paper"
    / "corpusstudio-sections-with-subsections-and-paragraph-content-no-appendices.json"
)

FIELD = "question_this_text_answers"
MAX_TOKENS = 256

SYSTEM_PROMPT = """Identify the function/role this text serves in the overall document — not its topic, not
a summary of its content, not a restatement of its title if it has one. Ask: what job is this text
doing? What answer(s) does the reader get before moving to the next part of the
document?

Write the question so it names enough context to stand alone — avoid bare "this"/"here" that only resolve if the reader already has the section's text open.

Keep the question short and genuinely open, preferably under 20 words. It must not answer itself. Do not use parentheses, em-dashes, or phrases like "namely", "including", or "such as" to list specifics. If the text covers several jobs, widen the verb rather than enumerating them.

Too specific (answers itself):
What dataset was collected and what series of pre-processing and embedding steps (sentence segmentation, embedding model choice, and section-title clustering) were applied to prepare it for the CorpusStudio system?

Open (does not list the steps):
How was the CorpusStudio dataset collected and prepared for use?

The question must not mention section numbering if they exist, and must not make a claim that the text doesn't actually establish.

Return exactly one question — including short ones (Acknowledgments, Preface). Never return null, "N/A", or a generic placeholder if the text below is not empty. If it is empty, return null."""


AskFn = Callable[[str], str]
SaveFn = Callable[[], None]


def _paragraphs(obj: dict) -> list[dict]:
    return list(obj.get("paragraphs") or [])


def _subsections(obj: dict) -> list[dict]:
    return list(obj.get("subsections") or [])


def _paragraph_text(paragraph: dict) -> str:
    return (paragraph.get("text") or "").strip()


def paragraph_is_empty(paragraph: dict) -> bool:
    return not _paragraph_text(paragraph)


def subsection_is_empty(subsection: dict) -> bool:
    return all(paragraph_is_empty(p) for p in _paragraphs(subsection))


def section_is_empty(section: dict) -> bool:
    if any(not paragraph_is_empty(p) for p in _paragraphs(section)):
        return False
    return all(subsection_is_empty(sub) for sub in _subsections(section))


def _join_blocks(*blocks: str) -> str:
    return "\n\n".join(block for block in blocks if block)


def serialize_section(section: dict) -> str:
    """Paper-order block: title, lead-in paragraphs, then each subsection's title + paragraphs."""
    parts = [section.get("section_name") or ""]
    for paragraph in _paragraphs(section):
        text = _paragraph_text(paragraph)
        if text:
            parts.append(text)
    for subsection in _subsections(section):
        parts.append(subsection.get("section_name") or "")
        for paragraph in _paragraphs(subsection):
            text = _paragraph_text(paragraph)
            if text:
                parts.append(text)
    return _join_blocks(*parts)


def serialize_subsection(section: dict, subsection: dict) -> str:
    header = (
        f"Section: {section.get('section_name') or ''}\n"
        f"Subsection: {subsection.get('section_name') or ''}"
    )
    body = _join_blocks(*(_paragraph_text(p) for p in _paragraphs(subsection) if not paragraph_is_empty(p)))
    return _join_blocks(header, body)


def serialize_paragraph(
    section: dict,
    paragraph: dict,
    subsection: Optional[dict] = None,
) -> str:
    lines = [f"Section: {section.get('section_name') or ''}"]
    if subsection is not None:
        lines.append(f"Subsection: {subsection.get('section_name') or ''}")
    header = "\n".join(lines)
    return _join_blocks(header, _paragraph_text(paragraph))


def _cache_key(serialized: str) -> str:
    return hashlib.sha256(f"{SYSTEM_PROMPT}\0{serialized}".encode("utf-8")).hexdigest()


def _build_tool() -> dict:
    return {
        "name": "record_question",
        "description": "Record the single role question this text answers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "One open question capturing the function/role of the text. "
                        "No parentheses or clauses that name the answer. "
                        "Preferably under 20 words."
                    ),
                },
            },
            "required": ["question"],
        },
    }


def _question_from_response(response: Any) -> str:
    for block in response.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "record_question":
            data = block.input
            if isinstance(data, dict) and "question" not in data and len(data) == 1:
                inner = next(iter(data.values()))
                data = inner if isinstance(inner, dict) else {"question": inner}
            if not isinstance(data, dict) or "question" not in data:
                raise RuntimeError(f"record_question tool payload missing 'question': {data!r}")
            question = data["question"]
            if not isinstance(question, str) or not question.strip():
                raise RuntimeError(f"record_question returned an empty question: {question!r}")
            return question.strip()
    raise RuntimeError("Model did not call record_question")


def make_ask_fn(client: Any, model: str, cache_dir: Path) -> AskFn:
    def ask(serialized: str, label: str = "") -> str:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{_cache_key(serialized)}.json"
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            print(f"    {label}: using cached response ({cache_path.name})")
            return payload["question"]

        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=cached_system(SYSTEM_PROMPT),
            messages=[{"role": "user", "content": f"Text:\n{serialized}"}],
            tools=[_build_tool()],
            tool_choice={"type": "tool", "name": "record_question"},
        )
        if label:
            log_cache_usage(label, response)
        question = _question_from_response(response)
        cache_path.write_text(json.dumps({"question": question}, indent=2) + "\n", encoding="utf-8")
        return question

    return ask


def save_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _unit_label(kind: str, section: dict, subsection: Optional[dict] = None, paragraph: Optional[dict] = None) -> str:
    name = section.get("section_name") or "?"
    if kind == "section":
        return f"section:{name}"
    if kind == "subsection":
        sub_name = (subsection or {}).get("section_name") or "?"
        return f"subsection:{name}/{sub_name}"
    para_n = (paragraph or {}).get("paragraph_number", "?")
    if subsection is not None:
        sub_name = subsection.get("section_name") or "?"
        return f"paragraph:{name}/{sub_name}/p{para_n}"
    return f"paragraph:{name}/p{para_n}"


def completeness_violations(sections: list[dict]) -> list[str]:
    """Non-empty units whose question_this_text_answers is missing or null."""
    violations: list[str] = []

    def _check(obj: dict, empty: bool, label: str) -> None:
        if empty:
            return
        if not obj.get(FIELD):
            violations.append(label)

    for section in sections:
        _check(section, section_is_empty(section), _unit_label("section", section))
        for paragraph in _paragraphs(section):
            _check(
                paragraph,
                paragraph_is_empty(paragraph),
                _unit_label("paragraph", section, paragraph=paragraph),
            )
        for subsection in _subsections(section):
            _check(
                subsection,
                subsection_is_empty(subsection),
                _unit_label("subsection", section, subsection),
            )
            for paragraph in _paragraphs(subsection):
                _check(
                    paragraph,
                    paragraph_is_empty(paragraph),
                    _unit_label("paragraph", section, subsection, paragraph),
                )
    return violations


def annotate_document(
    sections: list[dict],
    *,
    force: bool = False,
    dry_run: bool = False,
    ask_fn: Optional[AskFn] = None,
    save_fn: Optional[SaveFn] = None,
) -> dict[str, int]:
    """Walk sections, then subsections, then paragraphs. Mutates `sections` in place.

    ask_fn is only called for non-empty units that are not already annotated
    (unless force=True). Empty units get null with no API call.
    """
    stats = {"called": 0, "skipped": 0, "nulled": 0, "dry_run": 0}

    def _apply(obj: dict, *, empty: bool, serialized: str, label: str) -> None:
        if not force and FIELD in obj:
            stats["skipped"] += 1
            print(f"    {label}: already has {FIELD}, skipping")
            return
        if empty:
            if dry_run:
                stats["dry_run"] += 1
                print(f"[dry-run] {label}: empty -> null")
                return
            obj[FIELD] = None
            stats["nulled"] += 1
            print(f"    {label}: empty -> null")
            if save_fn is not None:
                save_fn()
            return
        if dry_run:
            stats["dry_run"] += 1
            print(f"[dry-run] {label}:\n{serialized}\n")
            return
        if ask_fn is None:
            raise RuntimeError("ask_fn is required when not dry-running a non-empty unit")
        question = _call_ask(ask_fn, serialized, label)
        obj[FIELD] = question
        stats["called"] += 1
        print(f"    {label}: {question}")
        if save_fn is not None:
            save_fn()

    for section in sections:
        _apply(
            section,
            empty=section_is_empty(section),
            serialized=serialize_section(section),
            label=_unit_label("section", section),
        )
    for section in sections:
        for subsection in _subsections(section):
            _apply(
                subsection,
                empty=subsection_is_empty(subsection),
                serialized=serialize_subsection(section, subsection),
                label=_unit_label("subsection", section, subsection),
            )
    for section in sections:
        for paragraph in _paragraphs(section):
            _apply(
                paragraph,
                empty=paragraph_is_empty(paragraph),
                serialized=serialize_paragraph(section, paragraph),
                label=_unit_label("paragraph", section, paragraph=paragraph),
            )
        for subsection in _subsections(section):
            for paragraph in _paragraphs(subsection):
                _apply(
                    paragraph,
                    empty=paragraph_is_empty(paragraph),
                    serialized=serialize_paragraph(section, paragraph, subsection),
                    label=_unit_label("paragraph", section, subsection, paragraph),
                )
    return stats


def _call_ask(ask_fn: AskFn, serialized: str, label: str) -> str:
    """Test doubles may take only the serialized text; the real ask_fn also takes a label.

    Do not probe this with a try/except TypeError: Anthropic raises TypeError for
    missing auth, and catching that retried the call and hid the real error.
    """
    try:
        n_params = len(inspect.signature(ask_fn).parameters)
    except (TypeError, ValueError):
        n_params = 1
    if n_params >= 2:
        return ask_fn(serialized, label)  # type: ignore[misc]
    return ask_fn(serialized)


def annotate_file(
    path: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    ask_fn: Optional[AskFn] = None,
    model: str = DEFAULT_MODEL,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict[str, int]:
    path = Path(path)
    sections = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(sections, list):
        raise ValueError(f"{path} must contain a JSON array of sections")

    if ask_fn is None and not dry_run:
        from anthropic import Anthropic

        ask_fn = make_ask_fn(Anthropic(), model, Path(cache_dir))

    def _save() -> None:
        save_json(path, sections)

    print(f"annotating {path}")
    stats = annotate_document(
        sections,
        force=force,
        dry_run=dry_run,
        ask_fn=ask_fn,
        save_fn=None if dry_run else _save,
    )
    print(
        f"done: called={stats['called']} skipped={stats['skipped']} "
        f"nulled={stats['nulled']} dry_run={stats['dry_run']}"
    )
    if not dry_run:
        violations = completeness_violations(sections)
        if violations:
            print(
                f"BLOCKED: {len(violations)} non-empty units are missing a non-null "
                f"{FIELD}:",
                file=sys.stderr,
            )
            for label in violations:
                print(f"  - {label}", file=sys.stderr)
            raise SystemExit(1)
        print(f"completeness check passed ({len(sections)} top-level sections)")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help="nested sections JSON to annotate in place (default: CorpusStudio corpus file)",
    )
    parser.add_argument("--force", action="store_true", help="recompute even if the field is already present")
    parser.add_argument("--dry-run", action="store_true", help="print serialized payloads without calling the API or writing")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        raise SystemExit(1)

    annotate_file(
        args.input,
        force=args.force,
        dry_run=args.dry_run,
        model=args.model,
        cache_dir=args.cache_dir,
    )


if __name__ == "__main__":
    main()
