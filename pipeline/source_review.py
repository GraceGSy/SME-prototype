"""Offline source checks and explicit approval of reusable prepared documents."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .document import iter_structural_units, strip_questions, validate_document
from .files import file_sha256, read_json, write_json

SOURCE_CACHE = Path(__file__).resolve().parents[1] / "_cache" / "source-extractions"
Digest = str


class ReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    status: Literal["pending", "approved"]
    source: str
    source_sha256: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    content_sha256: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    reference_sha256: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    boundary_mode: Literal["paragraphs", "manual_layout"]
    coverage_ok: bool
    order_ok: bool
    boundary_ok: bool | None
    paragraph_count: int = Field(ge=0)
    issues: list[str]
    reviewer: str | None = None
    notes: str | None = None
    reviewed_at: str | None = None


def review_path(content: Path) -> Path:
    return content.with_suffix(".review.json")


def source_cache_dir(source_sha256: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{64}", source_sha256):
        raise ValueError("Invalid source digest")
    return SOURCE_CACHE / source_sha256


def content_digest(document: Any) -> str:
    # Approval covers authored content and ownership, not generated questions.
    encoded = json.dumps(strip_questions(document), ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def require_approved(content: Path, document: Any) -> dict[str, Any] | None:
    path = review_path(content)
    if not path.exists():
        provenance = content.with_suffix(".provenance.json")
        if provenance.exists() and read_json(provenance).get("requires_source_review") is True:
            raise ValueError(f"Source review is missing for {content}; review before graph use")
        return None  # Existing manually prepared corpora are not retroactively certified.
    return validate_approval(read_json(path), document)


def validate_approval(payload: dict, document: Any) -> dict:
    record = ReviewRecord.model_validate(payload)
    if record.content_sha256 != content_digest(document):
        raise ValueError("Prepared content changed after source review")
    if (
        record.status != "approved"
        or record.issues
        or not record.coverage_ok
        or not record.order_ok
        or record.boundary_ok is False
        or (record.boundary_mode == "paragraphs" and record.boundary_ok is not True)
        or not record.reviewer
        or not record.notes
        or not record.reviewed_at
    ):
        raise ValueError("Source review is not approved")
    return record.model_dump()


class _MarkupText(HTMLParser):
    """Retain authored text blocks, not markup, scripts, or document metadata."""

    block_tags = {"p", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.current: list[str] = []
        self.blocks: list[str] = []

    def flush(self):
        text = "".join(self.current).strip()
        if text:
            self.blocks.append(text)
        self.current = []

    def handle_starttag(self, tag, attrs):
        if tag in {"head", "script", "style"}:
            self.ignored += 1
        if self.ignored:
            return
        if tag in self.block_tags:
            self.flush()
        elif tag == "br":
            self.current.append("\n")

    def handle_endtag(self, tag):
        if tag in {"head", "script", "style"}:
            self.ignored -= 1
            return
        if not self.ignored and tag in self.block_tags:
            self.flush()

    def handle_data(self, data):
        if not self.ignored:
            self.current.append(data)


def source_reference(source: Path, reference: Path | None = None) -> tuple[str, str]:
    if reference is not None:
        if reference.suffix != ".txt":
            raise ValueError("A reviewed reference transcript must be UTF-8 .txt")
        text = reference.read_text(encoding="utf-8")
    elif source.suffix == ".txt":
        text = source.read_text(encoding="utf-8")
    elif source.suffix == ".xhtml":
        parser = _MarkupText()
        parser.feed(source.read_text(encoding="utf-8"))
        parser.close()
        parser.flush()
        text = "\n\n".join(parser.blocks)
    elif source.suffix == ".pdf":
        from pypdf import PdfReader

        text = "\n\f\n".join(
            page.extract_text(extraction_mode="layout") or "" for page in PdfReader(source).pages
        )
    else:
        raise ValueError("Source review supports .txt, .xhtml, or .pdf")
    if not text.strip():
        raise ValueError("No source text found; supply a reviewed UTF-8 reference transcript")
    mode = (
        "manual_layout"
        if "\f" in text or (source.suffix == ".pdf" and reference is None)
        else "paragraphs"
    )
    return text, mode


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+|[^\w\s]", unicodedata.normalize("NFKC", text))


def inspect_document(
    source_text: str, document: Any, *, boundary_mode: str = "paragraphs"
) -> dict[str, Any]:
    """Compare text and paragraph ownership without rewriting either input."""
    validate_document(document)
    units = list(iter_structural_units(document))
    headings: dict[tuple[str, ...], list[str]] = {}
    for unit in units:
        number, name = unit.source.get("section_number") or "", unit.name
        for candidate in (name, number, f"{number} {name}", number + "." if number else ""):
            key = tuple(token.casefold() for token in _tokens(candidate))
            if key:
                headings.setdefault(key, []).append(unit.unit_id)
    blocks = []
    for block in re.split(r"\n\s*\n", source_text.replace("\r\n", "\n")):
        lines = []
        for line in block.splitlines():
            if tuple(token.casefold() for token in _tokens(line)) in headings:
                if lines:
                    blocks.append("\n".join(lines))
                    lines = []
                blocks.append(line)
            else:
                lines.append(line)
        if lines:
            blocks.append("\n".join(lines))

    matched_headings = {}
    expected, expected_ends = [], set()
    for block in blocks:
        tokens = _tokens(block)
        if not tokens:
            continue
        key = tuple(token.casefold() for token in tokens)
        owner = next(
            (owner for owner in headings.get(key, []) if owner not in matched_headings), None
        )
        expected.extend(tokens)
        if owner is not None:
            matched_headings[owner] = tokens
        else:
            expected_ends.add(len(expected))
    actual, actual_ends = [], set()
    paragraph_count = 0
    for unit in units:
        actual.extend(matched_headings.get(unit.unit_id, []))
        for paragraph in unit.own_paragraphs:
            actual.extend(_tokens(paragraph["text"]))
            actual_ends.add(len(actual))
            paragraph_count += 1

    missing, extra = Counter(expected) - Counter(actual), Counter(actual) - Counter(expected)
    coverage_ok, order_ok = not missing and not extra, actual == expected
    boundary_ok = (
        expected_ends == actual_ends if order_ok and boundary_mode == "paragraphs" else None
    )
    issues = []
    for label, difference in (
        ("Missing source tokens", missing),
        ("Added or duplicated tokens", extra),
    ):
        if difference:
            examples = ", ".join(
                f"{token!r} x{count}" for token, count in difference.most_common(12)
            )
            issues.append(f"{label} ({difference.total()}): {examples}")
    if coverage_ok and not order_ok:
        issues.append("Text or heading ownership is reordered relative to the source")
    if boundary_ok is False:
        issues.append(
            f"Paragraph boundaries differ: {len(expected_ends - actual_ends)} merged/missing, {len(actual_ends - expected_ends)} split/extra"
        )
    if len(units) > 1:
        unmarked = [unit.unit_id for unit in units if unit.unit_id not in matched_headings]
        if unmarked:
            issues.append("Structural headings not found in the source: " + ", ".join(unmarked))
    return {
        "coverage_ok": coverage_ok,
        "order_ok": order_ok,
        "boundary_ok": boundary_ok,
        "paragraph_count": paragraph_count,
        "issues": issues,
    }


def write_review_report(content: Path, source_text: str, document: Any, record: dict) -> None:
    issues = "".join(f"<li>{html.escape(issue)}</li>" for issue in record["issues"])
    if not issues:
        status = (
            "Source review is approved."
            if record["status"] == "approved"
            else "Review is still required."
        )
        issues = f"<li>No automatic text discrepancies found. {status}</li>"
    paragraphs = []
    for unit in iter_structural_units(document):
        paragraphs.append(f"<h3>{html.escape(unit.name)} <small>{unit.unit_id}</small></h3>")
        for index, paragraph in enumerate(unit.own_paragraphs, 1):
            paragraphs.append(
                f"<article><small>{unit.unit_id}.p{index:04d}</small><p>{html.escape(paragraph['text'])}</p></article>"
            )
    manual = (
        "PDF/layout text does not establish authored paragraph boundaries. Check every boundary against the original or supply a reviewed paragraph transcript."
        if record["boundary_mode"] == "manual_layout"
        else "Check headings, paragraph boundaries, footnote placement, and any intentionally omitted material against the original."
    )
    report = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Source review</title>
<style>body{{margin:0;background:#f5f2e9;color:#26332e;font:16px Georgia,serif}}main{{max-width:1200px;margin:auto;padding:30px}}h1{{font-size:40px;margin:0 0 8px}}small,code{{font:12px monospace;overflow-wrap:anywhere}}.summary,article{{background:#fffdf7;border:1px solid #d4dacd;padding:16px;margin:12px 0}}.columns{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}pre,p{{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}}pre{{font:14px/1.6 monospace}}h2{{border-bottom:2px solid #48785f;padding-bottom:8px}}@media(max-width:700px){{.columns{{grid-template-columns:1fr}}main{{padding:16px}}}}</style>
<main><h1>Source review</h1><small>{html.escape(str(content))}</small>
<div class="summary"><strong>Status: {record["status"]}</strong><p><small>Original: {html.escape(record["source"])}</small></p><p>Prepared paragraphs: {record["paragraph_count"]}</p><ul>{issues}</ul><p>{manual}</p>
<p>Approval certifies source fidelity, not matching quality. Fix discrepancies in the saved JSON; do not pay to extract it again.</p></div>
<div class="columns"><section><h2>Source transcript</h2><pre>{html.escape(source_text)}</pre></section>
<section><h2>Prepared paragraphs</h2>{"".join(paragraphs)}</section></div></main></html>"""
    content.with_suffix(".review.html").write_text(report, encoding="utf-8")


