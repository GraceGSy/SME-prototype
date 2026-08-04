"""Claude-judged, lexically gated reciprocal matching for group questions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from align_graphs import text_similarity
from anthropic import Anthropic
from cache_utils import cached_system, log_cache_usage

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You judge whether question groups in an academic-paper analysis should merge.

For every supplied source group, select zero or more OTHER group ids whose questions are conceptually
equivalent: they ask substantially the same question and their evidence could be combined under one
coherent question without erasing an important distinction. Conceptual role matters more than shared
words. Do not select a group merely because it discusses the same system, method, or broad topic.

Treat each source direction separately. Return every source group exactly once, never select the source
itself, use only supplied ids, and select at most the requested number of matches. Give a concise reason
for each selected match. Do not report confidence or similarity scores."""

USER_PROMPT_TEMPLATE = """Maximum matches per source: {top_k}

Question groups:
{questions}

Record directional conceptual matches for every source group using the tool."""


def group_question(group: dict[str, Any]) -> str:
    return str(group.get("question") or group.get("overarching_question") or "")


def _tool(group_ids: list[str], top_k: int) -> dict[str, Any]:
    return {
        "name": "record_directional_question_matches",
        "description": "Record conceptual question matches in every source direction.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "group_id": {"type": "string", "enum": group_ids},
                            "matches": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "group_id": {
                                            "type": "string",
                                            "enum": group_ids,
                                        },
                                        "reason": {"type": "string"},
                                    },
                                    "required": ["group_id", "reason"],
                                },
                            },
                        },
                        "required": ["group_id", "matches"],
                    },
                }
            },
            "required": ["sources"],
        },
    }


