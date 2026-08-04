"""Run monotonic merge, orphan-assignment, and question-revision epochs.

Groups can merge but never split or disappear. Existing paragraph memberships
are immutable; Claude only considers the currently unassigned paragraphs.
Question merges require reciprocal Claude judgments plus a deterministic
lexical threshold.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from align_graphs import text_similarity
from anthropic import Anthropic
from cache_utils import cached_system, log_cache_usage
from group_groups import group_links
from pipeline_paths import output_dir
from question_matching import (
    DEFAULT_MODEL,
    directional_question_matches,
    eligible_merge_links,
    reciprocal_question_links,
)
from question_synthesis import format_paragraphs, synthesize_question
from section_schema import SectionedPaper

OUTPUT_DIR = output_dir()
ASSIGNMENT_CACHE_DIR = OUTPUT_DIR / "_cache" / "epoch_assignments"
SYNTHESIS_CACHE_DIR = OUTPUT_DIR / "_cache" / "epoch_summaries"
MATCH_CACHE_DIR = OUTPUT_DIR / "_cache" / "epoch_question_matches"
DEFAULT_SECTION_WEIGHT = 0.15
DEFAULT_LEXICAL_THRESHOLD = float(os.environ.get("SME_SUPERGROUP_THRESHOLD", "0.33"))
DEFAULT_QUESTION_STABILITY = 0.97
DEFAULT_MATCH_TOP_K = int(os.environ.get("SME_MATCH_TOP_K", "3"))
MAX_BATCH_CHARS = int(os.environ.get("SME_ASSIGNMENT_BATCH_CHARS", "80000"))
DEFAULT_ASSIGNMENT_CONTEXT = os.environ.get("SME_ASSIGNMENT_CONTEXT", "question_only")
DEFAULT_REPRESENTATIVE_PER_PAPER = int(
    os.environ.get("SME_REPRESENTATIVE_PER_PAPER", "2")
)
DEFAULT_REPRESENTATIVE_MAX_PER_GROUP = int(
    os.environ.get("SME_REPRESENTATIVE_MAX_PER_GROUP", "6")
)
ASSIGNMENT_CONTEXTS = (
    "question_only",
    "representative_group_paragraphs",
    "all_group_paragraphs",
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "by",
    "can",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "these",
    "this",
    "to",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}

ASSIGNMENT_SYSTEM_PROMPT = """You assign currently UNASSIGNED academic-paper paragraphs to existing question groups.

For EVERY supplied paragraph, decide which existing group questions it substantively answers in the
larger argument of its paper. Assign zero, one, or multiple group ids. Conceptual role matters more
than shared vocabulary. Existing group memberships are intentionally not supplied and must not be
reconsidered. Paragraphs in the same source section have a modest coherence prior, but do not assign
a paragraph merely because its neighbors were assigned.

Use the exact supplied paragraph_id and group ids. Do not create, split, merge, or rename groups. Do not
report a numeric confidence. Do not force-fit evidence: when no question group is a substantive conceptual
match, return an empty group_ids list. Return every supplied paragraph exactly once, including those
assigned to no group."""

ASSIGNMENT_USER_PROMPT_TEMPLATE = """Epoch: {epoch}

Existing question groups:
{groups}

Currently unassigned complete paragraphs:

{formatted_paragraphs}

Return every supplied paragraph exactly once using the assignment tool."""

EVIDENCE_ASSIGNMENT_SYSTEM_PROMPT = """You assign currently UNASSIGNED academic-paper paragraphs to existing question groups.

For EVERY supplied paragraph, decide which existing group questions it substantively answers in the
larger argument of its paper. Assign zero, one, or multiple group ids. Conceptual role matters more
than shared vocabulary. For each group, you are given its question and EVERY complete paragraph
currently assigned to it. Treat those paragraphs as the group's full current evidence, not as new
assignment candidates. Existing memberships are immutable and must not be reconsidered. Paragraphs in
the same source section have a modest coherence prior, but do not assign a paragraph merely because its
neighbors were assigned.

Use the exact supplied paragraph_id and group ids. Do not create, split, merge, or rename groups. Do not
report a numeric confidence. Do not force-fit evidence: when no question group is a substantive conceptual
match, return an empty group_ids list. Return every supplied paragraph exactly once, including those
assigned to no group."""

EVIDENCE_ASSIGNMENT_USER_PROMPT_TEMPLATE = """Epoch: {epoch}

Existing question groups with ALL current assigned paragraph evidence:
{groups}

Currently unassigned complete paragraphs to evaluate:

{formatted_paragraphs}

Return every supplied paragraph exactly once using the assignment tool."""

REPRESENTATIVE_ASSIGNMENT_SYSTEM_PROMPT = """You assign currently UNASSIGNED academic-paper paragraphs to existing question groups.

For EVERY supplied paragraph, decide which existing group questions it substantively answers in the
larger argument of its paper. Assign zero, one, or multiple group ids. Conceptual role matters more
than shared vocabulary. For each group, you are given its question and a small deterministic set of
TF-IDF medoid paragraphs selected from its current immutable members. Treat those paragraphs as
representative evidence, not as new assignment candidates or the group's complete evidence. Existing
memberships are immutable and must not be reconsidered. Paragraphs in the same source section have a
modest coherence prior, but do not assign a paragraph merely because its neighbors were assigned.

Use the exact supplied paragraph_id and group ids. Do not create, split, merge, or rename groups. Do not
report a numeric confidence. Do not force-fit evidence: when no question group is a substantive conceptual
match, return an empty group_ids list. Return every supplied paragraph exactly once, including those
assigned to no group."""

REPRESENTATIVE_ASSIGNMENT_USER_PROMPT_TEMPLATE = """Epoch: {epoch}

Existing question groups with deterministic representative paragraph evidence:
{groups}

Currently unassigned complete paragraphs to evaluate:

{formatted_paragraphs}

Return every supplied paragraph exactly once using the assignment tool."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def paragraph_key(value: dict[str, Any]) -> tuple[str, str]:
    return str(value["paper"]), str(value.get("unit_id") or value.get("id"))


def paragraph_ref(value: dict[str, Any]) -> dict[str, str]:
    paper, unit_id = paragraph_key(value)
    return {"paper": paper, "unit_id": unit_id}


def assigned_keys(groups: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        paragraph_key(member) for group in groups for member in group.get("members", [])
    }