def review_document(
    source: Path,
    content: Path,
    *,
    reference: Path | None = None,
    approve: bool = False,
    reviewer: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    source, content = source.resolve(), content.resolve()
    document = read_json(content)
    source_sha256 = file_sha256(source)
    if not approve and reference is None and review_path(content).exists():
        previous = ReviewRecord.model_validate(read_json(review_path(content)))
        if previous.status == "approved" and previous.source_sha256 == source_sha256:
            return validate_approval(previous.model_dump(), document)
    source_text, mode = source_reference(source, reference)
    record = ReviewRecord(
        status="pending",
        source=str(source),
        source_sha256=source_sha256,
        content_sha256=content_digest(document),
        reference_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
        boundary_mode=mode,
        **inspect_document(source_text, document, boundary_mode=mode),
    )
    if approve:
        if record.issues:
            raise ValueError(
                "Cannot approve source review with unresolved issues: " + "; ".join(record.issues)
            )
        if not reviewer or not reviewer.strip() or not notes or not notes.strip():
            raise ValueError(
                "Approval requires a reviewer and notes confirming source and boundary review"
            )
        record.status = "approved"
        record.reviewer, record.notes = reviewer.strip(), notes.strip()
        record.reviewed_at = datetime.now(timezone.utc).isoformat()
    elif review_path(content).exists():
        previous = ReviewRecord.model_validate(read_json(review_path(content)))
        if previous.status == "approved" and (
            previous.source_sha256,
            previous.content_sha256,
            previous.reference_sha256,
        ) == (record.source_sha256, record.content_sha256, record.reference_sha256):
            record = previous
    payload = record.model_dump()
    write_json(review_path(content), payload)
    write_review_report(content, source_text, document, payload)
    if approve:
        cache = source_cache_dir(source_sha256)
        cache.mkdir(parents=True, exist_ok=True)
        provenance = content.with_suffix(".provenance.json")
        write_json(
            cache / "approved.json",
            {
                "content": strip_questions(document),
                "review": payload,
                "reference_text": source_text,
                "provenance": read_json(provenance)
                if provenance.exists()
                else {"source_sha256": source_sha256, "requires_source_review": True},
            },
        )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("content", type=Path)
    parser.add_argument(
        "--reference",
        type=Path,
        help="Reviewed UTF-8 transcript with authored paragraphs; record any intentional exclusions in approval notes",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Confirm original-source, heading, paragraph-boundary, and footnote review",
    )
    parser.add_argument("--reviewer")
    parser.add_argument("--notes")
    args = parser.parse_args()
    record = review_document(
        args.source,
        args.content,
        reference=args.reference,
        approve=args.approve,
        reviewer=args.reviewer,
        notes=args.notes,
    )
    print(
        f"Source review: {record['status']}; {len(record['issues'])} issue(s). Open {args.content.with_suffix('.review.html')}"
    )


if __name__ == "__main__":
    main()
