"""Deterministic harness for configurable, non-deterministic Claude Skill calls."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..incremental_graph.skill_api import ClaudeSkills, RunResult, SkillRef


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("pipeline.yaml")
FLAT_QUESTION = "question_this_section_answers"
NESTED_QUESTION = "question_this_text_answers"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def strip_questions(value: Any) -> Any:
    """Remove generated question metadata without changing document identity/content."""
    if isinstance(value, dict):
        return {
            key: strip_questions(child)
            for key, child in value.items()
            if not key.startswith("question_")
        }
    if isinstance(value, list):
        return [strip_questions(child) for child in value]
    return value


def section_paragraphs(section: dict[str, Any]) -> list[dict[str, Any]]:
    paragraphs = [copy.deepcopy(item) for item in section.get("paragraphs", [])]
    for subsection in section.get("subsections", []):
        paragraphs.extend(copy.deepcopy(item) for item in subsection.get("paragraphs", []))
    return [
        {"paragraph_number": index, "text": paragraph["text"]}
        for index, paragraph in enumerate(paragraphs)
    ]


def flatten_document(document: list[dict[str, Any]], *, with_questions: bool) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for section in document:
        entry = {
            "section_name": section["section_name"],
            "section_number": section.get("section_number"),
            "paragraphs": section_paragraphs(section),
        }
        if with_questions:
            entry[FLAT_QUESTION] = section.get(NESTED_QUESTION)
        flat.append(entry)
    return flat


def _validate_unit(unit: dict[str, Any], label: str) -> None:
    if not isinstance(unit.get("section_name"), str) or not unit["section_name"].strip():
        raise ValueError(f"{label} needs a non-empty section_name")
    if unit.get("section_number") is not None and not isinstance(unit["section_number"], str):
        raise ValueError(f"{label} section_number must be a string or null")
    paragraphs = unit.get("paragraphs")
    if not isinstance(paragraphs, list):
        raise ValueError(f"{label} paragraphs must be an array")
    for index, paragraph in enumerate(paragraphs):
        if paragraph.get("paragraph_number") != index:
            raise ValueError(f"{label} paragraph numbers must be zero-indexed and contiguous")
        if not isinstance(paragraph.get("text"), str) or not paragraph["text"].strip():
            raise ValueError(f"{label} paragraph {index} needs non-empty text")


def validate_document(document: Any) -> None:
    if not isinstance(document, list) or not document:
        raise ValueError("A document must be a non-empty JSON array")
    for section_index, section in enumerate(document):
        _validate_unit(section, f"section {section_index}")
        if not isinstance(section.get("subsections"), list):
            raise ValueError(f"section {section_index} subsections must be an array")
        for subsection_index, subsection in enumerate(section["subsections"]):
            _validate_unit(subsection, f"section {section_index} subsection {subsection_index}")


def validate_questions(document: list[dict[str, Any]]) -> None:
    validate_document(document)
    for section in document:
        units = [(section, section_paragraphs(section)), *[
            (subsection, subsection["paragraphs"])
            for subsection in section["subsections"]
        ]]
        for unit, paragraphs in units:
            if NESTED_QUESTION not in unit:
                raise ValueError(f"Missing question on {unit['section_name']}")
            question = unit[NESTED_QUESTION]
            if paragraphs and (not isinstance(question, str) or not question.strip()):
                raise ValueError(f"Non-empty unit {unit['section_name']} needs a question")
            if not paragraphs and question is not None:
                raise ValueError(f"Empty unit {unit['section_name']} must have a null question")


def validate_story_shape(document: list[dict[str, Any]], config: dict[str, Any]) -> None:
    expected_sections = config.get("expected_sections")
    if expected_sections is not None and len(document) != expected_sections:
        raise ValueError(f"Expected {expected_sections} sections, received {len(document)}")
    scene_names = [
        subsection["section_name"]
        for section in document
        for subsection in section["subsections"]
    ]
    expected_scenes = config.get("expected_scenes")
    if expected_scenes is not None and len(scene_names) != expected_scenes:
        raise ValueError(f"Expected {expected_scenes} scenes, received {len(scene_names)}")
    expected_names = [f"Scene {index}" for index in range(1, len(scene_names) + 1)]
    if scene_names != expected_names:
        raise ValueError("Scenes must be numbered once in document order")


def _question_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {FLAT_QUESTION: {"type": ["string", "null"]}},
        "required": [FLAT_QUESTION],
        "additionalProperties": False,
    }


def _enum(values: Iterable[Any]) -> dict[str, Any]:
    return {"enum": sorted(set(values), key=lambda value: (value is not None, str(value)))}


def _flat_entry_schema(
    source: set[tuple[Any, ...]], target: set[tuple[Any, ...]]
) -> dict[str, Any]:
    properties = {
        "paper1_section_name": _enum(candidate[0] for candidate in source),
        "paper1_section_number": _enum(candidate[1] for candidate in source),
        "paper2_section_name": _enum([None, *[candidate[0] for candidate in target]]),
        "paper2_section_number": _enum([None, *[candidate[1] for candidate in target]]),
        "basis": {"type": "string"},
        "question_the_sections_both_answer": {"type": ["string", "null"]},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _nested_entry_schema(
    source: set[tuple[Any, ...]], target: set[tuple[Any, ...]]
) -> dict[str, Any]:
    properties = {
        "paper1_section_name": _enum(candidate[0] for candidate in source),
        "paper1_section_number": _enum(candidate[1] for candidate in source),
        "paper1_subsection_name": _enum(candidate[2] for candidate in source),
        "paper1_subsection_number": _enum(candidate[3] for candidate in source),
        "paper2_section_name": _enum([None, *[candidate[0] for candidate in target]]),
        "paper2_section_number": _enum([None, *[candidate[1] for candidate in target]]),
        "paper2_subsection_name": _enum([None, *[candidate[2] for candidate in target]]),
        "paper2_subsection_number": _enum([None, *[candidate[3] for candidate in target]]),
        "basis": {"type": "string"},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _match_schema(
    view: str,
    source: set[tuple[Any, ...]],
    target: set[tuple[Any, ...]],
) -> dict[str, Any]:
    entry = (
        _flat_entry_schema(source, target)
        if view == "sections"
        else _nested_entry_schema(source, target)
    )
    return {
        "type": "object",
        "properties": {"matches": {"type": "array", "items": entry}},
        "required": ["matches"],
        "additionalProperties": False,
    }


def _flat_candidates(document: list[dict[str, Any]]) -> set[tuple[Any, ...]]:
    return {(section["section_name"], section.get("section_number")) for section in document}


def _nested_candidates(document: list[dict[str, Any]]) -> set[tuple[Any, ...]]:
    candidates: set[tuple[Any, ...]] = set()
    for section in document:
        parent = (section["section_name"], section.get("section_number"))
        candidates.add((*parent, None, None))
        candidates.update(
            (*parent, subsection["section_name"], subsection.get("section_number"))
            for subsection in section["subsections"]
        )
    return candidates


def matching_candidates(document: list[dict[str, Any]], view: str) -> list[dict[str, Any]]:
    if view == "sections":
        return copy.deepcopy(document)
    candidates: list[dict[str, Any]] = []
    for section in document:
        candidates.append({
            "section_name": section["section_name"],
            "section_number": section.get("section_number"),
            "subsection_name": None,
            "subsection_number": None,
            "paragraphs": section_paragraphs(section),
            NESTED_QUESTION: section.get(NESTED_QUESTION),
        })
        candidates.extend({
            "section_name": section["section_name"],
            "section_number": section.get("section_number"),
            "subsection_name": subsection["section_name"],
            "subsection_number": subsection.get("section_number"),
            "paragraphs": copy.deepcopy(subsection["paragraphs"]),
            NESTED_QUESTION: subsection.get(NESTED_QUESTION),
        } for subsection in section["subsections"])
    return candidates


def _candidate_key(candidate: dict[str, Any], view: str) -> tuple[Any, ...]:
    key = (candidate["section_name"], candidate.get("section_number"))
    if view != "sections":
        key += (candidate.get("subsection_name"), candidate.get("subsection_number"))
    return key


def validate_matches(
    matches: Any,
    document1: list[dict[str, Any]],
    document2: list[dict[str, Any]],
    view: str,
) -> None:
    source = _flat_candidates(document1) if view == "sections" else _nested_candidates(document1)
    target = _flat_candidates(document2) if view == "sections" else _nested_candidates(document2)
    validate_match_candidates(matches, source, target, view)


def validate_match_candidates(
    matches: Any,
    source: set[tuple[Any, ...]],
    target: set[tuple[Any, ...]],
    view: str,
) -> None:
    if not isinstance(matches, list):
        raise ValueError("Matches must be a JSON array")
    covered: set[tuple[Any, ...]] = set()
    pairs: set[tuple[tuple[Any, ...], tuple[Any, ...] | None]] = set()
    for match in matches:
        if view == "sections":
            source_key = (match["paper1_section_name"], match["paper1_section_number"])
            target_key = None if match["paper2_section_name"] is None else (
                match["paper2_section_name"], match["paper2_section_number"]
            )
            if target_key is None and match["paper2_section_number"] is not None:
                raise ValueError(f"Inconsistent null target: {match}")
        else:
            source_key = (
                match["paper1_section_name"], match["paper1_section_number"],
                match["paper1_subsection_name"], match["paper1_subsection_number"],
            )
            target_key = None if match["paper2_section_name"] is None else (
                match["paper2_section_name"], match["paper2_section_number"],
                match["paper2_subsection_name"], match["paper2_subsection_number"],
            )
            if target_key is None and any(match[name] is not None for name in [
                "paper2_section_number", "paper2_subsection_name", "paper2_subsection_number"
            ]):
                raise ValueError(f"Inconsistent null target: {match}")
        if source_key not in source:
            raise ValueError(f"Unknown source candidate: {source_key}")
        if target_key is not None and target_key not in target:
            raise ValueError(f"Unknown target candidate: {target_key}")
        if not isinstance(match.get("basis"), str) or not match["basis"].strip():
            raise ValueError("Every match needs a non-empty basis")
        pair = (source_key, target_key)
        if pair in pairs:
            raise ValueError(f"Duplicate source-target match: {pair}")
        pairs.add(pair)
        covered.add(source_key)
    if covered != source:
        missing = sorted(source - covered, key=str)
        raise ValueError(f"Matching omitted {len(missing)} source candidates: {missing}")


def _normalized_identifier(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    translation = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})
    return unicodedata.normalize("NFKC", value).translate(translation).casefold()


def _resolve_candidate(
    candidate: tuple[Any, ...], valid_candidates: set[tuple[Any, ...]]
) -> tuple[Any, ...]:
    if candidate in valid_candidates:
        return candidate
    if len(candidate) == 4:
        same_level = {
            valid for valid in valid_candidates
            if (candidate[2] is None) == (valid[2] is None)
        }
        if same_level:
            valid_candidates = same_level
    provided = [index for index, value in enumerate(candidate) if value is not None]
    exact_normalized = [
        valid
        for valid in valid_candidates
        if all(_normalized_identifier(candidate[index]) == _normalized_identifier(valid[index]) for index in provided)
    ]
    if len(exact_normalized) == 1:
        return exact_normalized[0]
    if len(provided) >= 3:
        scored = [
            (
                sum(
                    _normalized_identifier(candidate[index]) == _normalized_identifier(valid[index])
                    for index in provided
                ),
                valid,
            )
            for valid in valid_candidates
        ]
        best_score = max(score for score, _ in scored)
        best = [valid for score, valid in scored if score == best_score]
        if best_score >= len(provided) - 1 and len(best) == 1:
            return best[0]
    return candidate


def normalize_matches(
    matches: list[dict[str, Any]],
    document1: list[dict[str, Any]],
    document2: list[dict[str, Any]],
    view: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    source = _flat_candidates(document1) if view == "sections" else _nested_candidates(document1)
    target = _flat_candidates(document2) if view == "sections" else _nested_candidates(document2)
    return normalize_match_candidates(matches, source, target, view)


def normalize_match_candidates(
    matches: list[dict[str, Any]],
    source: set[tuple[Any, ...]],
    target: set[tuple[Any, ...]],
    view: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Canonicalize uniquely resolvable identifiers; never alter match selection."""
    source_fields = ["paper1_section_name", "paper1_section_number"]
    target_fields = ["paper2_section_name", "paper2_section_number"]
    if view != "sections":
        source_fields += ["paper1_subsection_name", "paper1_subsection_number"]
        target_fields += ["paper2_subsection_name", "paper2_subsection_number"]

    normalized: list[dict[str, Any]] = []
    changes: list[str] = []
    seen: set[tuple[tuple[Any, ...], tuple[Any, ...] | None]] = set()
    for index, original in enumerate(matches):
        match = copy.deepcopy(original)
        raw_source = tuple(match[field] for field in source_fields)
        resolved_source = _resolve_candidate(raw_source, source)
        if resolved_source != raw_source:
            changes.append(f"entry {index}: canonicalized source identifier")
            for field, value in zip(source_fields, resolved_source):
                match[field] = value

        if match["paper2_section_name"] is None and any(
            match[field] is not None for field in target_fields[1:]
        ):
            changes.append(f"entry {index}: cleared fields attached to null target")
            for field in target_fields[1:]:
                match[field] = None
        raw_target = None if match["paper2_section_name"] is None else tuple(
            match[field] for field in target_fields
        )
        resolved_target = None if raw_target is None else _resolve_candidate(raw_target, target)
        if resolved_target != raw_target:
            changes.append(f"entry {index}: canonicalized target identifier")
            for field, value in zip(target_fields, resolved_target):
                match[field] = value

        pair = (resolved_source, resolved_target)
        if pair in seen:
            changes.append(f"entry {index}: removed duplicate source-target pair")
            continue
        seen.add(pair)
        normalized.append(match)
    return normalized, changes


