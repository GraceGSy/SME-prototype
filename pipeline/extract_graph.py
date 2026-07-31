"""Stage 1: turn raw paper text into a structured PaperGraph via a forced
tool-call to Claude. This is the step Gentner's SME assumes is already done --
alignment needs structured relational representations as input, not prose.
"""
from __future__ import annotations

import os

from anthropic import Anthropic

from cache_utils import cached_system, log_cache_usage
from schema import ENTITY_KINDS, SUGGESTED_PREDICATES, PaperGraph

DEFAULT_MODEL = os.environ.get("SME_EXTRACT_MODEL", "claude-sonnet-5")

# Keep paper text under a rough budget so extraction stays cheap and the model
# doesn't spend its output budget on a paper too long to graph compactly.
MAX_CHARS = 60_000

SYSTEM_PROMPT = """You are extracting a structured relational graph from an academic paper, \
in the style of Gentner's structure-mapping representations: the paper is represented as \
(a) a set of entities (the objects/concepts/artifacts the paper is about) and (b) a set of \
propositions -- labeled relations connecting either entities directly (first-order relations) \
or connecting OTHER propositions (higher-order relations, e.g. one claim causing, motivating, \
or enabling another).

Favor extracting connected relational structure over isolated facts: a chain like "the problem \
motivates the method, the method produces the result, the result supports the claim" is far more \
useful than four disconnected attribute statements. Prefer higher-order propositions (relations \
between relations) whenever the paper supports them -- this is what lets later comparisons find \
real structural correspondences between papers instead of shallow keyword overlap.

Keep the graph compact: roughly 8-20 entities and 10-30 propositions is typical for one paper. \
Every proposition must cite a short piece of evidence (a quote or tight paraphrase, <25 words) \
from the text it is grounded in."""

USER_PROMPT_TEMPLATE = """Paper id: {paper_id}

Paper text:
\"\"\"
{text}
\"\"\"

Extract this paper's structural graph using the record_paper_graph tool."""


def _build_tool() -> dict:
    # Written by hand (not PaperGraph.model_json_schema()) so the schema is flat --
    # no $defs/$ref indirection. Nested $ref schemas occasionally get echoed back
    # verbatim by the model (e.g. a stray "$PARAMETER_NAME" wrapper key), which a
    # flat schema avoids.
    return {
        "name": "record_paper_graph",
        "description": "Record the extracted entity/proposition graph for one paper.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
                "title": {"type": "string"},
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "short stable id, e.g. 'e1'"},
                            "name": {"type": "string", "description": "concise name of the object/concept"},
                            "kind": {
                                "type": "string",
                                "description": f"category of entity, e.g. one of {ENTITY_KINDS} (or a close variant)",
                            },
                        },
                        "required": ["id", "name", "kind"],
                    },
                },
                "propositions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "short stable id, e.g. 'p1'"},
                            "predicate": {
                                "type": "string",
                                "description": (
                                    f"the relation name connecting the args, e.g. one of {SUGGESTED_PREDICATES} "
                                    "(or a close variant)"
                                ),
                            },
                            "args": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "ordered list of ids this predicate connects. Each id must refer to an "
                                    "entity id or another proposition id -- referencing a proposition makes "
                                    "this a higher-order relation."
                                ),
                            },
                            "evidence": {
                                "type": "string",
                                "description": "a short quote or tight paraphrase (<25 words) from the paper supporting this",
                            },
                        },
                        "required": ["id", "predicate", "args", "evidence"],
                    },
                },
            },
            "required": ["paper_id", "title", "entities", "propositions"],
        },
    }


def extract_graph(paper_id: str, title_hint: str, text: str, model: str = DEFAULT_MODEL) -> PaperGraph:
    client = Anthropic()
    truncated = text[:MAX_CHARS]

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=cached_system(SYSTEM_PROMPT),
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(paper_id=paper_id, text=truncated),
            }
        ],
        tools=[_build_tool()],
        tool_choice={"type": "tool", "name": "record_paper_graph"},
    )
    log_cache_usage(paper_id, response)

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_paper_graph":
            data = block.input
            if set(data.keys()) - {"paper_id", "title", "entities", "propositions"} and len(data) == 1:
                # Defensive unwrap in case the model still nests everything under one stray key.
                data = next(iter(data.values()))
            return PaperGraph.model_validate(data)

    raise RuntimeError(f"Model did not call record_paper_graph for paper_id={paper_id!r}")
