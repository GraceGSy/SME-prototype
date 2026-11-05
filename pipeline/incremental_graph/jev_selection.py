"""Cached Jev selection, including bounded hierarchical candidate selection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..files import read_json, write_json
from ..prompts import REPO_ROOT, request_prompts
from ..providers.jev import (
    MAX_REQUEST_BYTES,
    NO_MATCH,
    JevClient,
    JevRequestTooLarge,
    JevSettings,
    choice_from_probabilities,
    encode_request,
    validate_response,
)
from .evidence_encoding import encode_evidence
from .match_evidence import candidate_handle
from .models import JudgmentRequest


class JevSelector:
    def __init__(self, settings: JevSettings, cache: Path):
        self.settings = settings
        self.cache = cache
        self.client = JevClient(settings, REPO_ROOT, cache / "responses")
        self.wording = request_prompts("jev")
        self.instructions = self.wording["policy"]

    def build_request(self, context: dict, phase: str = "has_match") -> dict:
        """One question per request; candidate text is stored only in state."""
        candidates = {candidate_handle(item): item for item in context["candidates"]}
        state = encode_evidence({**context, "candidates": candidates}, candidate_handles=False)
        # Keep candidate evidence and question metadata in one place: state.
        if phase == "has_match":
            question = {
                "type": "noul",
                "instructions": {
                    "question": self.wording["has_match_question"],
                    "policy": self.instructions,
                    "example": self.wording["gate_example"],
                },
                "criteria": {
                    "true": self.wording["has_match_true"],
                    "false": self.wording["has_match_false"],
                },
            }
        elif phase == "match" and len(candidates) > 1:
            question = {
                "type": "choice",
                "instructions": {
                    "question": self.wording["ranking_question"],
                    "policy": self.instructions,
                    "example": self.wording["rank_example"],
                },
                "criteria": {
                    key: self.wording["candidate_reference"].format(candidate_id=json.dumps(key))
                    for key in candidates
                },
            }
        else:
            raise ValueError("Ranking requires multiple candidates")
        return {"model": self.settings.model, "state": state, "questions": {phase: question}}

    def select(
        self, request: JudgmentRequest, *, force: bool = False, allow_splitting: bool = True
    ) -> dict:
        candidates = request.context["candidates"]
        ids = request.allowed_match_ids
        if (
            [candidate_handle(candidate) for candidate in candidates] != ids
            or len(set(ids)) != len(ids)
            or NO_MATCH in ids
        ):
            raise ValueError("Jev candidate IDs must be unique and aligned with the evidence")
        if not ids:
            return {"target_id": None, "calls": []}
        calls = []

        def split(indices: list[int]) -> tuple:
            if not allow_splitting:
                raise ValueError(
                    "Frozen-pool comparison cannot split candidates; no text was truncated"
                )
            if len(indices) == 1:
                raise ValueError(
                    "Jev focus plus one candidate exceeds the provider's request limits; "
                    "no source text was truncated. Use smaller prepared units."
                )
            middle = len(indices) // 2
            shortlist = []
            for half in (indices[:middle], indices[middle:]):
                target, ranked_answer, _ = choose(half)
                if target is None:
                    continue
                scores = ranked_answer["probabilities"] if ranked_answer else {target: 1.0}
                ranked = sorted(
                    (i for i in half if ids[i] in scores), key=lambda i: -scores[ids[i]]
                )
                shortlist.extend(ranked[:5])
            if not shortlist:
                return None, None, None
            if len(shortlist) >= len(indices):
                raise ValueError(
                    "Jev reranking pool cannot fit the provider's request limits; "
                    "no automatic truncation or fallback is allowed"
                )
            return choose(shortlist)

        def ask(context: dict, phase: str) -> dict:
            body = self.build_request(context, phase)
            encoded = encode_request(body)
            if len(encoded) > MAX_REQUEST_BYTES:
                raise JevRequestTooLarge("Local request size limit exceeded")
            fingerprint = hashlib.sha256(encoded).hexdigest()
            path = self.cache / f"{fingerprint}.json"
            hit = path.is_file() and not force
            if hit:
                saved = read_json(path)
                if saved["request"] != body:
                    raise ValueError("Jev cached request changed")
                response = validate_response(saved["response"], body)
            else:
                response = self.client.choose(body)
                write_json(path, {"request": body, "response": response})
                self.client.check_reported_usage()
            call = {"fingerprint": fingerprint, "cache_hit": hit, "response": response}
            answer = response["answers"].get("match")
            if answer is not None:
                effective_choice = choice_from_probabilities(answer)
                if effective_choice != answer["choice"]:
                    call["choice_correction"] = {
                        "reported_choice": answer["choice"],
                        "effective_choice": effective_choice,
                        "reason": "highest_returned_probability",
                    }
            calls.append(call)
            return response["answers"][phase]

        def choose(indices: list[int]) -> tuple:
            context = {**request.context, "candidates": [candidates[i] for i in indices]}
            try:
                gate = ask(context, "has_match")
                if gate["noul"] <= 0.5:
                    return None, None, gate
                if len(indices) == 1:
                    return ids[indices[0]], None, gate
                if len(indices) <= 255:
                    ranked = ask(context, "match")
                    return choice_from_probabilities(ranked), ranked, gate
            except JevRequestTooLarge:
                pass
            return split(indices)

        target, answer, has_match = choose(list(range(len(ids))))
        return {
            "target_id": target,
            "choice": answer,
            "has_match": has_match,
            "calls": calls,
        }