class TfidfScorer:
    """Small deterministic corpus-local question-to-paragraph similarity scorer."""

    method = "corpus-tfidf-cosine-v1"

    def __init__(self, paragraphs: list[dict[str, Any]]):
        self.document_count = len(paragraphs)
        document_frequency: Counter[str] = Counter()
        for paragraph in paragraphs:
            document_frequency.update(set(self._tokens(self._document_text(paragraph))))
        self.idf = {
            token: math.log((1 + self.document_count) / (1 + count)) + 1
            for token, count in document_frequency.items()
        }
        self.unknown_idf = math.log(1 + self.document_count) + 1

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [
            token
            for token in _TOKEN_RE.findall(text.lower())
            if token not in _STOPWORDS
        ]

    @staticmethod
    def _document_text(paragraph: dict[str, Any]) -> str:
        tag = paragraph.get("tag", "")
        return f"{tag} {tag} {paragraph.get('text', '')}"

    def _vector(self, text: str) -> dict[str, float]:
        counts = Counter(self._tokens(text))
        return {
            token: (1 + math.log(count)) * self.idf.get(token, self.unknown_idf)
            for token, count in counts.items()
        }

    @staticmethod
    def _cosine(
        left: dict[str, float], right: dict[str, float]
    ) -> float:
        if not left or not right:
            return 0.0
        dot = sum(weight * right.get(token, 0.0) for token, weight in left.items())
        left_norm = math.sqrt(sum(weight * weight for weight in left.values()))
        right_norm = math.sqrt(sum(weight * weight for weight in right.values()))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0

    def score(self, question: str, paragraph: dict[str, Any]) -> float:
        query = self._vector(question)
        document = self._vector(self._document_text(paragraph))
        return self._cosine(query, document)

    def paragraph_similarity(
        self, left: dict[str, Any], right: dict[str, Any]
    ) -> float:
        return self._cosine(
            self._vector(self._document_text(left)),
            self._vector(self._document_text(right)),
        )


def load_paragraphs() -> tuple[list[dict[str, Any]], dict[str, str]]:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    paragraphs: list[dict[str, Any]] = []
    titles: dict[str, str] = {}
    for entry in manifest:
        paper = SectionedPaper.model_validate(
            json.loads((OUTPUT_DIR / entry["file"]).read_text(encoding="utf-8"))
        )
        titles[paper.paper_id] = paper.title
        section_titles = {section.id: section.title for section in paper.sections}
        for paragraph in paper.paragraphs:
            paragraphs.append(
                {
                    "paper": paper.paper_id,
                    "unit_id": paragraph.id,
                    "parent_section_id": paragraph.parent_section_id,
                    "section_title": section_titles.get(
                        paragraph.parent_section_id, ""
                    ),
                    "tag": paragraph.tag,
                    "text": paragraph.text,
                }
            )
    return paragraphs, titles


def _rank_memberships(groups: list[dict[str, Any]]) -> None:
    memberships: dict[tuple[str, str], list[tuple[float, int, dict[str, Any]]]] = (
        defaultdict(list)
    )
    for group_index, group in enumerate(groups):
        for member in group.get("members", []):
            memberships[paragraph_key(member)].append(
                (float(member.get("combined_score", 0.0)), group_index, member)
            )
    for rows in memberships.values():
        rows.sort(key=lambda row: (-row[0], row[1]))
        for rank, (_, _, member) in enumerate(rows, 1):
            member["rank_for_paragraph"] = rank


def initial_epoch(
    paragraphs: list[dict[str, Any]], scorer: TfidfScorer
) -> dict[str, Any]:
    quote_groups = json.loads(
        (OUTPUT_DIR / "quote_groups.json").read_text(encoding="utf-8")
    )
    lookup = {paragraph_key(paragraph): paragraph for paragraph in paragraphs}
    groups = []
    for source in quote_groups.get("paragraphs", []):
        question = source.get("overarching_question", "")
        members = []
        for raw_member in source.get("members", []):
            key = paragraph_key(raw_member)
            paragraph = lookup.get(key)
            if not paragraph:
                continue
            semantic = round(scorer.score(question, paragraph), 4)
            members.append(
                {
                    "paper": key[0],
                    "unit_id": key[1],
                    "parent_section_id": paragraph["parent_section_id"],
                    "semantic_similarity": semantic,
                    "section_cohesion": 0.0,
                    "combined_score": semantic,
                    "assignment_semantic_similarity": semantic,
                    "assignment_section_cohesion": 0.0,
                    "assignment_combined_score": semantic,
                    "assignment_origin": "initial_reciprocal_paragraph_match",
                    "first_assigned_epoch": 0,
                    "source_group_ids": [source["group_id"]],
                    "inherited_from_group_ids": [],
                    "assignment_reason": "Initial reciprocal paragraph-question match",
                }
            )
        groups.append(
            {
                "group_id": source["group_id"],
                "parent_group_ids": [],
                "question": question,
                "members": members,
                "paragraph_links": source.get("links", []),
                "merge_evidence": [],
                "synthesis_provenance": source.get("synthesis_provenance", {}),
                "question_history": [
                    {
                        "epoch": 0,
                        "stage": "initial_group",
                        "question": question,
                        "parent_group_ids": [],
                    }
                ],
            }
        )
    _rank_memberships(groups)
    assigned = assigned_keys(groups)
    unassigned = [
        paragraph_ref(paragraph)
        for paragraph in paragraphs
        if paragraph_key(paragraph) not in assigned
    ]
    question_links_path = OUTPUT_DIR / "bidirectional_group_matches.json"
    question_links = (
        json.loads(question_links_path.read_text(encoding="utf-8"))
        if question_links_path.is_file()
        else []
    )
    return {
        "epoch": 0,
        "stage": "initial_groups",
        "created_at": utc_now(),
        "groups": groups,
        "group_count": len(groups),
        "assigned_unique_count": len(assigned),
        "membership_count": sum(len(group["members"]) for group in groups),
        "unassigned_paragraphs": unassigned,
        "question_match_links": question_links,
    }


