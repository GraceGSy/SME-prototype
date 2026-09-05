"""Typed contracts shared by the incremental graph pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


Level = Literal["section", "paragraph"]
StructuralKind = Literal["section", "subsection"]
Granularity = Literal["section", "subsection", "paragraph"]
Phase = Literal["structural", "rerepresentation", "paragraph"]
MatchDirection = Literal["new_to_group", "group_to_new", "singleton_to_group"]


class StrictModel(BaseModel):
    """Reject unknown fields and coercion at application boundaries."""

    model_config = ConfigDict(extra="forbid", strict=True)


def _schema_version(value: Any) -> int:
    if type(value) is not int or value != 1:
        raise ValueError("Only integer schema_version 1 is supported")
    return value


SchemaVersion = Annotated[int, BeforeValidator(_schema_version)]
WirePath = Annotated[Path, BeforeValidator(lambda value: Path(value) if isinstance(value, str) else value)]


class Paragraph(StrictModel):
    id: str
    label: str = ""
    text: str
    question: str = ""
    ordinal: int = Field(default=1, ge=1)


class Section(StrictModel):
    id: str
    label: str = ""
    text: str
    paragraphs: list[Paragraph] = Field(default_factory=list)
    question: str = ""
    ordinal: int = Field(default=1, ge=1)
    kind: StructuralKind = "section"
    parent_id: str | None = None
    family_id: str = ""

    @model_validator(mode="after")
    def default_family(self) -> "Section":
        if not self.family_id:
            self.family_id = self.parent_id or self.id
        return self


class Paper(StrictModel):
    paper_id: str
    title: str
    sections: list[Section]

    @model_validator(mode="after")
    def validate_unit_ids(self) -> "Paper":
        section_ids = [section.id for section in self.sections]
        paragraph_ids = [paragraph.id for section in self.sections for paragraph in section.paragraphs]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError(f"Paper {self.paper_id} has duplicate section IDs")
        if len(paragraph_ids) != len(set(paragraph_ids)):
            raise ValueError(f"Paper {self.paper_id} has duplicate paragraph IDs")
        known_sections = set(section_ids)
        for section in self.sections:
            if section.parent_id and section.parent_id not in known_sections:
                raise ValueError(f"Paper {self.paper_id} has unknown parent section {section.parent_id}")
            if section.kind == "section" and section.parent_id:
                raise ValueError(f"Top-level section {section.id} cannot have a parent")
            if section.kind == "subsection" and not section.parent_id:
                raise ValueError(f"Subsection {section.id} must have a parent")
        return self


class PaperManifestEntry(StrictModel):
    paper_id: str
    title: str
    file: WirePath


class PaperManifest(StrictModel):
    schema_version: SchemaVersion = 1
    max_granularity: Granularity = "section"
    papers: list[PaperManifestEntry]

    @model_validator(mode="after")
    def validate_papers(self) -> "PaperManifest":
        ids = [paper.paper_id for paper in self.papers]
        if not ids:
            raise ValueError("The paper manifest must contain at least one paper")
        if len(ids) != len(set(ids)):
            raise ValueError("The paper manifest contains duplicate paper IDs")
        return self


class ModelSettings(StrictModel):
    provider: Literal["anthropic"] = "anthropic"
    name: str = "claude-sonnet-5"
    max_tokens: int = Field(default=1024, gt=0)
    effort: Literal["low", "medium", "high"] = "low"
    thinking: Literal["disabled", "adaptive"] = "disabled"
    max_input_tokens: int = Field(default=200_000, gt=0)
    max_prompt_characters: int = Field(default=500_000, gt=0)
    context_management_trigger_tokens: int = Field(default=50_000, gt=0)
    max_api_responses_per_process: int = Field(default=200, gt=0)
    max_session_input_tokens: int = Field(default=2_000_000, gt=0)
    max_session_output_tokens: int = Field(default=100_000, gt=0)
    temperature: float | None = None


class StageConfig(StrictModel):
    id: str
    handler: str
    phase: Phase
    prompt: str | None = None
    context: str | None = None
    prompts: dict[str, str] = Field(default_factory=dict)
    contexts: dict[str, str] = Field(default_factory=dict)
    skill: str | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    max_input_tokens: int | None = Field(default=None, gt=0)


class PipelineConfig(StrictModel):
    schema_version: SchemaVersion = 1
    pipeline_id: str
    prompt_root: WirePath
    context_root: WirePath
    skill_root: WirePath = Path("skills")
    model: ModelSettings = Field(default_factory=ModelSettings)
    stages: list[StageConfig]

    @model_validator(mode="after")
    def validate_stages(self) -> "PipelineConfig":
        ids = [stage.id for stage in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError("Pipeline stage IDs must be unique")
        return self


class JudgmentRequest(StrictModel):
    key: str
    paper_index: int
    stage_id: str
    output_kind: Literal["question", "match", "match_batch"]
    prompt_ref: str
    context_ref: str
    context: dict[str, Any]
    allowed_match_ids: list[str] = Field(default_factory=list)
    expected_match_source_ids: list[str] = Field(default_factory=list)
    skill_ref: str | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    max_input_tokens: int | None = Field(default=None, gt=0)
    force: bool = False


class JudgmentResult(StrictModel):
    fingerprint: str
    normalized: dict[str, Any]
    raw_response: dict[str, Any]
    rendered_system: str
    rendered_user: str
    prompt_hash: str
    context_hash: str
    schema_hash: str
    model: dict[str, Any]
    cache_hit: bool = False


class MatchDecision(StrictModel):
    source_id: str
    target_id: str | None
    direction: MatchDirection
    attempt_id: str


@dataclass
class MatchBatch:
    existing_group_ids: list[str]
    new_unit_ids: list[str]
    forward: dict[str, MatchDecision] = field(default_factory=dict)
    reverse: dict[str, MatchDecision] = field(default_factory=dict)


@dataclass
class InsertionState:
    paper: Paper
    paper_index: int
    stage_results: dict[str, Any] = field(default_factory=dict)
    section_matches: MatchBatch | None = None
    section_assignments: dict[str, str] = field(default_factory=dict)
    paragraph_matches: dict[str, MatchBatch] = field(default_factory=dict)
    paragraph_assignments: dict[str, str] = field(default_factory=dict)