def _safe_label(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _validate_sources(
    raw_sources: Any, group_ids: list[str], top_k: int
) -> dict[str, list[dict[str, str]]]:
    if not isinstance(raw_sources, list):
        raise TypeError("sources was not an array")
    allowed = set(group_ids)
    by_source: dict[str, list[dict[str, str]]] = {}
    for source in raw_sources:
        if not isinstance(source, dict):
            raise TypeError("one or more source records was not an object")
        source_id = str(source.get("group_id", ""))
        if source_id not in allowed or source_id in by_source:
            raise ValueError(
                f"Invalid or duplicate question-match source: {source_id!r}"
            )
        raw_matches = source.get("matches", [])
        if not isinstance(raw_matches, list):
            raise TypeError(f"matches for {source_id!r} was not an array")
        matches = []
        seen: set[str] = set()
        for match in raw_matches:
            if not isinstance(match, dict):
                raise TypeError(f"a match for {source_id!r} was not an object")
            target_id = str(match.get("group_id", ""))
            if target_id not in allowed or target_id == source_id or target_id in seen:
                raise ValueError(
                    f"Invalid question match {source_id!r} -> {target_id!r}"
                )
            seen.add(target_id)
            matches.append(
                {
                    "group_id": target_id,
                    "reason": " ".join(str(match.get("reason", "")).split()),
                }
            )
        if len(matches) > top_k:
            raise ValueError(f"Claude exceeded top_k for {source_id!r}")
        by_source[source_id] = matches
    missing = allowed - set(by_source)
    if missing:
        raise ValueError(f"Claude omitted question-match sources: {sorted(missing)}")
    return by_source


def directional_question_matches(
    groups: list[dict[str, Any]],
    cache_dir: Path,
    *,
    label: str,
    top_k: int,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
) -> list[dict[str, Any]]:
    """Ask Claude for directional conceptual matches and attach lexical scores."""
    if not groups:
        return []
    if len(groups) == 1:
        group = groups[0]
        return [
            {
                "group_id": group["group_id"],
                "overarching_question": group_question(group),
                "matches": [],
            }
        ]

    group_ids = [str(group["group_id"]) for group in groups]
    if len(set(group_ids)) != len(group_ids):
        raise ValueError("Question groups must have unique group ids")
    top_k = max(1, min(top_k, len(groups) - 1))
    question_by_id = {str(group["group_id"]): group_question(group) for group in groups}
    questions = "\n".join(
        f"- {group_id}: {question_by_id[group_id]}" for group_id in group_ids
    )
    prompt = USER_PROMPT_TEMPLATE.format(top_k=top_k, questions=questions)
    prompt_hash = hashlib.sha256(
        f"{model}\n{SYSTEM_PROMPT}\n{prompt}".encode()
    ).hexdigest()
    cache_path = cache_dir / f"{_safe_label(label)}__{prompt_hash[:16]}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))["entries"]

    anthropic = client or Anthropic()
    by_source = None
    last_error = "Claude did not return question matches"
    for attempt in range(3):
        repair = ""
        if attempt:
            repair = (
                "\n\nYour previous tool response was invalid. Return sources as an array "
                "of objects and include every supplied source group exactly once."
            )
        response = anthropic.messages.create(
            model=model,
            max_tokens=min(10_000, max(2_000, len(groups) * 280)),
            system=cached_system(SYSTEM_PROMPT),
            messages=[{"role": "user", "content": prompt + repair}],
            tools=[_tool(group_ids, top_k)],
            tool_choice={"type": "tool", "name": "record_directional_question_matches"},
        )
        log_cache_usage(f"question matches {label} attempt {attempt + 1}", response)
        raw_sources = None
        for block in response.content:
            if (
                block.type == "tool_use"
                and block.name == "record_directional_question_matches"
                and isinstance(block.input, dict)
            ):
                raw_sources = block.input.get("sources")
                break
        try:
            by_source = _validate_sources(raw_sources, group_ids, top_k)
            break
        except (TypeError, ValueError) as exc:
            last_error = str(exc)
            print(
                f"    question matches {label}: invalid tool response on attempt "
                f"{attempt + 1}; retrying ..."
            )
    if by_source is None:
        raise RuntimeError(
            f"Claude did not return valid question matches for {label}: {last_error}"
        )

    entries = []
    for source_id in group_ids:
        entries.append(
            {
                "group_id": source_id,
                "overarching_question": question_by_id[source_id],
                "matches": [
                    {
                        **match,
                        "overarching_question": question_by_id[match["group_id"]],
                        "similarity": round(
                            text_similarity(
                                question_by_id[source_id],
                                question_by_id[match["group_id"]],
                            ),
                            4,
                        ),
                    }
                    for match in by_source[source_id]
                ],
            }
        )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "model": model,
                "prompt_hash": prompt_hash,
                "top_k": top_k,
                "entries": entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return entries


def reciprocal_question_links(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep A-B only when Claude selected both A -> B and B -> A."""
    entry_by_id = {str(entry["group_id"]): entry for entry in entries}
    order = {str(entry["group_id"]): index for index, entry in enumerate(entries)}
    directional: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        source_id = str(entry["group_id"])
        for match in entry.get("matches", []):
            directional[(source_id, str(match["group_id"]))] = match

    links = []
    for (source_id, target_id), forward in directional.items():
        if order.get(source_id, -1) >= order.get(target_id, -1):
            continue
        reverse = directional.get((target_id, source_id))
        if reverse is None:
            continue
        lexical = round(
            text_similarity(
                str(entry_by_id[source_id]["overarching_question"]),
                str(entry_by_id[target_id]["overarching_question"]),
            ),
            4,
        )
        links.append(
            {
                "group_a": source_id,
                "question_a": entry_by_id[source_id]["overarching_question"],
                "group_b": target_id,
                "question_b": entry_by_id[target_id]["overarching_question"],
                "similarity": lexical,
                "lexical_similarity": lexical,
                "claude_reciprocal": True,
                "reason_a_to_b": forward.get("reason", ""),
                "reason_b_to_a": reverse.get("reason", ""),
            }
        )
    return links


def eligible_merge_links(
    reciprocal_links: list[dict[str, Any]], lexical_threshold: float
) -> list[dict[str, Any]]:
    """Apply the deterministic half of the two-gate merge contract."""
    return [
        {
            **link,
            "merge_threshold": lexical_threshold,
            "merged": True,
        }
        for link in reciprocal_links
        if link.get("claude_reciprocal") is True
        and float(link.get("lexical_similarity", link.get("similarity", 0.0)))
        >= lexical_threshold
    ]