def paragraph_batches(
    paragraphs: list[dict[str, Any]], max_chars: int = MAX_BATCH_CHARS
) -> list[list[dict[str, Any]]]:
    """Keep source sections together unless one section alone exceeds the limit."""
    sections: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    order: list[tuple[str, str]] = []
    for paragraph in paragraphs:
        key = (paragraph["paper"], paragraph["parent_section_id"])
        if key not in sections:
            order.append(key)
        sections[key].append(paragraph)

    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for key in order:
        section = sections[key]
        section_chars = sum(len(paragraph.get("text", "")) for paragraph in section)
        if current and current_chars + section_chars > max_chars:
            batches.append(current)
            current, current_chars = [], 0
        if section_chars <= max_chars:
            current.extend(section)
            current_chars += section_chars
            continue
        if current:
            batches.append(current)
            current, current_chars = [], 0
        oversized: list[dict[str, Any]] = []
        oversized_chars = 0
        for paragraph in section:
            length = len(paragraph.get("text", ""))
            if oversized and oversized_chars + length > max_chars:
                batches.append(oversized)
                oversized, oversized_chars = [], 0
            oversized.append(paragraph)
            oversized_chars += length
        if oversized:
            batches.append(oversized)
    if current:
        batches.append(current)
    return batches


def _assignment_tool(paragraph_ids: list[str], group_ids: list[str]) -> dict[str, Any]:
    return {
        "name": "record_paragraph_assignments",
        "description": "Record zero-or-more existing question-group assignments for every paragraph.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "assignments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "paragraph_id": {
                                "type": "string",
                                "enum": paragraph_ids,
                                "description": "Exact paper:paragraph reference supplied in the input.",
                            },
                            "group_ids": {
                                "type": "array",
                                "items": {"type": "string", "enum": group_ids},
                                "uniqueItems": True,
                            },
                            "reason": {"type": "string"},
                        },
                        "required": ["paragraph_id", "group_ids", "reason"],
                    },
                }
            },
            "required": ["assignments"],
        },
    }


def _greedy_tfidf_medoids(
    paragraphs: list[dict[str, Any]],
    scorer: TfidfScorer,
    count: int,
) -> list[dict[str, Any]]:
    """Choose deterministic medoids that greedily maximize TF-IDF coverage."""
    candidates = sorted(paragraphs, key=paragraph_key)
    target = min(count, len(candidates))
    if target == len(candidates):
        return candidates
    pair_scores: dict[
        tuple[tuple[str, str], tuple[str, str]], float
    ] = {}

    def similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
        pair = tuple(sorted((paragraph_key(left), paragraph_key(right))))
        if pair not in pair_scores:
            pair_scores[pair] = scorer.paragraph_similarity(left, right)
        return pair_scores[pair]

    selected: list[dict[str, Any]] = []
    while len(selected) < target:
        best: dict[str, Any] | None = None
        best_coverage = -1.0
        for candidate in candidates:
            if candidate in selected:
                continue
            medoids = [*selected, candidate]
            coverage = sum(
                max(similarity(paragraph, medoid) for medoid in medoids)
                for paragraph in candidates
            ) / len(candidates)
            if coverage > best_coverage + 1e-12 or (
                abs(coverage - best_coverage) <= 1e-12
                and (best is None or paragraph_key(candidate) < paragraph_key(best))
            ):
                best = candidate
                best_coverage = coverage
        if best is None:
            break
        selected.append(best)
    return selected


def representative_group_paragraphs(
    group: dict[str, Any],
    paragraph_by_key: dict[tuple[str, str], dict[str, Any]],
    scorer: TfidfScorer,
    *,
    per_paper: int,
    max_per_group: int,
) -> list[dict[str, Any]]:
    """Select up to N medoids per paper, then round-robin across papers."""
    by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for member in group.get("members", []):
        key = paragraph_key(member)
        if key in seen:
            continue
        seen.add(key)
        paragraph = paragraph_by_key.get(key)
        if paragraph is None:
            raise ValueError(
                f"Group {group['group_id']!r} references missing paragraph {key!r}"
            )
        by_paper[key[0]].append(paragraph)

    ranked = {
        paper: _greedy_tfidf_medoids(paragraphs, scorer, per_paper)
        for paper, paragraphs in sorted(by_paper.items())
    }
    selected: list[dict[str, Any]] = []
    rank = 0
    while len(selected) < max_per_group:
        added = False
        for paper in sorted(ranked):
            if rank < len(ranked[paper]):
                selected.append(ranked[paper][rank])
                added = True
                if len(selected) == max_per_group:
                    break
        if not added:
            break
        rank += 1
    return selected


def format_assignment_groups(
    groups: list[dict[str, Any]],
    assignment_context: str,
    corpus_paragraphs: list[dict[str, Any]] | None = None,
    scorer: TfidfScorer | None = None,
    representative_per_paper: int = DEFAULT_REPRESENTATIVE_PER_PAPER,
    representative_max_per_group: int = DEFAULT_REPRESENTATIVE_MAX_PER_GROUP,
) -> tuple[str, dict[str, Any]]:
    if assignment_context not in ASSIGNMENT_CONTEXTS:
        raise ValueError(f"Unknown assignment context: {assignment_context!r}")
    if assignment_context == "question_only":
        text = "\n".join(
            f"- {group['group_id']}: {group['question']}" for group in groups
        )
        return text, {
            "mode": assignment_context,
            "group_count": len(groups),
            "evidence_membership_count": 0,
            "evidence_unique_paragraph_count": 0,
            "evidence_characters": 0,
        }

    if corpus_paragraphs is None:
        raise ValueError(f"{assignment_context} context requires the complete corpus")
    if assignment_context == "representative_group_paragraphs" and scorer is None:
        raise ValueError("representative context requires a deterministic TF-IDF scorer")
    paragraph_by_key = {
        paragraph_key(paragraph): paragraph for paragraph in corpus_paragraphs
    }
    blocks = []
    evidence_keys: list[tuple[str, str]] = []
    evidence_characters = 0
    group_evidence = []
    for group in groups:
        if assignment_context == "representative_group_paragraphs":
            assert scorer is not None
            member_paragraphs = representative_group_paragraphs(
                group,
                paragraph_by_key,
                scorer,
                per_paper=representative_per_paper,
                max_per_group=representative_max_per_group,
            )
            evidence_label = "Deterministic TF-IDF medoid paragraphs"
        else:
            member_paragraphs = []
            for member in group.get("members", []):
                key = paragraph_key(member)
                if key not in paragraph_by_key:
                    raise ValueError(
                        f"Group {group['group_id']!r} references missing paragraph {key!r}"
                    )
                member_paragraphs.append(paragraph_by_key[key])
            evidence_label = "All current assigned paragraphs"
        selected_keys = [paragraph_key(paragraph) for paragraph in member_paragraphs]
        evidence_keys.extend(selected_keys)
        evidence_characters += sum(
            len(paragraph.get("text", "")) for paragraph in member_paragraphs
        )
        group_evidence.append(
            {
                "group_id": group["group_id"],
                "paragraph_ids": [f"{paper}:{unit_id}" for paper, unit_id in selected_keys],
            }
        )
        formatted = (
            format_paragraphs(member_paragraphs) if member_paragraphs else "(none)"
        )
        blocks.append(
            f"=== GROUP {group['group_id']} ===\n"
            f"Question: {group['question']}\n"
            f"{evidence_label} ({len(member_paragraphs)} memberships):\n"
            f"{formatted}"
        )
    return "\n\n--- NEXT QUESTION GROUP ---\n\n".join(blocks), {
        "mode": assignment_context,
        "group_count": len(groups),
        "evidence_membership_count": len(evidence_keys),
        "evidence_unique_paragraph_count": len(set(evidence_keys)),
        "evidence_characters": evidence_characters,
        "selection_method": "corpus-tfidf-greedy-k-medoids-per-paper-v1"
        if assignment_context == "representative_group_paragraphs"
        else "all-current-memberships",
        "representative_per_paper": representative_per_paper
        if assignment_context == "representative_group_paragraphs"
        else None,
        "representative_max_per_group": representative_max_per_group
        if assignment_context == "representative_group_paragraphs"
        else None,
        "group_evidence": group_evidence,
    }


