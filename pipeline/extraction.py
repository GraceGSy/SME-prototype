"""Extract each source once, review it offline, and reuse approved content."""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path
from typing import Literal

from .document import content_schema, strip_questions, validate_document
from .files import directory_hash, file_sha256, read_json, write_json
from .prompts import PROMPT_ROOT, REPO_ROOT, request_prompts
from .providers.contracts import SkillCallPolicy, SkillClient
from .providers.factory import create_skill_client
from .providers.settings import ModelSettings
from .source_review import (
    require_approved,
    review_document,
    review_path,
    source_cache_dir,
    source_reference,
    validate_approval,
    write_review_report,
)

ROOT = REPO_ROOT
SKILL = PROMPT_ROOT / "skills" / "extract-section-and-subsection-paragraphs"
EXTRACTION_PROMPTS = request_prompts("extraction")
Domain = Literal["academic", "legal", "narrative"]


def extract_document(
    source: Path,
    output: Path,
    *,
    domain: Domain,
    title: str,
    model: str | None = None,
    provider: str = "anthropic",
    client: SkillClient | None = None,
    reference: Path | None = None,
) -> Path:
    """Save the first response before local checks; never silently buy a replacement."""
    source, output = source.resolve(), output.resolve()
    provenance = output.with_suffix(".provenance.json")
    if domain not in {"academic", "legal", "narrative"}:
        raise ValueError(f"Unsupported extraction domain: {domain}")
    if source.suffix not in {".pdf", ".txt", ".xhtml"}:
        raise ValueError(
            "Raw input must be .pdf, .txt, or .xhtml; canonical JSON needs no extraction"
        )
    if not isinstance(title, str) or not title.strip():
        raise ValueError("A non-empty document title is required")
    source_sha256 = file_sha256(source)
    if output.exists() or provenance.exists() or review_path(output).exists():
        if output.exists() and review_path(output).exists():
            approved = require_approved(output, read_json(output))
            if approved and approved["source_sha256"] == source_sha256:
                return output
        raise FileExistsError(
            f"Prepared output already exists; review or curate it without re-extracting: {output}"
        )

    cache = source_cache_dir(source_sha256)
    approved_path, extracted_path = cache / "approved.json", cache / "extraction.json"
    approved = read_json(approved_path) if approved_path.exists() else None
    if approved:
        saved = approved
    elif extracted_path.exists():
        saved = read_json(extracted_path)
    else:
        settings = ModelSettings.model_validate(
            {"provider": provider, **({"name": model} if model is not None else {})}
        )
        policy = SkillCallPolicy(
            max_tokens=32768,
            max_attachment_bytes=20_000_000 if source.suffix == ".pdf" else 500_000,
        )
        if source.stat().st_size > policy.max_attachment_bytes:
            raise ValueError(
                f"Source exceeds the {policy.max_attachment_bytes}-byte extraction limit"
            )
        # A PDF transcript is diagnostic, not a reliable paragraph oracle.
        source_reference(source, reference)
        started_message = f"Extraction was already started for this source: {cache}. Inspect its saved response or curate content; no automatic second call."
        if cache.exists():
            raise ValueError(started_message)
        client = client or create_skill_client(
            ROOT, ROOT / "_cache/skill-registry.json", settings.name, provider=settings.provider
        )
        skill = client.register(SKILL)
        cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache.mkdir(exist_ok=False)
        except FileExistsError as error:
            raise ValueError(started_message) from error
        write_json(
            cache / "request.json",
            {
                "source": str(source),
                "source_sha256": source_sha256,
                "domain": domain,
                "title": title,
                "model": settings.name,
                "provider": settings.provider,
            },
        )
        snapshot = cache / f"source{source.suffix}"
        shutil.copyfile(source, snapshot)
        if file_sha256(snapshot) != source_sha256:
            raise ValueError("Source changed while snapshotting; no model request was made")
        saved = _extract_source(
            snapshot, source_sha256, domain, title, settings, policy, client, skill
        )
        write_json(extracted_path, saved)

    content = saved["content"]
    validate_document(content)
    if strip_questions(content) != content:
        raise ValueError("Extraction must return content only, without generated questions")
    if approved:
        receipt = validate_approval(approved["review"], content)
        if (
            receipt["source_sha256"] != source_sha256
            or receipt["reference_sha256"]
            != hashlib.sha256(approved["reference_text"].encode()).hexdigest()
        ):
            raise ValueError(
                "Cached source review changed; inspect the saved artifact without re-extracting"
            )
    write_json(provenance, {**saved["provenance"], "requires_source_review": True})
    write_json(output, content)
    if approved:
        receipt = {**approved["review"], "source": str(source)}
        write_json(review_path(output), receipt)
        require_approved(output, content)
        write_review_report(output, approved["reference_text"], content, receipt)
    else:
        snapshot = cache / f"source{source.suffix}"
        review_document(snapshot if snapshot.exists() else source, output, reference=reference)
    return output


def _extract_source(source, source_sha256, domain, title, settings, policy, client, skill) -> dict:
    result = client.run_json_file(
        skill,
        EXTRACTION_PROMPTS["request"].format(title=title),
        source,
        content_schema(),
        policy=policy,
        cacheable_prompt=EXTRACTION_PROMPTS["instructions"].format(domain=domain),
    )
    return {
        "content": result.value,
        "provenance": {
            "schema_version": 1,
            "source": str(source),
            "source_sha256": source_sha256,
            "domain": domain,
            "title": title,
            "provider": settings.provider,
            "model": settings.name,
            "skill_sha256": directory_hash(SKILL),
            "response_id": result.response_id,
            "usage": result.usage,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--domain", choices=["academic", "legal", "narrative"], required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    parser.add_argument("--model")
    parser.add_argument(
        "--reference", type=Path, help="Reviewed UTF-8 paragraph transcript for fidelity checks"
    )
    args = parser.parse_args()
    output = extract_document(
        args.source,
        args.output,
        domain=args.domain,
        title=args.title,
        model=args.model,
        provider=args.provider,
        reference=args.reference,
    )
    record = read_json(review_path(output))
    print(
        f"{output}\nSource review: {record['status']}; {len(record['issues'])} issue(s). Open {output.with_suffix('.review.html')}"
    )


if __name__ == "__main__":
    main()
