"""The only two LLM-judgment functions in this pipeline. Everything else -- ID
generation, graph mutation, classification -- is deterministic Python (see
input_data.py, graph_ops.py). This is the "necessary fuzzy judgements" half of the
design: does this passage's role match that group's role, and what question describes a
passage or group.

A tiny content-hash cache avoids re-paying for an identical call across re-runs. This is
plain bookkeeping, not the provenance/replay system pipeline 2 has -- there's no event
log, no revisions, no retry command, just "have we already asked exactly this question
of exactly this text before."

`anthropic` is imported lazily, inside Judge.__init__, not at module load time -- same
pattern pipeline 2's own llm.py uses, and for the same reason: this module (and anything
that imports it, like runner.py) stays importable in an environment that doesn't have
the anthropic package installed, as long as nothing actually constructs a real Judge.
Tests use ScriptedJudge instead and never hit this import at all.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

MODEL_DEFAULT = "claude-sonnet-5"

QUESTION_PROMPT = """You will be shown the full text of a {kind}. Write ONE short, open \
question that this {kind} is fundamentally trying to answer. Keep it under 20 words. Do \
not answer the question, just state it. Respond with only the question, no preamble.

Text:
{text}"""

MATCH_PROMPT = """You are matching a {kind} against a list of candidate existing \
question-groups, each identified by an id and its own guiding question. Decide which \
candidate (if any) this {kind} genuinely belongs with -- same underlying question or \
role, not just shared topic or vocabulary. If none of them genuinely fit, say so.

{kind} text:
{focus_text}

Candidates:
{candidates}

Respond with ONLY the chosen candidate's id, or the literal word NONE if none fit."""


def _key(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


class JudgmentCache:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict[str, str] = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, key: str) -> Optional[str]:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


class Judge:
    """Real, API-backed judge. See ScriptedJudge in the tests for a fake used in unit
    tests -- both expose the same generate_question/match_unit interface, and
    runner.py's orchestration code only ever depends on that interface, not this class."""

    def __init__(self, cache_path: Path, model: str = MODEL_DEFAULT):
        from anthropic import Anthropic  # lazy: see module docstring

        self.client = Anthropic()
        self.model = model
        self.cache = JudgmentCache(cache_path)

    def generate_question(self, text: str, kind: str = "passage") -> str:
        key = _key("question", kind, text)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        response = self.client.messages.create(
            model=self.model,
            max_tokens=100,
            temperature=0,
            messages=[{"role": "user", "content": QUESTION_PROMPT.format(kind=kind, text=text)}],
        )
        question = response.content[0].text.strip()
        self.cache.set(key, question)
        return question

    def match_unit(self, focus_text: str, candidates: dict[str, str], kind: str = "passage") -> Optional[str]:
        """candidates: {candidate_id: candidate_question}. Returns the chosen id, or
        None if no candidates were given or the model picked none of them."""
        if not candidates:
            return None
        key = _key("match", kind, focus_text, json.dumps(candidates, sort_keys=True))
        cached = self.cache.get(key)
        if cached is not None:
            return None if cached == "NONE" else cached
        listing = "\n".join(f"- {candidate_id}: {question}" for candidate_id, question in candidates.items())
        response = self.client.messages.create(
            model=self.model,
            max_tokens=50,
            temperature=0,
            messages=[{
                "role": "user",
                "content": MATCH_PROMPT.format(kind=kind, focus_text=focus_text, candidates=listing),
            }],
        )
        answer = response.content[0].text.strip()
        chosen = answer if answer in candidates else None
        self.cache.set(key, chosen or "NONE")
        return chosen