def assign_batch(
    epoch: int,
    batch_index: int,
    groups: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    *,
    assignment_context: str = DEFAULT_ASSIGNMENT_CONTEXT,
    corpus_paragraphs: list[dict[str, Any]] | None = None,
    scorer: TfidfScorer | None = None,
    representative_per_paper: int = DEFAULT_REPRESENTATIVE_PER_PAPER,
    representative_max_per_group: int = DEFAULT_REPRESENTATIVE_MAX_PER_GROUP,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
) -> list[dict[str, Any]]:
    group_text, context_provenance = format_assignment_groups(
        groups,
        assignment_context,
        corpus_paragraphs,
        scorer,
        representative_per_paper,
        representative_max_per_group,
    )
    paragraph_ids = [
        f"{paper}:{unit_id}"
        for paper, unit_id in (paragraph_key(paragraph) for paragraph in paragraphs)
    ]
    system_prompt = {
        "question_only": ASSIGNMENT_SYSTEM_PROMPT,
        "representative_group_paragraphs": REPRESENTATIVE_ASSIGNMENT_SYSTEM_PROMPT,
        "all_group_paragraphs": EVIDENCE_ASSIGNMENT_SYSTEM_PROMPT,
    }[assignment_context]
    user_template = {
        "question_only": ASSIGNMENT_USER_PROMPT_TEMPLATE,
        "representative_group_paragraphs": REPRESENTATIVE_ASSIGNMENT_USER_PROMPT_TEMPLATE,
        "all_group_paragraphs": EVIDENCE_ASSIGNMENT_USER_PROMPT_TEMPLATE,
    }[assignment_context]
    prompt = user_template.format(
        epoch=epoch,
        groups=group_text,
        formatted_paragraphs=format_paragraphs(paragraphs),
    )
    tool = _assignment_tool(paragraph_ids, [group["group_id"] for group in groups])
    prompt_hash = hashlib.sha256(
        (
            f"{model}\n{system_prompt}\n"
            + json.dumps(tool, sort_keys=True)
            + f"\n{prompt}"
        ).encode("utf-8")
    ).hexdigest()
    cache_path = (
        ASSIGNMENT_CACHE_DIR
        / f"epoch_{epoch}"
        / f"batch_{batch_index}__{prompt_hash[:16]}.json"
    )
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))["assignments"]

    anthropic = client or Anthropic()
    response = anthropic.messages.create(
        model=model,
        max_tokens=min(12_000, max(2_000, len(paragraphs) * 140)),
        system=cached_system(system_prompt),
        messages=[{"role": "user", "content": prompt}],
        tools=[tool],
        tool_choice={"type": "tool", "name": "record_paragraph_assignments"},
    )
    log_cache_usage(f"epoch {epoch} orphan batch {batch_index}", response)

    raw_assignments: list[dict[str, Any]] | None = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "record_paragraph_assignments":
            data = block.input
            if isinstance(data, dict):
                raw_assignments = data.get("assignments")
            break
    if raw_assignments is None:
        raise RuntimeError(
            f"Claude did not return assignments for epoch {epoch}, batch {batch_index}"
        )

    expected = {paragraph_key(paragraph) for paragraph in paragraphs}
    key_by_ref = {f"{paper}:{unit_id}": (paper, unit_id) for paper, unit_id in expected}
    allowed_groups = {group["group_id"] for group in groups}
    normalized_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for assignment in raw_assignments:
        raw_ref = str(assignment.get("paragraph_id", ""))
        key = key_by_ref.get(raw_ref)
        if key not in expected:
            raise ValueError(f"Invalid paragraph assignment: {raw_ref!r}")
        selected = list(dict.fromkeys(assignment.get("group_ids", [])))
        unknown = set(selected) - allowed_groups
        if unknown:
            raise ValueError(f"Claude returned unknown group ids: {sorted(unknown)}")
        reason = " ".join(str(assignment.get("reason", "")).split())
        existing = normalized_by_key.get(key)
        if existing is None:
            normalized_by_key[key] = {
                "paper": key[0],
                "unit_id": key[1],
                "paragraph_id": raw_ref,
                "group_ids": selected,
                "reason": reason,
                "source_record_count": 1,
            }
            continue

        # Tool schemas cannot enforce uniqueness across array items. Preserve all
        # Claude-selected memberships if it emits the same paragraph more than once.
        existing["group_ids"] = list(
            dict.fromkeys([*existing["group_ids"], *selected])
        )
        if reason and reason not in existing["reason"].split(" | "):
            existing["reason"] = " | ".join(
                value for value in (existing["reason"], reason) if value
            )
        existing["source_record_count"] += 1

    missing = expected - set(normalized_by_key)
    if missing:
        raise ValueError(
            f"Claude omitted {len(missing)} paragraphs: {sorted(missing)[:5]}"
        )
    normalized = list(normalized_by_key.values())

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "prompt_hash": prompt_hash,
                "model": model,
                "assignment_context": context_provenance,
                "assignment_candidate_count": len(paragraphs),
                "prompt_characters": len(prompt),
                "assignments": normalized,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return normalized


