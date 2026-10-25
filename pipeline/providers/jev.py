"""TypeSafe's Choice transport. No graph rules, Skills, or automatic paid retries."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ..files import write_json
from .registry import load_api_key

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
NO_MATCH = "NO_MATCH"
# TypeSafe's transport limit, not an estimate of its token context window.
MAX_REQUEST_BYTES = 32 * 1024 * 1024


class JevRequestTooLarge(ValueError):
    """The provider's body or context limit requires a smaller candidate pool."""


class JevSettings(BaseModel):
    """Pin the model and bound requests independently of the generative provider."""

    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(default="jev-1.14.0", pattern=r"^jev-\d+\.\d+\.\d+$")
    max_calls: int = Field(default=500, gt=0)
    max_input_tokens: int = Field(default=2_000_000, gt=0)
    timeout_seconds: int = Field(default=120, gt=0)

    def result_settings(self) -> dict:
        """Budgets and timeouts do not change a successful Choice request."""
        return self.model_dump(exclude={"max_calls", "max_input_tokens", "timeout_seconds"})


class ChoiceAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    type: Literal["choice"]
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0, le=1)


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ChoiceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str
    answers: dict[str, ChoiceAnswer]
    usage: Usage


def validate_response(payload: dict, body: dict) -> dict:
    """Require the exact requested options, model, and a valid distribution."""
    response = ChoiceResponse.model_validate(payload)
    if response.model != body["model"] or set(response.answers) != {"match"}:
        raise ValueError("Jev returned a different model or question set")
    answer = response.answers["match"]
    options = set(body["questions"]["match"]["criteria"])
    probabilities = answer.probabilities
    if set(probabilities) != options or answer.choice not in options:
        raise ValueError("Jev returned missing or unknown choices")
    if any(not 0 <= value <= 1 for value in probabilities.values()) or not math.isclose(
        sum(probabilities.values()), 1, abs_tol=1e-5
    ):
        raise ValueError("Jev returned an invalid probability distribution")
    if probabilities[answer.choice] < max(probabilities.values()):
        raise ValueError("Jev choice is not a highest-probability option")
    return response.model_dump()


def encode_request(body: dict) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class JevClient:
    """Keep raw responses before validation; never save the Authorization header."""

    def __init__(self, settings: JevSettings, repo_root: Path, responses: Path):
        self.settings = settings
        self.repo_root = repo_root
        self.responses = responses
        self.calls = 0
        self.input_tokens = 0

    def choose(self, body: dict) -> dict:
        encoded = encode_request(body)
        count = len(body["questions"]["match"]["criteria"])
        if not 2 <= count <= 255:
            raise ValueError("Jev request exceeds the choice limit")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise JevRequestTooLarge("Jev request exceeds TypeSafe's 32 MiB body limit")
        if self.calls >= self.settings.max_calls:
            raise ValueError("Jev call limit reached; inspect usage before retrying")
        if self.input_tokens >= self.settings.max_input_tokens:
            raise ValueError("Jev input-token limit reached; inspect usage before retrying")
        key = load_api_key(self.repo_root, "TYPESAFE_API_KEY")
        request = Request(
            ENDPOINT,
            data=encoded,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        self.calls += 1
        record = {"provider": "jev", "request": body, "call_index": self.calls}
        path = self.responses / f"{uuid4().hex}.json"
        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                text = response.read().decode("utf-8")
        except HTTPError as error:
            text = error.read().decode("utf-8", errors="replace")
            write_json(path, {**record, "http_status": error.code, "response_text": text})
            try:
                payload = json.loads(text)
            except ValueError:
                payload = None
            detail = payload.get("detail") if isinstance(payload, dict) else None
            error_type = detail.get("error_type") if isinstance(detail, dict) else detail
            if error.code == 413 or (error.code == 400 and error_type == "max_tokens_exceeded"):
                raise JevRequestTooLarge(
                    "Jev rejected the request's body or context size; response retained"
                ) from None
            raise RuntimeError(
                f"Jev HTTP {error.code}; check credentials, limits, or service availability. "
                "No automatic retry was made."
            ) from None
        except (URLError, TimeoutError, OSError) as error:
            write_json(path, {**record, "error_type": type(error).__name__})
            raise RuntimeError(
                "Jev connection failed; the request may have been billed. Inspect before retrying."
            ) from None
        write_json(path, {**record, "response_text": text})
        payload = validate_response(json.loads(text), body)
        self.input_tokens += payload["usage"]["input_tokens"]
        if self.input_tokens > self.settings.max_input_tokens:
            raise ValueError("Jev input-token limit exceeded; paid response retained")
        return payload
