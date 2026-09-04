"""Append-only provenance and graph-event recording for one pipeline revision."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import JudgmentRequest, JudgmentResult


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


class RevisionJournal:
    """Record enough evidence to inspect, replay, and retry every pipeline stage."""

    def __init__(self, revision_dir: Path):
        self.revision_dir = revision_dir
        self.events: list[dict[str, Any]] = []
        self.attempt_count = 0
        self.attempt_path = revision_dir / "provenance" / "attempts.jsonl"
        self.event_path = revision_dir / "provenance" / "events.jsonl"
        self.attempt_path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, action: str, *, paper_index: int, **payload: Any) -> dict[str, Any]:
        event = {
            "sequence": len(self.events) + 1,
            "event_id": f"event-{len(self.events) + 1:06d}",
            "paper_index": paper_index,
            "action": action,
            **payload,
        }
        self.events.append(event)
        self._append(self.event_path, event)
        return event

    def attempt(self, request: JudgmentRequest, result: JudgmentResult) -> str:
        self.attempt_count += 1
        attempt_id = f"attempt-{self.attempt_count:06d}"
        record = {
            "attempt_id": attempt_id,
            "request_key": request.key,
            "paper_index": request.paper_index,
            "stage_id": request.stage_id,
            "output_kind": request.output_kind,
            "prompt_ref": request.prompt_ref,
            "context_ref": request.context_ref,
            "skill_ref": request.skill_ref,
            "candidate_ids": request.allowed_match_ids,
            "expected_question_ids": request.expected_question_ids,
            "expected_match_source_ids": request.expected_match_source_ids,
            "max_tokens": request.max_tokens,
            "max_input_tokens": request.max_input_tokens,
            "fingerprint": result.fingerprint,
            "prompt_hash": result.prompt_hash,
            "context_hash": result.context_hash,
            "schema_hash": result.schema_hash,
            "model": result.model,
            "cache_hit": result.cache_hit,
            "rendered_system": result.rendered_system,
            "rendered_user": result.rendered_user,
            "normalized": result.normalized,
            "raw_response": result.raw_response,
        }
        self._append(self.attempt_path, record)
        return attempt_id

    def stage(self, paper_index: int, stage_id: str, value: Any) -> None:
        safe_id = stage_id.replace("/", "-").replace("\\", "-")
        write_json(self.revision_dir / "stages" / f"{paper_index:04d}-{safe_id}.json", value)

    def finalize(self) -> None:
        write_json(self.revision_dir / "events.json", self.events)

    @staticmethod
    def _append(path: Path, value: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
