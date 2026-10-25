"""Cached Jev selection, including bounded hierarchical candidate selection."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..files import read_json, write_json
from ..providers.jev import (
    MAX_REQUEST_BYTES,
    NO_MATCH,
    JevClient,
    JevRequestTooLarge,
    JevSettings,
    encode_request,
    validate_response,
)
from .evidence_encoding import encode_evidence
from .match_evidence import candidate_handle
from .models import JudgmentRequest


class JevSelector:
    def __init__(self, settings: JevSettings, cache: Path, skill_root: Path, prompt_root: Path):
        self.settings = settings
        self.cache = cache
        self.client = JevClient(settings, skill_root.parent, cache / "responses")
        self.instructions = (
            (skill_root / "match-role/references/selection.md").read_text(encoding="utf-8")
            + "\n\n"
            + (prompt_root / "shared/group-role.md").read_text(encoding="utf-8")
            + "\n\n"
            + (prompt_root / "shared/role-matching-examples.md").read_text(encoding="utf-8")
            + "\n\nChoose one candidate from state.candidates for state.focus, or NO_MATCH. "
            "Each criterion names its candidate's index. IDs are opaque output handles. "
            "Judge this direction independently; no reverse votes are supplied. "
            "NO_MATCH means no defensible role correspondence in this pool. "
            "The examples use a generative output format; here return a Choice only, "
            "with NO_MATCH equivalent to their null selections. "
            "Do not use the order of options as evidence."
        )

    def select(self, request: JudgmentRequest, *, force: bool = False) -> dict:
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

        def body_for(indices: list[int]) -> dict:
            state = {**request.context, "candidates": [candidates[index] for index in indices]}
            return {
                "model": self.settings.model,
                "state": encode_evidence(state),
                "questions": {
                    "match": {
                        "type": "choice",
                        "instructions": self.instructions,
                        "criteria": {
                            **{
                                ids[
                                    index
                                ]: f"The role correspondence in state.candidates[{position}]"
                                for position, index in enumerate(indices)
                            },
                            NO_MATCH: "None of these candidates supports a defensible shared role",
                        },
                    }
                },
            }

        def split(indices: list[int]) -> dict:
            if len(indices) == 1:
                raise ValueError(
                    "Jev focus plus one candidate exceeds the provider's request limits; "
                    "no source text was truncated. Use smaller prepared units."
                )
            middle = len(indices) // 2
            shortlist = []
            for half in (indices[:middle], indices[middle:]):
                answer = choose(half)
                # Compare probabilities only within the same response distribution.
                ranked = sorted(
                    half, key=lambda index: -answer["probabilities"].get(ids[index], -1)
                )
                shortlist.extend(
                    index for index in ranked[:5] if ids[index] in answer["probabilities"]
                )
            if len(shortlist) >= len(indices):
                raise ValueError(
                    "Jev reranking pool cannot fit the provider's request limits; "
                    "no automatic truncation or fallback is allowed"
                )
            return choose(shortlist)

        def choose(indices: list[int]) -> dict:
            body = body_for(indices)
            encoded = encode_request(body)
            if len(indices) > 254 or len(encoded) > MAX_REQUEST_BYTES:
                return split(indices)
            fingerprint = hashlib.sha256(encoded).hexdigest()
            path = self.cache / f"{fingerprint}.json"
            hit = path.is_file() and not force
            if hit:
                saved = read_json(path)
                if saved["request"] != body:
                    raise ValueError("Jev cached request changed")
                response = validate_response(saved["response"], body)
            else:
                try:
                    response = self.client.choose(body)
                except JevRequestTooLarge:
                    return split(indices)
                write_json(path, {"request": body, "response": response})
            calls.append({"fingerprint": fingerprint, "cache_hit": hit, "response": response})
            return response["answers"]["match"]

        answer = choose(list(range(len(ids))))
        return {
            "target_id": None if answer["choice"] == NO_MATCH else answer["choice"],
            "choice": answer,
            "calls": calls,
        }
