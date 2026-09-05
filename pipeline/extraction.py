"""Extract one new raw document. Prepared documents are never overwritten."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
from typing import Any, Literal

from .document import content_schema, strip_questions, validate_document, write_json
from .llm.client import ClaudeSkills, SkillCallPolicy, directory_hash


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "extract-section-and-subsection-paragraphs"
Domain = Literal["academic", "legal", "narrative"]


def validate_source_tail(document: list[dict[str, Any]], source: str) -> None:
    """Detect truncated text extraction; this is not a full fidelity assessment."""
    expected = re.findall(r"\w+", source.casefold())[-8:]
    text = " ".join(
        paragraph["text"]
        for section in document
        for unit in [section, *section["subsections"]]
        for paragraph in unit["paragraphs"]
    )
    actual = re.findall(r"\w+", text.casefold())
    if not expected or not any(
        actual[index:index + len(expected)] == expected
        for index in range(len(actual) - len(expected) + 1)
    ):
        raise ValueError("Extraction is missing the final source passage")


def extract_document(
    source: Path,
    output: Path,
    *,
    domain: Domain,
    title: str,
    model: str = "claude-sonnet-5",
    client: ClaudeSkills | None = None,
) -> Path:
    """Publish canonical content and provenance after one validated judgment."""
    source, output = source.resolve(), output.resolve()
    provenance = output.with_suffix(".provenance.json")
    if output.exists() or provenance.exists():
        raise FileExistsError(f"Prepared output already exists; choose a new path: {output}")
    if domain not in {"academic", "legal", "narrative"}:
        raise ValueError(f"Unsupported extraction domain: {domain}")
    if source.suffix not in {".pdf", ".txt", ".xhtml"}:
        raise ValueError("Raw input must be .pdf, .txt, or .xhtml; canonical JSON needs no extraction")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("A non-empty document title is required")
    raw = source.read_bytes()
    client = client or ClaudeSkills(ROOT, ROOT / "runs/extraction/skill-registry.json", model)
    skill = client.register(SKILL)
    result = client.run_json_file(
        skill,
        f"Extract the attached document: {title}",
        source,
        content_schema(),
        policy=SkillCallPolicy(max_tokens=32768, max_input_tokens=250000),
        cacheable_prompt=(
            f"Use the attached extraction Skill in {domain} mode. Preserve only "
            "source-marked structural boundaries and the original paragraphs. "
            "Return canonical content directly; do not create files, generate "
            "questions, infer divisions, or add explanatory prose."
        ),
    )
    content = result.value
    validate_document(content)
    if strip_questions(content) != content:
        raise ValueError("Extraction must return content only, without generated questions")
    if source.suffix == ".txt":
        validate_source_tail(content, raw.decode("utf-8"))
    write_json(provenance, {
        "schema_version": 1,
        "source": str(source),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "domain": domain,
        "title": title,
        "model": model,
        "skill_sha256": directory_hash(SKILL),
        "response_id": result.response_id,
        "usage": result.usage,
    })
    write_json(output, content)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--domain", choices=["academic", "legal", "narrative"], required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--model", default="claude-sonnet-5")
    args = parser.parse_args()
    print(extract_document(args.source, args.output, domain=args.domain, title=args.title, model=args.model))


if __name__ == "__main__":
    main()
