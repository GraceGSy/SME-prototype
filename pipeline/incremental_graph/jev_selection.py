"""Cached Jev selection, including bounded hierarchical candidate selection."""

from __future__ import annotations

import hashlib
import json
import re
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


def matching_examples(path: Path) -> list[dict]:
    """Reuse the canonical lessons, without Claude's JSON/quotation instructions."""
    examples = []
    for case in re.findall(
        r"### (.*?)(?=\n### |\nFor the actual request,|\Z)",
        path.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    ):
        evidence, output = case.split("\nExpected output:\n", 1)
        result = json.loads(output.strip().removeprefix("```json").removesuffix("```").strip())
        examples.append(
            {
                "case": evidence.strip(),
                "corresponding_candidate": result["target_id"],
                "reason": result["basis"],
            }
        )
    if not examples:
        raise ValueError("No canonical matching examples found")
    return examples


class JevSelector:
    def __init__(self, settings: JevSettings, cache: Path, skill_root: Path, prompt_root: Path):
        self.settings = settings
        self.cache = cache
        self.client = JevClient(settings, REPO_ROOT, cache / "responses")
        self.wording = request_prompts("jev")
        self.evidence_wording = request_prompts("evidence")
        self.instructions = (
            (skill_root / "match-role/references/selection.md").read_text(encoding="utf-8")
            + "\n\n"
            + (prompt_root / "shared/group-role.md").read_text(encoding="utf-8")
            + "\n\n"
            + self.wording["policy_suffix"]
        )
        self.examples = matching_examples(prompt_root / "shared/role-matching-examples.md")

    def build_request(self, context: dict) -> dict:
        """Name candidate records and share repeated passages without truncation."""
        candidates = {candidate_handle(item): item for item in context["candidates"]}
        state = encode_evidence({**context, "candidates": candidates})
        # The shared decoder contract must not tell a Noul to output a candidate ID.
        state["text_reference_contract"] = state["text_reference_contract"].removesuffix(
            self.evidence_wording["candidate_handle_suffix"]
        )
        criteria = {}
        for key, candidate in candidates.items():
            center = candidate.get("paragraph_under_consideration", candidate)
            criteria[key] = {
                "evidence": f"`candidates[{json.dumps(key)}]`",
                "generated_question_metadata": center.get("generated_question_metadata", ""),
                "meaning": self.wording["candidate_meaning"],
            }
        shared = {"policy": self.instructions, "examples": self.examples}
        questions = {}
        choice_policy = shared
        choice_question = self.wording["choice_question"]
        if self.settings.selection_mode == "choice":
            criteria[NO_MATCH] = self.wording["no_match_criterion"]
        else:
            # Noul owns abstention in this mode; Choice only ranks the real options.
            choice_policy = {
                **shared,
                "policy": self.instructions.replace(
                    self.wording["ranking_policy_omission"],
                    "",
                ),
            }
            choice_question = self.wording["ranking_question"]
        # Choice needs at least two options; a sole candidate only needs the Noul.
        if len(criteria) > 1:
            questions["match"] = {
                "type": "choice",
                "instructions": {
                    "question": choice_question,
                    **choice_policy,
                },
                "criteria": criteria,
            }
        if self.settings.selection_mode == "choice_noul":
            questions["has_match"] = {
                "type": "noul",
                "instructions": {
                    "question": self.wording["has_match_question"],
                    **shared,
                },
                "criteria": {
                    "true": self.wording["has_match_true"],
                    "false": self.wording["has_match_false"],
                },
            }
        return {"model": self.settings.model, "state": state, "questions": questions}

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

        def split(indices: list[int]) -> dict:
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
                response = choose(half)
                # Do not discard a half because its existence judgment abstained.
                # The final combined pool receives its own independent Noul.
                probabilities = (
                    response["answers"].get("match", {}).get("probabilities", {ids[half[0]]: 1.0})
                )
                # Compare probabilities only within the same response distribution.
                ranked = sorted(half, key=lambda index: -probabilities.get(ids[index], -1))
                shortlist.extend(index for index in ranked[:5] if ids[index] in probabilities)
            if len(shortlist) >= len(indices):
                raise ValueError(
                    "Jev reranking pool cannot fit the provider's request limits; "
                    "no automatic truncation or fallback is allowed"
                )
            return choose(shortlist)

        def choose(indices: list[int]) -> dict:
            body = self.build_request(
                {**request.context, "candidates": [candidates[index] for index in indices]}
            )
            encoded = encode_request(body)
            limit = 254 if self.settings.selection_mode == "choice" else 255
            if len(indices) > limit or len(encoded) > MAX_REQUEST_BYTES:
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
            return response

        response = choose(list(range(len(ids))))
        answer = response["answers"].get("match")
        target = choice_from_probabilities(answer) if answer else ids[0]
        has_match = response["answers"].get("has_match")
        # Binary maximum-probability decision, not a tuned confidence cutoff.
        # An exactly tied existence judgment abstains.
        if target == NO_MATCH or (has_match is not None and has_match["noul"] <= 0.5):
            target = None
        return {
            "target_id": target,
            "choice": answer,
            "has_match": has_match,
            "calls": calls,
        }