def assign_all(
    epoch: int,
    groups: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    *,
    assignment_context: str = DEFAULT_ASSIGNMENT_CONTEXT,
    corpus_paragraphs: list[dict[str, Any]] | None = None,
    scorer: TfidfScorer | None = None,
    representative_per_paper: int = DEFAULT_REPRESENTATIVE_PER_PAPER,
    representative_max_per_group: int = DEFAULT_REPRESENTATIVE_MAX_PER_GROUP,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
) -> list[dict[str, Any]]:
    if not paragraphs or not groups:
        return []
    assignments = []
    batches = paragraph_batches(paragraphs)
    for index, batch in enumerate(batches, start=1):
        print(
            f"  epoch {epoch}: assigning orphan batch {index}/{len(batches)} "
            f"({len(batch)} complete paragraphs, "
            f"{sum(len(paragraph['text']) for paragraph in batch):,} chars)"
        )
        assignments.extend(
            assign_batch(
                epoch,
                index,
                groups,
                batch,
                assignment_context=assignment_context,
                corpus_paragraphs=corpus_paragraphs,
                scorer=scorer,
                representative_per_paper=representative_per_paper,
                representative_max_per_group=representative_max_per_group,
                model=model,
                client=client,
            )
        )
    return assignments


def score_assignments(
    groups: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    scorer: TfidfScorer,
    section_weight: float,
    *,
    corpus_paragraphs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    group_by_id = {group["group_id"]: group for group in groups}
    paragraph_by_key = {paragraph_key(paragraph): paragraph for paragraph in paragraphs}
    selected_by_group = {
        group_id: {paragraph_key(member) for member in group.get("members", [])}
        for group_id, group in group_by_id.items()
    }
    for assignment in assignments:
        key = paragraph_key(assignment)
        for group_id in assignment["group_ids"]:
            selected_by_group[group_id].add(key)

    corpus = corpus_paragraphs or paragraphs
    section_members: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for paragraph in corpus:
        key = paragraph_key(paragraph)
        section_members[(paragraph["paper"], paragraph["parent_section_id"])].add(key)

    decisions = []
    for assignment in assignments:
        key = paragraph_key(assignment)
        paragraph = paragraph_by_key[key]
        section_key = (paragraph["paper"], paragraph["parent_section_id"])
        peers = section_members[section_key] - {key}
        candidates = []
        for group_id, group in group_by_id.items():
            semantic = scorer.score(group["question"], paragraph)
            selected_peers = len(peers & selected_by_group[group_id])
            cohesion = selected_peers / len(peers) if peers else 0.0
            combined = (1 - section_weight) * semantic + section_weight * cohesion
            candidates.append(
                {
                    "group_id": group_id,
                    "claude_selected": group_id in assignment["group_ids"],
                    "semantic_similarity": round(semantic, 4),
                    "section_cohesion": round(cohesion, 4),
                    "section_weight": section_weight,
                    "combined_score": round(combined, 4),
                }
            )
        selected_candidates = sorted(
            (candidate for candidate in candidates if candidate["claude_selected"]),
            key=lambda candidate: (-candidate["combined_score"], candidate["group_id"]),
        )
        ranks = {
            candidate["group_id"]: index
            for index, candidate in enumerate(selected_candidates, 1)
        }
        for candidate in candidates:
            candidate["rank_for_paragraph"] = ranks.get(candidate["group_id"])
        decisions.append(
            {
                "paper": key[0],
                "unit_id": key[1],
                "parent_section_id": paragraph["parent_section_id"],
                "reason": assignment["reason"],
                "source_record_count": assignment.get("source_record_count", 1),
                "selected_group_ids": assignment["group_ids"],
                "candidates": candidates,
            }
        )
    return decisions


def _merge_duplicate_members(
    parent_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    direct_parents: dict[tuple[str, str], set[str]] = defaultdict(set)
    for group in parent_groups:
        for member in group.get("members", []):
            key = paragraph_key(member)
            direct_parents[key].add(group["group_id"])
            if key not in by_key:
                by_key[key] = copy.deepcopy(member)
                continue
            existing = by_key[key]
            if float(member.get("combined_score", 0.0)) > float(
                existing.get("combined_score", 0.0)
            ):
                preserved_sources = set(existing.get("source_group_ids", []))
                by_key[key] = copy.deepcopy(member)
                by_key[key]["source_group_ids"] = sorted(
                    preserved_sources | set(member.get("source_group_ids", []))
                )
            else:
                existing["source_group_ids"] = sorted(
                    set(existing.get("source_group_ids", []))
                    | set(member.get("source_group_ids", []))
                )
    for key, member in by_key.items():
        member["inherited_from_group_ids"] = sorted(direct_parents[key])
    return list(by_key.values())


def merge_groups(
    previous_groups: list[dict[str, Any]],
    components: list[dict[str, Any]],
    paragraphs: list[dict[str, Any]],
    scorer: TfidfScorer,
    *,
    epoch_number: int,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    previous_by_id = {group["group_id"]: group for group in previous_groups}
    paragraph_by_key = {paragraph_key(paragraph): paragraph for paragraph in paragraphs}
    groups = []
    merge_events = []
    merge_number = 1
    for component in components:
        parent_ids = list(
            component.get("parent_group_ids")
            or [member["group_id"] for member in component.get("members", [])]
        )
        parents = [previous_by_id[group_id] for group_id in parent_ids]
        is_merged = len(parent_ids) > 1
        if is_merged:
            group_id = (
                component.get("super_group_id")
                or f"epoch_{epoch_number}_merged_{merge_number}"
            )
            if epoch_number > 1 or not str(group_id).startswith("super_group_"):
                group_id = f"epoch_{epoch_number}_merged_{merge_number}"
            merge_number += 1
            members = _merge_duplicate_members(parents)
            source_paragraphs = [
                paragraph_by_key[paragraph_key(member)]
                for member in members
                if paragraph_key(member) in paragraph_by_key
            ]
            existing_question = component.get("overarching_question")
            existing_provenance = component.get("synthesis_provenance")
            if existing_question:
                question = existing_question
                synthesis = existing_provenance or {
                    "overarching_question": question,
                    "type": "precomputed_merge_question",
                }
            else:
                synthesis = synthesize_question(
                    group_id,
                    source_paragraphs,
                    SYNTHESIS_CACHE_DIR / f"epoch_{epoch_number}" / "merge",
                    previous_questions=[parent["question"] for parent in parents],
                    model=model,
                    client=client,
                )
                question = synthesis["overarching_question"]
            for member in members:
                paragraph = paragraph_by_key[paragraph_key(member)]
                member["semantic_similarity"] = round(
                    scorer.score(question, paragraph), 4
                )
            merge_event = {
                "group_id": group_id,
                "parent_group_ids": parent_ids,
                "question": question,
                "links": component.get("links", []),
            }
            merge_events.append(merge_event)
            history = [
                item
                for parent in parents
                for item in parent.get("question_history", [])
            ]
            history.append(
                {
                    "epoch": epoch_number,
                    "stage": "merge",
                    "question": question,
                    "parent_group_ids": parent_ids,
                }
            )
            groups.append(
                {
                    "group_id": group_id,
                    "parent_group_ids": parent_ids,
                    "question": question,
                    "members": members,
                    "paragraph_links": [
                        link
                        for parent in parents
                        for link in parent.get("paragraph_links", [])
                    ],
                    "merge_evidence": component.get("links", []),
                    "synthesis_provenance": synthesis,
                    "question_history": history,
                }
            )
            continue

        source = copy.deepcopy(parents[0])
        source["parent_group_ids"] = [source["group_id"]]
        source["merge_evidence"] = []
        groups.append(source)
    _rank_memberships(groups)
    return groups, merge_events


def apply_assignments(
    groups: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    paragraph_by_key: dict[tuple[str, str], dict[str, Any]],
    *,
    epoch_number: int,
) -> tuple[
    list[dict[str, Any]], list[dict[str, str]], dict[str, list[tuple[str, str]]]
]:
    updated = copy.deepcopy(groups)
    group_by_id = {group["group_id"]: group for group in updated}
    newly_assigned = []
    gained_by_group: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for decision in decisions:
        key = paragraph_key(decision)
        selected = list(decision["selected_group_ids"])
        if selected:
            newly_assigned.append({"paper": key[0], "unit_id": key[1]})
        candidate_by_id = {
            candidate["group_id"]: candidate for candidate in decision["candidates"]
        }
        paragraph = paragraph_by_key[key]
        for group_id in selected:
            candidate = candidate_by_id[group_id]
            group_by_id[group_id]["members"].append(
                {
                    "paper": key[0],
                    "unit_id": key[1],
                    "parent_section_id": paragraph["parent_section_id"],
                    "semantic_similarity": candidate["semantic_similarity"],
                    "section_cohesion": candidate["section_cohesion"],
                    "combined_score": candidate["combined_score"],
                    "assignment_semantic_similarity": candidate["semantic_similarity"],
                    "assignment_section_cohesion": candidate["section_cohesion"],
                    "assignment_combined_score": candidate["combined_score"],
                    "rank_for_paragraph": candidate["rank_for_paragraph"],
                    "assignment_origin": "claude_orphan_assignment",
                    "first_assigned_epoch": epoch_number,
                    "source_group_ids": [],
                    "inherited_from_group_ids": [],
                    "assignment_reason": decision["reason"],
                }
            )
            gained_by_group[group_id].append(key)
    _rank_memberships(updated)
    return updated, newly_assigned, gained_by_group


def revise_questions(
    groups: list[dict[str, Any]],
    gained_by_group: dict[str, list[tuple[str, str]]],
    paragraph_by_key: dict[tuple[str, str], dict[str, Any]],
    scorer: TfidfScorer,
    *,
    epoch_number: int,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    revised = copy.deepcopy(groups)
    revisions = []
    for group in revised:
        gained = gained_by_group.get(group["group_id"], [])
        if not gained:
            continue
        previous_question = group["question"]
        source_paragraphs = [
            paragraph_by_key[paragraph_key(member)]
            for member in group["members"]
            if paragraph_key(member) in paragraph_by_key
        ]
        synthesis = synthesize_question(
            group["group_id"],
            source_paragraphs,
            SYNTHESIS_CACHE_DIR / f"epoch_{epoch_number}" / "revision",
            previous_questions=[previous_question],
            model=model,
            client=client,
        )
        question = synthesis["overarching_question"]
        similarity = round(text_similarity(previous_question, question), 4)
        changed = question != previous_question
        group["question"] = question
        group["synthesis_provenance"] = synthesis
        group.setdefault("question_history", []).append(
            {
                "epoch": epoch_number,
                "stage": "post_assignment_revision",
                "question": question,
                "previous_question": previous_question,
                "new_paragraph_ids": [
                    f"{paper}:{unit_id}" for paper, unit_id in gained
                ],
            }
        )
        for member in group["members"]:
            paragraph = paragraph_by_key[paragraph_key(member)]
            member["semantic_similarity"] = round(scorer.score(question, paragraph), 4)
        revisions.append(
            {
                "group_id": group["group_id"],
                "previous_question": previous_question,
                "question": question,
                "question_similarity": similarity,
                "changed": changed,
                "new_paragraph_ids": [
                    f"{paper}:{unit_id}" for paper, unit_id in gained
                ],
                "synthesis_provenance": synthesis,
            }
        )
    return revised, revisions


def build_changes(
    decisions: list[dict[str, Any]], epoch_number: int
) -> list[dict[str, Any]]:
    return [
        {
            "paper": decision["paper"],
            "unit_id": decision["unit_id"],
            "previous_group_ids": [],
            "selected_parent_group_ids": list(decision["selected_group_ids"]),
            "current_group_ids": list(decision["selected_group_ids"]),
            "removed_from": [],
            "joined": list(decision["selected_group_ids"]),
            "shifted": bool(decision["selected_group_ids"]),
            "became_unassigned": False,
            "newly_assigned": bool(decision["selected_group_ids"]),
            "still_unassigned": not decision["selected_group_ids"],
            "first_assigned_epoch": epoch_number
            if decision["selected_group_ids"]
            else None,
        }
        for decision in decisions
    ]


def _component_specs_for_epoch(
    groups: list[dict[str, Any]],
    epoch_number: int,
    *,
    lexical_threshold: float,
    match_top_k: int,
    model: str,
    client: Anthropic | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    directional = directional_question_matches(
        groups,
        MATCH_CACHE_DIR / f"epoch_{epoch_number}",
        label=f"epoch_{epoch_number}",
        top_k=match_top_k,
        model=model,
        client=client,
    )
    reciprocal = reciprocal_question_links(directional)
    eligible = eligible_merge_links(reciprocal, lexical_threshold)
    components = group_links(groups, eligible)
    merge_number = 1
    for component in components:
        if component["is_merged"]:
            component["super_group_id"] = f"epoch_{epoch_number}_merged_{merge_number}"
            merge_number += 1
    return components, directional, reciprocal


def refine_once(
    epoch_number: int,
    previous_epoch: dict[str, Any],
    paragraphs: list[dict[str, Any]],
    scorer: TfidfScorer,
    *,
    section_weight: float,
    lexical_threshold: float,
    question_stability_threshold: float,
    match_top_k: int,
    assignment_context: str = DEFAULT_ASSIGNMENT_CONTEXT,
    representative_per_paper: int = DEFAULT_REPRESENTATIVE_PER_PAPER,
    representative_max_per_group: int = DEFAULT_REPRESENTATIVE_MAX_PER_GROUP,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
    initial_components: list[dict[str, Any]] | None = None,
    initial_directional: list[dict[str, Any]] | None = None,
    initial_reciprocal: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    previous_groups = previous_epoch["groups"]
    previous_assigned = assigned_keys(previous_groups)
    paragraph_by_key = {paragraph_key(paragraph): paragraph for paragraph in paragraphs}
    orphan_paragraphs = [
        paragraph
        for paragraph in paragraphs
        if paragraph_key(paragraph) not in previous_assigned
    ]

    if initial_components is None:
        components, directional, reciprocal = _component_specs_for_epoch(
            previous_groups,
            epoch_number,
            lexical_threshold=lexical_threshold,
            match_top_k=match_top_k,
            model=model,
            client=client,
        )
    else:
        components = initial_components
        directional = initial_directional or []
        reciprocal = initial_reciprocal or []

    merged_groups, merge_events = merge_groups(
        previous_groups,
        components,
        paragraphs,
        scorer,
        epoch_number=epoch_number,
        model=model,
        client=client,
    )
    if len(merged_groups) > len(previous_groups):
        raise AssertionError("Epoch refinement split a group; group count increased")
    if assigned_keys(merged_groups) != previous_assigned:
        raise AssertionError("Merging changed the unique assigned paragraph set")

    raw_assignments = assign_all(
        epoch_number,
        merged_groups,
        orphan_paragraphs,
        assignment_context=assignment_context,
        corpus_paragraphs=paragraphs,
        scorer=scorer,
        representative_per_paper=representative_per_paper,
        representative_max_per_group=representative_max_per_group,
        model=model,
        client=client,
    )
    _, assignment_context_provenance = format_assignment_groups(
        merged_groups,
        assignment_context,
        paragraphs,
        scorer,
        representative_per_paper,
        representative_max_per_group,
    )
    decisions = score_assignments(
        merged_groups,
        orphan_paragraphs,
        raw_assignments,
        scorer,
        section_weight,
        corpus_paragraphs=paragraphs,
    )
    assignment_groups, newly_assigned, gained_by_group = apply_assignments(
        merged_groups,
        decisions,
        paragraph_by_key,
        epoch_number=epoch_number,
    )
    current_assigned = assigned_keys(assignment_groups)
    if not previous_assigned <= current_assigned:
        raise AssertionError("Existing paragraph assignments were removed")

    final_groups, revisions = revise_questions(
        assignment_groups,
        gained_by_group,
        paragraph_by_key,
        scorer,
        epoch_number=epoch_number,
        model=model,
        client=client,
    )
    final_assigned = assigned_keys(final_groups)
    if current_assigned != final_assigned:
        raise AssertionError("Question revision changed paragraph memberships")
    remaining_unassigned = [
        paragraph_ref(paragraph)
        for paragraph in paragraphs
        if paragraph_key(paragraph) not in final_assigned
    ]
    changes = build_changes(decisions, epoch_number)
    questions_stable = all(
        revision["question_similarity"] >= question_stability_threshold
        for revision in revisions
    )
    stable = not merge_events and not newly_assigned and questions_stable
    carried = [
        group["group_id"]
        for group in merged_groups
        if len(group.get("parent_group_ids", [])) == 1
    ]
    return {
        "epoch": epoch_number,
        "created_at": utc_now(),
        "input_group_count": len(previous_groups),
        "merge": {
            "groups": copy.deepcopy(merged_groups),
            "group_count": len(merged_groups),
            "events": merge_events,
            "carried_group_ids": carried,
            "directional_matches": directional,
            "reciprocal_links": reciprocal,
            "lexical_threshold": lexical_threshold,
            "unassigned_paragraphs": [
                paragraph_ref(item) for item in orphan_paragraphs
            ],
        },
        "assignment": {
            "groups": copy.deepcopy(assignment_groups),
            "context": assignment_context_provenance,
            "evaluated_paragraph_count": len(orphan_paragraphs),
            "decisions": decisions,
            "newly_assigned_paragraphs": newly_assigned,
            "remaining_unassigned_paragraphs": remaining_unassigned,
        },
        "question_revision": {
            "groups": copy.deepcopy(final_groups),
            "revisions": revisions,
        },
        "groups": final_groups,
        "group_count": len(final_groups),
        "assigned_unique_count": len(final_assigned),
        "membership_count": sum(len(group["members"]) for group in final_groups),
        "assignment_decisions": decisions,
        "paragraph_changes": changes,
        "newly_assigned_paragraphs": newly_assigned,
        "retired_group_ids": [],
        "unassigned_paragraphs": remaining_unassigned,
        "stability": {
            "stable": stable,
            "no_merges": not merge_events,
            "no_new_assignments": not newly_assigned,
            "questions_stable": questions_stable,
            "question_threshold": question_stability_threshold,
            "reason": "no merges, new assignments, or material question changes"
            if stable
            else "refinement continues",
        },
    }


def run_epochs(
    max_epochs: int,
    *,
    section_weight: float = DEFAULT_SECTION_WEIGHT,
    lexical_threshold: float = DEFAULT_LEXICAL_THRESHOLD,
    question_stability_threshold: float = DEFAULT_QUESTION_STABILITY,
    match_top_k: int = DEFAULT_MATCH_TOP_K,
    assignment_context: str = DEFAULT_ASSIGNMENT_CONTEXT,
    representative_per_paper: int = DEFAULT_REPRESENTATIVE_PER_PAPER,
    representative_max_per_group: int = DEFAULT_REPRESENTATIVE_MAX_PER_GROUP,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
) -> dict[str, Any]:
    if assignment_context not in ASSIGNMENT_CONTEXTS:
        raise ValueError(f"Unknown assignment context: {assignment_context!r}")
    if representative_per_paper < 1 or representative_max_per_group < 1:
        raise ValueError("Representative evidence limits must be positive")
    paragraphs, paper_titles = load_paragraphs()
    scorer = TfidfScorer(paragraphs)
    initial = initial_epoch(paragraphs, scorer)
    history = {
        "schema_version": 3,
        "run_id": os.environ.get("SME_RUN_ID", "manual"),
        "status": "running",
        "started_at": utc_now(),
        "completed_at": None,
        "paper_titles": paper_titles,
        "similarity_method": scorer.method,
        "merge_similarity_method": "reciprocal Claude conceptual judgment AND lexical-jaccard-sequence-v1",
        "config": {
            "max_epochs": max_epochs,
            "section_weight": section_weight,
            "section_scope": "same source-paper section only",
            "merge_lexical_threshold": lexical_threshold,
            "question_stability_threshold": question_stability_threshold,
            "match_top_k": match_top_k,
            "assignment_provider": "Claude",
            "assignment_context": assignment_context,
            "representative_per_paper": representative_per_paper,
            "representative_max_per_group": representative_max_per_group,
            "merge_judge_provider": "Claude",
            "model": model,
            "membership": "sticky zero-or-more groups; only unassigned paragraphs are evaluated",
            "group_constraint": "merge only; singletons persist; never split or retire",
        },
        "initial_state": initial,
        "epochs": [],
        "stop_reason": None,
    }
    output_path = OUTPUT_DIR / "epoch_history.json"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(history, indent=2), encoding="utf-8")

    initial_components = json.loads(
        (OUTPUT_DIR / "group_of_groups.json").read_text(encoding="utf-8")
    )
    initial_directional = json.loads(
        (OUTPUT_DIR / "group_matches.json").read_text(encoding="utf-8")
    )
    initial_reciprocal = json.loads(
        (OUTPUT_DIR / "bidirectional_group_matches.json").read_text(encoding="utf-8")
    )

    previous = initial
    for epoch_number in range(1, max_epochs + 1):
        print(
            f"Epoch {epoch_number}/{max_epochs}: {previous['group_count']} input groups, "
            f"{len(previous['unassigned_paragraphs'])} unassigned paragraphs"
        )
        epoch = refine_once(
            epoch_number,
            previous,
            paragraphs,
            scorer,
            section_weight=section_weight,
            lexical_threshold=lexical_threshold,
            question_stability_threshold=question_stability_threshold,
            match_top_k=match_top_k,
            assignment_context=assignment_context,
            representative_per_paper=representative_per_paper,
            representative_max_per_group=representative_max_per_group,
            model=model,
            client=client,
            initial_components=initial_components if epoch_number == 1 else None,
            initial_directional=initial_directional if epoch_number == 1 else None,
            initial_reciprocal=initial_reciprocal if epoch_number == 1 else None,
        )
        history["epochs"].append(epoch)
        output_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
        print(
            f"Epoch {epoch_number}: {epoch['group_count']} groups, "
            f"{len(epoch['newly_assigned_paragraphs'])} newly assigned, "
            f"{len(epoch['unassigned_paragraphs'])} unassigned"
        )
        previous = epoch
        if epoch["stability"]["stable"]:
            history["stop_reason"] = (
                "converged before maximum epoch"
                if epoch_number < max_epochs
                else "converged at maximum epoch"
            )
            break
    else:
        history["stop_reason"] = "maximum epoch reached"

    history["status"] = "complete"
    history["completed_at"] = utc_now()
    output_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    print(
        f"Wrote initial state and {len(history['epochs'])} monotonic epochs to "
        f"{output_path}"
    )
    return history


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-epochs", type=int, default=3)
    parser.add_argument("--section-weight", type=float, default=DEFAULT_SECTION_WEIGHT)
    parser.add_argument(
        "--merge-lexical-threshold", type=float, default=DEFAULT_LEXICAL_THRESHOLD
    )
    parser.add_argument(
        "--question-stability-threshold", type=float, default=DEFAULT_QUESTION_STABILITY
    )
    parser.add_argument("--match-top-k", type=int, default=DEFAULT_MATCH_TOP_K)
    parser.add_argument(
        "--assignment-context",
        choices=ASSIGNMENT_CONTEXTS,
        default=DEFAULT_ASSIGNMENT_CONTEXT,
    )
    parser.add_argument(
        "--representative-per-paper",
        type=int,
        default=DEFAULT_REPRESENTATIVE_PER_PAPER,
    )
    parser.add_argument(
        "--representative-max-per-group",
        type=int,
        default=DEFAULT_REPRESENTATIVE_MAX_PER_GROUP,
    )
    args = parser.parse_args()
    if args.max_epochs < 0:
        parser.error("--max-epochs must be non-negative")
    for name in (
        "section_weight",
        "merge_lexical_threshold",
        "question_stability_threshold",
    ):
        if not 0 <= getattr(args, name) <= 1:
            parser.error(f"--{name.replace('_', '-')} must be between 0 and 1")
    if args.match_top_k < 1:
        parser.error("--match-top-k must be positive")
    if args.representative_per_paper < 1:
        parser.error("--representative-per-paper must be positive")
    if args.representative_max_per_group < 1:
        parser.error("--representative-max-per-group must be positive")
    run_epochs(
        args.max_epochs,
        section_weight=args.section_weight,
        lexical_threshold=args.merge_lexical_threshold,
        question_stability_threshold=args.question_stability_threshold,
        match_top_k=args.match_top_k,
        assignment_context=args.assignment_context,
        representative_per_paper=args.representative_per_paper,
        representative_max_per_group=args.representative_max_per_group,
    )


if __name__ == "__main__":
    main()
