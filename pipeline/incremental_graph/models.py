"""Typed contracts shared by the incremental graph pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


Level = Literal["section", "paragraph"]
StructuralKind = Literal["section", "subsection"]
Classification = Literal[
    "common_structure",
    "alignable_difference",
    "non_alignable_difference",
]


class Paragraph(BaseModel):
    id: str
    label: str = ""
    text: str
    question: str = ""
    ordinal: int = Field(default=1, ge=1)


class Section(BaseModel):
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


class Paper(BaseModel):
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


class PaperManifestEntry(BaseModel):
    paper_id: str
    title: str
    file: Path


class PaperManifest(BaseModel):
    schema_version: int = 1
    papers: list[PaperManifestEntry]

    @model_validator(mode="after")
    def validate_papers(self) -> "PaperManifest":
        ids = [paper.paper_id for paper in self.papers]
        if not ids:
            raise ValueError("The paper manifest must contain at least one paper")
        if len(ids) != len(set(ids)):
            raise ValueError("The paper manifest contains duplicate paper IDs")
        return self


class ModelSettings(BaseModel):
    provider: Literal["anthropic"] = "anthropic"
    name: str = "claude-sonnet-5"
    max_tokens: int = 1024
    temperature: float | None = None


class StageConfig(BaseModel):
    id: str
    handler: str
    prompt: str | None = None
    context: str | None = None
    prompts: dict[str, str] = Field(default_factory=dict)
    contexts: dict[str, str] = Field(default_factory=dict)
    skill: str | None = None


class PipelineConfig(BaseModel):
    schema_version: int = 1
    pipeline_id: str
    prompt_root: Path
    context_root: Path
    skill_root: Path = Path("skills")
    model: ModelSettings = Field(default_factory=ModelSettings)
    stages: list[StageConfig]

    @model_validator(mode="after")
    def validate_stages(self) -> "PipelineConfig":
        ids = [stage.id for stage in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError("Pipeline stage IDs must be unique")
        return self


class JudgmentRequest(BaseModel):
    key: str
    paper_index: int
    stage_id: str
    output_kind: Literal["question", "match"]
    prompt_ref: str
    context_ref: str
    context: dict[str, Any]
    allowed_match_ids: list[str] = Field(default_factory=list)
    skill_ref: str | None = None
    force: bool = False


class JudgmentResult(BaseModel):
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


class MatchDecision(BaseModel):
    focus_id: str
    chosen_id: str | None
    direction: Literal["new_to_group", "group_to_new"]
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
