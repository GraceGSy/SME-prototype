"""A much coarser alternative representation to schema.py's Entity/Proposition
graph: one paper is just its ordered list of units at some granularity, each
described by a free-text tag (what question it answers / what role it plays)
rather than a fixed category. No relational structure within a paper at all --
the only thing stage 2 (match_sections.py) has to work with is the tag (and,
now, the unit's own text).

`Section` doubles as the generic "tagged unit" type at both granularities
(sections, paragraphs) -- paragraphs just leave `title` empty, since only a
section has its own heading text."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# Discourse relations: describe how a paragraph relates to its immediate
# neighbor, not what role it plays in the paper. The same vocabulary is used for
# both directions (relation-to-previous and relation-to-next) since most of these
# relations are meaningful either way (e.g. "elaboration" can describe how a unit
# builds on what came before, or how the *next* unit will build on this one).
DISCOURSE_TAGS = [
    "elaboration", "example", "contrast", "cause", "motivation", "restatement",
    "generalization", "summary", "comparison", "continuation", "qualification",
    "background", "sequence",
]

GRANULARITIES = ["sections", "paragraphs"]


class Section(BaseModel):
    id: str = Field(description="short stable id, e.g. 's1'")
    title: str = Field(default="", description="the section's own heading text as it appears in the paper, e.g. '4. Evaluation' (empty for paragraph units)")
    tag: str = Field(description="a short, complete question capturing what question about the research this unit answers")
    text: str = Field(default="", description="the unit's own raw text, sliced locally from the extracted PDF text (not model-generated)")
    parent_section_id: str = Field(default="", description="paragraph only: stable id of the source section containing this paragraph")
    prev_relation: str = Field(default="", description=f"paragraph only: this unit's discourse relation to the PREVIOUS unit, e.g. one of {DISCOURSE_TAGS}; empty if it's the first unit in its section")
    next_relation: str = Field(default="", description=f"paragraph only: this unit's discourse relation to the FOLLOWING unit, e.g. one of {DISCOURSE_TAGS}; empty if it's the last unit in its section")

    @field_validator("tag")
    @classmethod
    def tag_must_be_a_question(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized.endswith("?"):
            raise ValueError("unit tags must be complete questions ending in '?'")
        return normalized


class SectionedPaper(BaseModel):
    paper_id: str
    title: str
    sections: list[Section]
    paragraphs: list[Section] = Field(default_factory=list)
