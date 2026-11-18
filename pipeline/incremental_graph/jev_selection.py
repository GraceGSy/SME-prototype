"""Cached Jev selection, including bounded hierarchical candidate selection."""

from __future__ import annotations

import hashlib
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
    needs_long_context,
    validate_response,
)
from .evidence_encoding import paragraph_options
from .jev_outline import focus_outline
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
        return self._request_and_labels(context, phase)[0]

    def _request_and_labels(self, context, phase):
        state, labels = focus_outline(context)
        options = paragraph_options(context)
        wording = self.wording[options[0]] if options else None
        if phase == "has_match":
            kind = "noul"
            criteria = {
                "true": self.wording["has_match_true"],
                "false": self.wording["has_match_false"],
            }
            question = self.wording["has_match_question"]
        elif phase == "match" and len(labels) > 1:
            kind = "choice"
            criteria = {v: v for v in labels.values()}
            question = self.wording["ranking_question"]
        else:
            raise ValueError("Ranking requires multiple candidates")
        instructions = {
            "question": wording[phase] if wording else question,
            "policy": (wording["guide"] if wording else self.instructions)
            + " "
            + self.wording["outline_rule"],
        }
        if not wording:
            instructions["example"] = self.wording[
                "gate_example" if phase == "has_match" else "rank_example"
            ]
        return {
            "model": self.settings.model,
            "state": state,
            "questions": {
                phase: {"type": kind, "instructions": instructions, "criteria": criteria}
            },
        }, labels

    def select(
        self,
        request: JudgmentRequest,
        *,
        force: bool = False,
        allow_splitting: bool = True,
        rank_only: bool = False,
    ) -> dict:
        """Gate, then rank. ``rank_only`` chooses among options that each passed a gate."""
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
            body, labels = self._request_and_labels(context, phase)
            encoded = encode_request(body)
            if len(encoded) > MAX_REQUEST_BYTES:
                raise JevRequestTooLarge("Local request size limit exceeded")
            fingerprint = hashlib.sha256(encoded).hexdigest()

            def rejected(marker: Path) -> bool:
                # A size rejection is deterministic for an exact body; replay it without a call.
                if not marker.is_file() or force:
                    return False
                if read_json(marker)["request"] != body:
                    raise ValueError("Jev cached request changed")
                return True

            def answer(path: Path, too_large: Path, long_context: bool) -> tuple[dict, bool]:
                if path.is_file() and not force:
                    saved = read_json(path)
                    if saved["request"] != body:
                        raise ValueError("Jev cached request changed")
                    return validate_response(saved["response"], body), True
                try:
                    response = (
                        self.client.choose(body, long_context=True)
                        if long_context
                        else self.client.choose(body)
                    )
                except JevRequestTooLarge:
                    write_json(too_large, {"request": body})
                    raise
                write_json(path, {"request": body, "response": response})
                self.client.check_reported_usage()
                return response, False

            # Long-context answers live apart: the same body can answer differently with it.
            default = (self.cache / f"{fingerprint}.json", self.cache / "too-large" / f"{fingerprint}.json")
            long = (
                self.cache / "long-context" / f"{fingerprint}.json",
                self.cache / "too-large" / "long-context" / f"{fingerprint}.json",
            )
            long_context = rejected(default[1])
            if self.settings.long_context_retry and not long_context:
                # Requests predicted to overflow skip the default attempt, unless one was
                # already answered without the header.
                long_context = needs_long_context(body) and not (
                    default[0].is_file() and not force
                )
            if long_context and not self.settings.long_context_retry:
                raise JevRequestTooLarge("Jev rejected this exact request for size earlier")
            if not long_context:
                try:
                    response, hit = answer(*default, long_context=False)
                except JevRequestTooLarge:
                    if not self.settings.long_context_retry:
                        raise
                    long_context = True
            if long_context:
                if rejected(long[1]):
                    raise JevRequestTooLarge(
                        "Jev rejected this exact request for size earlier, even with long context"
                    )
                response, hit = answer(*long, long_context=True)
            call = {"fingerprint": fingerprint, "cache_hit": hit, "response": response}
            if long_context:
                call["long_context"] = True
            call["option_ids"] = {label: key for key, label in labels.items()}
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
            if answer is not None:
                ids_by_label = call["option_ids"]
                return {
                    **answer,
                    "choice": ids_by_label[choice_from_probabilities(answer)],
                    "probabilities": {
                        ids_by_label[k]: v for k, v in answer["probabilities"].items()
                    },
                }
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
                if "sections" in context.get("outline", {}) or "paragraphs" in context.get(
                    "outline", {}
                ):
                    raise JevRequestTooLarge(
                        "Jev could not fit the complete participating papers. No source text "
                        "was truncated and no smaller pool was retried."
                    )
            return split(indices)

        if rank_only:
            if len(ids) < 2:
                raise ValueError("Ranking requires multiple candidates")
            ranked = ask(request.context, "match")
            return {
                "target_id": choice_from_probabilities(ranked),
                "choice": ranked,
                "has_match": None,
                "calls": calls,
            }
        target, answer, has_match = choose(list(range(len(ids))))
        return {
            "target_id": target,
            "choice": answer,
            "has_match": has_match,
            "calls": calls,
        }