def batch_candidates(
    candidates: list[dict[str, Any]], maximum_candidates: int | None
) -> list[list[dict[str, Any]]]:
    if not maximum_candidates:
        return [candidates]
    return [
        candidates[index:index + maximum_candidates]
        for index in range(0, len(candidates), maximum_candidates)
    ]


class Harness:
    def __init__(self, config_path: Path, *, force: bool = False) -> None:
        self.config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        self.force = force
        self.output = ROOT / self.config["output_dir"]
        self.cache = ROOT / self.config["cache_dir"]
        self.api: ClaudeSkills | None = None
        self.prepared: set[str] = set()
        self.questioned: set[str] = set()
        self._validate_config()

    def _validate_config(self) -> None:
        stage_ids = [stage["id"] for stage in self.config["stages"]]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("Stage ids must be unique")
        for stage in self.config["stages"]:
            if stage["skill"] not in self.config["skills"]:
                raise ValueError(f"Unknown Skill key on stage {stage['id']}")
            if stage["kind"] == "match" and stage.get("view") not in {
                "sections", "sections_and_subsections"
            }:
                raise ValueError(f"Unknown match view on stage {stage['id']}")
        for name, dataset in self.config["datasets"].items():
            ids = [document["id"] for document in dataset["documents"]]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate document id in {name}")
            selected = [*dataset["question_documents"], *dataset["match_pair"]]
            if any(document_id not in ids for document_id in selected):
                raise ValueError(f"Dataset {name} selects an unknown document")

    def _api(self) -> ClaudeSkills:
        if self.api is None:
            self.api = ClaudeSkills(ROOT, self.cache / "skill-registry.json", self.config["model"])
        return self.api

    def _skill(self, stage: dict[str, Any]) -> SkillRef:
        path = ROOT / self.config["skills"][stage["skill"]]
        return self._api().register(path)

    def _stage(self, kind: str) -> dict[str, Any]:
        return next(stage for stage in self.config["stages"] if stage["kind"] == kind)

    def _dataset_dir(self, dataset_name: str) -> Path:
        return self.output / dataset_name

    def _document_map(self, dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {document["id"]: document for document in dataset["documents"]}

    def _log(
        self,
        dataset: str,
        stage: str,
        result: RunResult,
        skills: Iterable[SkillRef],
        *,
        inputs: Iterable[Path],
        outputs: Iterable[Path],
        detail: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dataset": dataset,
            "stage": stage,
            "model": self.config["model"],
            "response_id": result.response_id,
            "stop_reason": result.stop_reason,
            "usage": result.usage,
            "skills": [skill.__dict__ for skill in skills],
            "inputs": [
                {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)}
                for path in inputs
            ],
            "outputs": [
                {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)}
                for path in outputs
            ],
            "detail": detail or {},
        }
        self.output.mkdir(parents=True, exist_ok=True)
        with (self.output / "runs.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _log_error(
        self,
        dataset: str,
        stage: str,
        error: Exception,
        detail: dict[str, Any],
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dataset": dataset,
            "stage": stage,
            "error_type": type(error).__name__,
            "status_code": getattr(error, "status_code", None),
            "request_id": getattr(error, "request_id", None),
            "message": str(error),
            "detail": detail,
        }
        self.output.mkdir(parents=True, exist_ok=True)
        with (self.output / "errors.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _source_path(self, dataset_name: str, document: dict[str, Any]) -> Path:
        source = document["xhtml"]
        expected_hash = source["sha256"]
        if "path" in source:
            path = ROOT / source["path"]
        else:
            directory = self.cache / dataset_name / "sources"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{document['id']}.xhtml"
            if not path.exists() or sha256_file(path) != expected_hash:
                request = urllib.request.Request(
                    source["url"], headers={"User-Agent": "SME-Claude-Skill-Harness/1"}
                )
                with urllib.request.urlopen(request) as response:
                    path.write_bytes(response.read())
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise ValueError(f"Source hash mismatch for {document['id']}: {actual_hash}")
        return path

    def prepare(self, dataset_name: str, stage: dict[str, Any] | None = None) -> None:
        if dataset_name in self.prepared:
            return
        dataset = self.config["datasets"][dataset_name]
        directory = self._dataset_dir(dataset_name)
        directory.mkdir(parents=True, exist_ok=True)
        extraction_stage = stage or self._stage("extract")
        extraction_skill: SkillRef | None = None
        for document in dataset["documents"]:
            nested_path = directory / f"{document['id']}-nested-content.json"
            flat_path = directory / f"{document['id']}-content.json"
            if nested_path.exists() and flat_path.exists() and not self.force:
                nested = read_json(nested_path)
                validate_document(nested)
                if "xhtml" in document:
                    validate_story_shape(nested, document)
                continue

            if "json" in document:
                source_path = ROOT / document["json"]
                nested = strip_questions(read_json(source_path))
                result = None
            else:
                source_path = self._source_path(dataset_name, document)
                extraction_skill = extraction_skill or self._skill(extraction_stage)
                prompt = (
                    "Use the attached extraction Skill exactly as written in narrative mode. "
                    "Claude must extract the sections, source-marked scenes, and paragraphs from the "
                    "attached XHTML. Save the strict nested JSON result to "
                    f"/mnt/data/{nested_path.name} and return that generated file."
                )
                result, payload = self._api().run_file(
                    extraction_skill, prompt, source_path, nested_path.name, max_tokens=8192
                )
                nested = json.loads(payload.decode("utf-8"))

            validate_document(nested)
            if "xhtml" in document:
                validate_story_shape(nested, document)
            write_json(nested_path, nested)
            write_json(flat_path, flatten_document(nested, with_questions=False))
            if result is not None and extraction_skill is not None:
                self._log(
                    dataset_name,
                    f"{extraction_stage['id']}:{document['id']}",
                    result,
                    [extraction_skill],
                    inputs=[source_path],
                    outputs=[nested_path, flat_path],
                    detail={"title": document["title"]},
                )
            print(f"[{dataset_name}] prepared {document['id']}")
        self.prepared.add(dataset_name)

    def questions(self, dataset_name: str, stage: dict[str, Any] | None = None) -> None:
        if dataset_name in self.questioned:
            return
        dataset = self.config["datasets"][dataset_name]
        self.prepare(dataset_name)
        question_stage = stage or self._stage("questions")
        skill = self._skill(question_stage)
        directory = self._dataset_dir(dataset_name)
        documents = self._document_map(dataset)
        for document_id in dataset["question_documents"]:
            content_path = directory / f"{document_id}-nested-content.json"
            output_path = directory / f"{document_id}-nested-questions.json"
            flat_path = directory / f"{document_id}-questions.json"
            content = read_json(content_path)
            annotated = (
                read_json(output_path)
                if output_path.exists() and not self.force
                else copy.deepcopy(content)
            )
            if strip_questions(annotated) != content:
                raise ValueError(f"Question output content drifted for {document_id}")

            for section_index, section in enumerate(annotated):
                self._annotate_unit(
                    dataset_name,
                    document_id,
                    f"section:{section_index}",
                    section,
                    section_paragraphs(section),
                    annotated,
                    output_path,
                    content_path,
                    skill,
                    documents[document_id],
                )
                for subsection_index, subsection in enumerate(section["subsections"]):
                    self._annotate_unit(
                        dataset_name,
                        document_id,
                        f"subsection:{section_index}:{subsection_index}",
                        subsection,
                        subsection["paragraphs"],
                        annotated,
                        output_path,
                        content_path,
                        skill,
                        documents[document_id],
                    )
            validate_questions(annotated)
            write_json(output_path, annotated)
            write_json(flat_path, flatten_document(annotated, with_questions=True))
            print(f"[{dataset_name}] generated questions for {document_id}")
        self.questioned.add(dataset_name)

    def _annotate_unit(
        self,
        dataset_name: str,
        document_id: str,
        unit_id: str,
        target: dict[str, Any],
        paragraphs: list[dict[str, Any]],
        document: list[dict[str, Any]],
        output_path: Path,
        content_path: Path,
        skill: SkillRef,
        document_config: dict[str, Any],
    ) -> None:
        if not self.force and NESTED_QUESTION in target:
            return
        if not paragraphs:
            target[NESTED_QUESTION] = None
            write_json(output_path, document)
            return
        candidate = {
            "section_name": target["section_name"],
            "section_number": target.get("section_number"),
            "paragraphs": paragraphs,
        }
        prompt = (
            "Use the attached question-generation Skill exactly as written. This call covers one "
            "section or subsection, and every supplied paragraph is its complete evidence. Return "
            f"only the Skill's {FLAT_QUESTION} field in the required JSON object.\n\n"
            f"Document: {document_config['title']}\n"
            f"Unit:\n{json.dumps(candidate, ensure_ascii=False)}"
        )
        result = self._api().run_json([skill], prompt, _question_schema(), max_tokens=512)
        question = result.value[FLAT_QUESTION]
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"Question Skill returned no question for {document_id}/{unit_id}")
        target[NESTED_QUESTION] = question.strip()
        write_json(output_path, document)
        self._log(
            dataset_name,
            f"questions:{document_id}:{unit_id}",
            result,
            [skill],
            inputs=[content_path],
            outputs=[output_path],
            detail={"question": question.strip()},
        )

    def match(self, dataset_name: str, stage: dict[str, Any]) -> None:
        dataset = self.config["datasets"][dataset_name]
        self.questions(dataset_name)
        directory = self._dataset_dir(dataset_name)
        document_a, document_b = dataset["match_pair"]
        view = stage["view"]
        nested = view == "sections_and_subsections"
        input_suffix = "nested-questions" if nested else "questions"
        input_a = directory / f"{document_a}-{input_suffix}.json"
        input_b = directory / f"{document_b}-{input_suffix}.json"
        content_a, content_b = read_json(input_a), read_json(input_b)
        skill = self._skill(stage)
        suffix = stage["output_suffix"]
        prefix = f"{document_a}-{document_b}"
        forward_path = directory / f"{prefix}-p1-p2-{suffix}.json"
        reverse_path = directory / f"{prefix}-p2-p1-{suffix}.json"
        combined_path = directory / f"{prefix}-{suffix}.json"

        forward = self._match_direction(
            dataset_name, stage, skill, document_a, content_a, input_a,
            document_b, content_b, input_b, forward_path,
        )
        reverse = self._match_direction(
            dataset_name, stage, skill, document_b, content_b, input_b,
            document_a, content_a, input_a, reverse_path,
        )
        write_json(combined_path, {"p1-p2": forward, "p2-p1": reverse})
        print(f"[{dataset_name}] completed {stage['id']} in both directions")

    def _match_direction(
        self,
        dataset_name: str,
        stage: dict[str, Any],
        skill: SkillRef,
        document1_id: str,
        document1: list[dict[str, Any]],
        input1: Path,
        document2_id: str,
        document2: list[dict[str, Any]],
        input2: Path,
        output_path: Path,
    ) -> list[dict[str, Any]]:
        if output_path.exists() and not self.force:
            matches = read_json(output_path)
            validate_matches(matches, document1, document2, stage["view"])
            return matches
        source_candidates = matching_candidates(document1, stage["view"])
        target_candidates = matching_candidates(document2, stage["view"])
        batches = batch_candidates(source_candidates, stage.get("source_batch_size"))
        matches: list[dict[str, Any]] = []
        for batch_index, batch in enumerate(batches, start=1):
            batch_path = (
                output_path
                if len(batches) == 1
                else output_path.with_name(f"{output_path.stem}.batch-{batch_index:02d}.json")
            )
            matches.extend(self._match_batch(
                dataset_name, stage, skill, document1_id, batch, input1,
                document2_id, target_candidates, input2, batch_path, batch_index, len(batches),
            ))
        validate_matches(matches, document1, document2, stage["view"])
        write_json(output_path, matches)
        return matches

    def _match_batch(
        self,
        dataset_name: str,
        stage: dict[str, Any],
        skill: SkillRef,
        document1_id: str,
        source_candidates: list[dict[str, Any]],
        input1: Path,
        document2_id: str,
        target_candidates: list[dict[str, Any]],
        input2: Path,
        output_path: Path,
        batch_index: int,
        batch_count: int,
    ) -> list[dict[str, Any]]:
        source = {_candidate_key(candidate, stage["view"]) for candidate in source_candidates}
        target = {_candidate_key(candidate, stage["view"]) for candidate in target_candidates}
        if output_path.exists() and not self.force:
            matches = read_json(output_path)
            validate_match_candidates(matches, source, target, stage["view"])
            return matches
        prompt = (
            "Use the attached matching Skill exactly as written for one directional pass. The harness "
            "has deterministically performed the Skill's candidate-construction step; make only the "
            "Skill's role-correspondence judgments. Compare every paper1 candidate below against every "
            "paper2 candidate. Multiple legitimate matches and null matches must be preserved. The "
            "outer matches object is only the API transport wrapper; each entry must use the Skill's "
            "exact output schema. Include at least one entry for every paper1 candidate and copy its "
            "identifying fields together and verbatim.\n\n"
            f"document1_id: {document1_id}\n"
            f"paper1_candidates:\n{json.dumps(source_candidates, ensure_ascii=False)}\n\n"
            f"document2_id: {document2_id}\n"
            f"paper2_candidates:\n{json.dumps(target_candidates, ensure_ascii=False)}"
        )
        schema = _match_schema(stage["view"], source, target)
        for attempt in range(1, stage["validation_attempts"] + 1):
            try:
                result = self._api().run_json(
                    [skill], prompt, schema, max_tokens=stage["max_tokens"]
                )
            except Exception as error:
                status = getattr(error, "status_code", None)
                transient = status in {408, 409, 429} or (isinstance(status, int) and status >= 500)
                self._log_error(
                    dataset_name,
                    f"{stage['id']}:{document1_id}-to-{document2_id}:batch-{batch_index}",
                    error,
                    {"attempt": attempt, "batch": f"{batch_index}/{batch_count}"},
                )
                if not transient or attempt == stage["validation_attempts"]:
                    raise
                continue
            raw_matches = result.value["matches"]
            matches, normalizations = normalize_match_candidates(
                raw_matches, source, target, stage["view"]
            )
            normalizations = [*result.transport_notes, *normalizations]
            try:
                validate_match_candidates(matches, source, target, stage["view"])
            except ValueError as error:
                rejected_path = output_path.with_name(
                    f"{output_path.stem}.rejected-{result.response_id}.json"
                )
                write_json(rejected_path, raw_matches)
                self._log(
                    dataset_name,
                    f"{stage['id']}:{document1_id}-to-{document2_id}:batch-{batch_index}:rejected",
                    result,
                    [skill],
                    inputs=[input1, input2],
                    outputs=[rejected_path],
                    detail={
                        "attempt": attempt,
                        "batch": f"{batch_index}/{batch_count}",
                        "normalizations": normalizations,
                        "validation_error": str(error),
                    },
                )
                if attempt == stage["validation_attempts"]:
                    raise
                continue
            write_json(output_path, matches)
            logged_outputs = [output_path]
            if normalizations:
                raw_path = output_path.with_name(
                    f"{output_path.stem}.raw-{result.response_id}.json"
                )
                write_json(raw_path, raw_matches)
                logged_outputs.append(raw_path)
            if result.transport_notes and result.raw_text is not None:
                transport_path = output_path.with_name(
                    f"{output_path.stem}.raw-{result.response_id}.txt"
                )
                transport_path.write_text(result.raw_text + "\n", encoding="utf-8")
                logged_outputs.append(transport_path)
            self._log(
                dataset_name,
                f"{stage['id']}:{document1_id}-to-{document2_id}:batch-{batch_index}",
                result,
                [skill],
                inputs=[input1, input2],
                outputs=logged_outputs,
                detail={
                    "attempt": attempt,
                    "batch": f"{batch_index}/{batch_count}",
                    "normalizations": normalizations,
                },
            )
            return matches
        raise RuntimeError("unreachable")

    def run(self, dataset_names: list[str], stage_id: str) -> None:
        stages = self.config["stages"]
        if stage_id != "all":
            stages = [stage for stage in stages if stage["id"] == stage_id]
            if not stages:
                raise ValueError(f"Unknown stage: {stage_id}")
        for dataset_name in dataset_names:
            if dataset_name not in self.config["datasets"]:
                raise ValueError(f"Unknown dataset: {dataset_name}")
            for stage in stages:
                if stage["kind"] == "extract":
                    self.prepare(dataset_name, stage)
                elif stage["kind"] == "questions":
                    self.questions(dataset_name, stage)
                else:
                    self.match(dataset_name, stage)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dataset", default="all", help="dataset id or all")
    parser.add_argument("--stage", default="all", help="stage id or all")
    parser.add_argument("--force", action="store_true", help="rerun completed API calls")
    args = parser.parse_args()
    harness = Harness(args.config.resolve(), force=args.force)
    dataset_names = (
        list(harness.config["datasets"])
        if args.dataset == "all"
        else [args.dataset]
    )
    harness.run(dataset_names, args.stage)


if __name__ == "__main__":
    main()
