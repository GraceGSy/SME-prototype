"""TypeSafe's Choice/Noul transport; no graph rules or automatic paid retries."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Annotated, Literal
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
# https://docs.typesafe.ai/models#long-context
LONG_CONTEXT_HEADER = "TypeSafe-Danger-Zone-Long-Context"
# Default Jev 1.14 window per question (state plus one question).
DEFAULT_QUESTION_TOKENS = 32_768
# Fitted Nov 18, 2026 on 521 HCI requests: reported tokens = 0.2005 * JSON characters + 95,
# residuals within -517..+647. The margin keeps a request near the limit on long context.
TOKENS_PER_CHAR = 0.2005
ESTIMATE_MARGIN_TOKENS = 700


def estimated_tokens(body: dict) -> int:
    """Approximate Jev's input-token count from the request's JSON length."""
    return round(TOKENS_PER_CHAR * len(encode_request(body).decode("utf-8")) + 95)


def needs_long_context(body: dict) -> bool:
    return estimated_tokens(body) + ESTIMATE_MARGIN_TOKENS > DEFAULT_QUESTION_TOKENS


class JevRequestTooLarge(ValueError):
    """The provider's body or context limit requires a smaller candidate pool."""


class JevSettings(BaseModel):
    """Pin the model and bound requests independently of the generative provider."""

    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(default="jev-1.14.0", pattern=r"^jev-\d+\.\d+\.\d+$")
    max_calls: int | None = Field(default=None, gt=0)
    max_input_tokens: int | None = Field(default=None, gt=0)
    timeout_seconds: int = Field(default=120, gt=0)
    # Resend a size-rejected request once with TypeSafe's long-context header (262k tokens
    # per question instead of 32k), so questions keep complete papers instead of shrinking.
    # The docs call it slower and less accurate, so requests that fit the default window
    # never use it. Off means an oversized question stops the run.
    long_context_retry: bool = True

    def result_settings(self) -> dict:
        """Budgets and timeouts do not change a successful judgment."""
        settings = self.model_dump(exclude={"max_calls", "max_input_tokens", "timeout_seconds"})
        if not settings["long_context_retry"]:
            settings.pop("long_context_retry")  # Keep saved runs' policy hashes unchanged.
        return settings


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


class NoulAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    type: Literal["noul"]
    noul: float = Field(ge=0, le=1)


class JevResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str
    answers: dict[str, Annotated[ChoiceAnswer | NoulAnswer, Field(discriminator="type")]]
    usage: Usage


def validate_response(payload: dict, body: dict) -> dict:
    """Require the exact requested options, model, and a valid distribution."""
    response = JevResponse.model_validate(payload)
    if response.model != body["model"] or set(response.answers) != set(body["questions"]):
        raise ValueError("Jev returned a different model or question set")
    for name, answer in response.answers.items():
        question = body["questions"][name]
        if answer.type != question.get("type", "choice"):
            raise ValueError("Jev returned a different question type")
        if isinstance(answer, NoulAnswer):
            continue
        options = set(question["criteria"])
        probabilities = answer.probabilities
        if set(probabilities) != options or answer.choice not in options:
            raise ValueError("Jev returned missing or unknown choices")
        # Returned probabilities are rounded; preserve them without renormalizing.
        total = math.fsum(probabilities.values())
        if any(not 0 <= value <= 1 for value in probabilities.values()) or not 0.98 < total <= 1.02:
            raise ValueError(f"Jev returned an invalid probability distribution (sum={total})")
    return response.model_dump()


def choice_from_probabilities(answer: dict) -> str:
    """Use validated probabilities, retaining the reported choice only if tied for first."""
    return min(
        answer["probabilities"],
        key=lambda option: (
            -answer["probabilities"][option],
            option != answer["choice"],
            option,
        ),
    )


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

    def choose(self, body: dict, *, long_context: bool = False) -> dict:
        encoded = encode_request(body)
        for question in body["questions"].values():
            if question.get("type", "choice") == "choice":
                if not 2 <= len(question["criteria"]) <= 255:
                    raise ValueError("Jev request exceeds the choice limit")
            elif question["type"] != "noul":
                raise ValueError("Only Choice and Noul questions are supported")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise JevRequestTooLarge("Jev request exceeds TypeSafe's 32 MiB body limit")
        if self.settings.max_calls is not None and self.calls >= self.settings.max_calls:
            raise ValueError("Jev call limit reached; inspect usage before retrying")
        if (
            self.settings.max_input_tokens is not None
            and self.input_tokens >= self.settings.max_input_tokens
        ):
            raise ValueError("Jev input-token limit reached; inspect usage before retrying")
        key = load_api_key(self.repo_root, "TYPESAFE_API_KEY")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if long_context:
            headers[LONG_CONTEXT_HEADER] = "true"
        request = Request(ENDPOINT, data=encoded, headers=headers, method="POST")
        self.calls += 1
        record = {"provider": "jev", "request": body, "call_index": self.calls}
        if long_context:
            record["long_context"] = True
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
        return payload

    def check_reported_usage(self) -> None:
        """Stop on an overshoot after the selector caches the valid paid response."""
        if (
            self.settings.max_input_tokens is not None
            and self.input_tokens > self.settings.max_input_tokens
        ):
            raise ValueError("Jev input-token limit exceeded; paid response retained")
