"""Deterministic harness for configurable, non-deterministic Claude Skill calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from ..document import (
    NESTED_VIEW,
    QUESTION_FIELD,
    SECTIONS_VIEW,
    CandidateView,
    iter_structural_units,
    matching_candidates,
    read_json,
    strip_questions,
    validate_document,
    write_json,
)
from ..incremental_graph.skill_api import (
    ClaudeSkills,
    RunResult,
    SkillCallPolicy,
    SkillRef,
    SkillSessionBudget,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("pipeline.yaml")
MATCH_FIELDS = {"source_id", "target_id", "basis"}
SOURCE_KINDS = ("json", "xhtml", "text", "pdf")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def validate_story_shape(document: list[dict[str, Any]], config: dict[str, Any]) -> None:
    """Require the source-marked divisions and scenes configured for a story."""

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


def validate_text_completion(document: list[dict[str, Any]], source_text: str) -> None:
    """Require the extracted paragraphs to preserve the source's final passage."""

    source_lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    source_tail: list[str] = []
    while source_lines and len(re.findall(r"\w+", " ".join(source_tail))) < 8:
        source_tail.insert(0, source_lines.pop())
    source_tokens = re.findall(
        r"\w+",
        re.sub(r"-\s+", "", " ".join(source_tail)).casefold(),
    )
    paragraph_text = " ".join(
        paragraph["text"]
        for section in document
        for paragraphs in (
            section["paragraphs"],
            *(subsection["paragraphs"] for subsection in section["subsections"]),
        )
        for paragraph in paragraphs
    )
    output_tokens = re.findall(r"\w+", paragraph_text.casefold())
    window_size = len(source_tokens)
    expected = source_tokens[-window_size:]
    if not expected or not any(
        output_tokens[index:index + window_size] == expected
        for index in range(len(output_tokens) - window_size + 1)
    ):
        raise ValueError("Extracted content is missing the final source passage")


def _question_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {QUESTION_FIELD: {"type": ["string", "null"]}},
        "required": [QUESTION_FIELD],
        "additionalProperties": False,
    }


def _content_schema() -> dict[str, Any]:
    paragraph = {
        "type": "object",
        "properties": {
            "paragraph_number": {"type": "integer", "minimum": 0},
            "text": {"type": "string", "minLength": 1},
        },
        "required": ["paragraph_number", "text"],
        "additionalProperties": False,
    }
    subsection = {
        "type": "object",
        "properties": {
            "section_name": {"type": "string", "minLength": 1},
            "section_number": {"type": ["string", "null"]},
            "paragraphs": {"type": "array", "items": paragraph},
        },
        "required": ["section_name", "section_number", "paragraphs"],
        "additionalProperties": False,
    }
    return {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "properties": {
                **subsection["properties"],
                "subsections": {"type": "array", "items": subsection},
            },
            "required": [*subsection["required"], "subsections"],
            "additionalProperties": False,
        },
    }


def _match_schema() -> dict[str, Any]:
    """Return a stable schema; deterministic validation enforces candidate IDs."""

    entry = {
        "type": "object",
        "properties": {
            "source_id": {"type": "string", "minLength": 1},
            "target_id": {"type": ["string", "null"]},
            "basis": {"type": "string", "minLength": 1},
        },
        "required": ["source_id", "target_id", "basis"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"matches": {"type": "array", "items": entry}},
        "required": ["matches"],
        "additionalProperties": False,
    }


def validate_match_records(
    matches: Any,
    source_ids: set[str],
    target_ids: set[str],
    *,
    require_coverage: bool = True,
) -> None:
    """Validate the one match-record contract used by both matching views."""

    if not isinstance(matches, list):
        raise ValueError("Matches must be a JSON array")
    pairs: set[tuple[str, str | None]] = set()
    targets_by_source: dict[str, set[str | None]] = {}
    for match in matches:
        if not isinstance(match, dict) or set(match) != MATCH_FIELDS:
            raise ValueError(f"Every match must contain exactly {sorted(MATCH_FIELDS)}")
        source_id = match["source_id"]
        target_id = match["target_id"]
        if source_id not in source_ids:
            raise ValueError(f"Unknown source candidate: {source_id!r}")
        if target_id is not None and target_id not in target_ids:
            raise ValueError(f"Unknown target candidate: {target_id!r}")
        if not isinstance(match["basis"], str) or not match["basis"].strip():
            raise ValueError("Every match needs a non-empty basis")
        pair = (source_id, target_id)
        if pair in pairs:
            raise ValueError(f"Duplicate source-target match: {pair}")
        pairs.add(pair)
        targets_by_source.setdefault(source_id, set()).add(target_id)

    contradictory = [
        source_id
        for source_id, targets in targets_by_source.items()
        if None in targets and len(targets) > 1
    ]
    if contradictory:
        raise ValueError(f"Sources cannot have both matched and null records: {contradictory}")
    if require_coverage and set(targets_by_source) != source_ids:
        missing = sorted(source_ids - set(targets_by_source))
        raise ValueError(f"Matching omitted {len(missing)} source candidates: {missing}")


def batch_candidates(
    candidates: list[dict[str, Any]],
    maximum_candidates: int | None,
) -> list[list[dict[str, Any]]]:
    if not maximum_candidates:
        return [candidates]
    return [
        candidates[index:index + maximum_candidates]
        for index in range(0, len(candidates), maximum_candidates)
    ]


class Harness:
    """Execute configured stages while keeping all language judgment in Skills."""

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
        try:
            SkillSessionBudget(**self.config.get("session_budget", {}))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid Skill session budget: {error}") from error
        stage_ids = [stage["id"] for stage in self.config["stages"]]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("Stage ids must be unique")
        for stage in self.config["stages"]:
            if stage["skill"] not in self.config["skills"]:
                raise ValueError(f"Unknown Skill key on stage {stage['id']}")
            if "validation_attempts" in stage:
                raise ValueError(
                    f"Stage {stage['id']} cannot configure validation_attempts; "
                    "one judgment always makes one request"
                )
            self._call_policy(stage)
            if stage["kind"] == "match" and stage.get("view") not in {
                SECTIONS_VIEW,
                NESTED_VIEW,
            }:
                raise ValueError(f"Unknown match view on stage {stage['id']}")
        for name, dataset in self.config["datasets"].items():
            ids = [document["id"] for document in dataset["documents"]]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate document id in {name}")
            selected = [*dataset["question_documents"], *dataset["match_pair"]]
            if any(document_id not in ids for document_id in selected):
                raise ValueError(f"Dataset {name} selects an unknown document")
            if not set(dataset["match_pair"]).issubset(dataset["question_documents"]):
                raise ValueError(f"Dataset {name} must generate questions before matching")
            if len(dataset["match_pair"]) != 2:
                raise ValueError(f"Dataset {name} match_pair must contain exactly two ids")
            for document in dataset["documents"]:
                sources = [kind for kind in SOURCE_KINDS if kind in document]
                if len(sources) != 1:
                    raise ValueError(
                        f"Document {name}/{document['id']} needs exactly one "
                        f"{', '.join(SOURCE_KINDS)} source"
                    )
        study_datasets = self.config.get("study", {}).get("datasets", {})
        unknown = set(study_datasets) - set(self.config["datasets"])
        if unknown:
            raise ValueError(f"Study selects unknown dataset {sorted(unknown)[0]}")
        prefixes = [settings.get("participant_prefix") for settings in study_datasets.values()]
        if any(
            not isinstance(prefix, str) or not re.fullmatch(r"[A-Z]{2}", prefix)
            for prefix in prefixes
        ):
            raise ValueError("Study participant prefixes must be two uppercase letters")
        if len(prefixes) != len(set(prefixes)):
            raise ValueError("Study participant prefixes must be unique")

    def _api(self) -> ClaudeSkills:
        if self.api is None:
            self.api = ClaudeSkills(
                ROOT,
                self.cache / "skill-registry.json",
                self.config["model"],
                session_budget=SkillSessionBudget(
                    **self.config.get("session_budget", {})
                ),
            )
        return self.api

    def _skill(self, stage: dict[str, Any]) -> SkillRef:
        return self._api().register(ROOT / self.config["skills"][stage["skill"]])

    def _call_policy(self, stage: dict[str, Any]) -> SkillCallPolicy:
        options = {
            **self.config.get("execution", {}),
            **stage.get("execution", {}),
        }
        try:
            return SkillCallPolicy(max_tokens=int(stage["max_tokens"]), **options)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid execution policy on stage {stage['id']}: {error}") from error

    def _stage(self, kind: str) -> dict[str, Any]:
        return next(stage for stage in self.config["stages"] if stage["kind"] == kind)

    def _dataset_dir(self, dataset_name: str) -> Path:
        return self.output / dataset_name

    def _content_dir(self, dataset_name: str) -> Path:
        configured = self.config["datasets"][dataset_name].get("content_dir")
        return ROOT / configured if configured else self._dataset_dir(dataset_name)

    @staticmethod
    def _document_map(dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {document["id"]: document for document in dataset["documents"]}

    @staticmethod
    def _content_path(directory: Path, document_id: str) -> Path:
        return directory / f"{document_id}.content.json"

    @staticmethod
    def _questions_path(directory: Path, document_id: str) -> Path:
        return directory / f"{document_id}.questions.json"

    @staticmethod
    def _matches_path(
        directory: Path,
        document_a: str,
        document_b: str,
        stage_id: str,
    ) -> Path:
        return directory / f"{document_a}--{document_b}.{stage_id}.json"

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
            "call_policy": result.call_policy,
            "transport_notes": list(result.transport_notes),
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
            "usage": getattr(error, "usage", {}),
            "detail": detail,
        }
        self.output.mkdir(parents=True, exist_ok=True)
        with (self.output / "errors.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _source_path(
        self,
        dataset_name: str,
        document: dict[str, Any],
        source_kind: str,
    ) -> Path:
        source = document[source_kind]
        expected_hash = source["sha256"]
        if "path" in source:
            path = ROOT / source["path"]
        else:
            directory = self.cache / dataset_name / "sources"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{document['id']}.{source_kind}"
            if not path.exists() or sha256_file(path) != expected_hash:
                request = urllib.request.Request(
                    source["url"],
                    headers={"User-Agent": "SME-Claude-Skill-Harness/1"},
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
        directory = self._content_dir(dataset_name)
        directory.mkdir(parents=True, exist_ok=True)
        extraction_stage = stage or self._stage("extract")
        extraction_skill: SkillRef | None = None

        for document in dataset["documents"]:
            source_kind = next(kind for kind in SOURCE_KINDS if kind in document)
            output_path = self._content_path(directory, document["id"])
            if output_path.exists() and not self.force:
                content = read_json(output_path)
                validate_document(content)
                if source_kind == "xhtml":
                    validate_story_shape(content, document)
                if source_kind == "text":
                    source_path = self._source_path(dataset_name, document, source_kind)
                    validate_text_completion(content, source_path.read_text(encoding="utf-8"))
                continue

            if source_kind == "json":
                source_path = ROOT / document["json"]
                content = strip_questions(read_json(source_path))
                result = None
            else:
                source_path = self._source_path(dataset_name, document, source_kind)
                extraction_skill = extraction_skill or self._skill(extraction_stage)
                mode = "narrative" if source_kind == "xhtml" else "legal"
                instructions = (
                    f"Use the attached extraction Skill exactly as written in {mode} mode. "
                    "Extract only source-marked structural boundaries and their paragraphs. "
                    "Read the attached source once, then return the canonical document directly "
                    "through the provided structured-output schema. Do not create an output file "
                    "or return explanatory prose."
                )
                try:
                    result = self._api().run_json_file(
                        extraction_skill,
                        prompt,
                        source_path,
                        _content_schema(),
                        policy=self._call_policy(extraction_stage),
                        cacheable_prompt=instructions,
                    )
                except Exception as error:
                    self._log_error(
                        dataset_name,
                        f"{extraction_stage['id']}:{document['id']}",
                        error,
                        {"source": source_path.relative_to(ROOT).as_posix()},
                    )
                    raise
                content = result.value

            validate_document(content)
            if source_kind == "xhtml":
                validate_story_shape(content, document)
            if source_kind == "text":
                validate_text_completion(content, source_path.read_text(encoding="utf-8"))
            write_json(output_path, content)
            if result is not None and extraction_skill is not None:
                self._log(
                    dataset_name,
                    f"{extraction_stage['id']}:{document['id']}",
                    result,
                    [extraction_skill],
                    inputs=[source_path],
                    outputs=[output_path],
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
        directory = self._dataset_dir(dataset_name)
        content_directory = self._content_dir(dataset_name)
        directory.mkdir(parents=True, exist_ok=True)
        documents = self._document_map(dataset)
        skill: SkillRef | None = None

        for document_id in dataset["question_documents"]:
            content_path = self._content_path(content_directory, document_id)
            output_path = self._questions_path(directory, document_id)
            content = read_json(content_path)
            annotated = (
                read_json(output_path)
                if output_path.exists() and not self.force
                else json.loads(json.dumps(content))
            )
            if strip_questions(annotated) != content:
                raise ValueError(f"Question output content drifted for {document_id}")

            for unit in iter_structural_units(annotated):
                if not self.force and QUESTION_FIELD in unit.source:
                    continue
                if not unit.evidence:
                    unit.source[QUESTION_FIELD] = None
                    write_json(output_path, annotated)
                    continue
                skill = skill or self._skill(question_stage)
                candidate = unit.candidate()
                candidate.pop(QUESTION_FIELD)
                instructions = (
                    "Use the attached question-generation Skill exactly as written. "
                    "The supplied candidate contains the complete evidence for one section or "
                    "subsection. Return only the required JSON object."
                )
                prompt = (
                    f"document_id: {document_id}\n"
                    f"document_title: {documents[document_id]['title']}\n"
                    f"candidate:\n{json.dumps(candidate, ensure_ascii=False)}"
                )
                try:
                    result = self._api().run_json(
                        [skill],
                        prompt,
                        _question_schema(),
                        policy=self._call_policy(question_stage),
                        cacheable_prompt=instructions,
                    )
                except Exception as error:
                    self._log_error(
                        dataset_name,
                        f"questions:{document_id}:{unit.unit_id}",
                        error,
                        {"input": content_path.relative_to(ROOT).as_posix()},
                    )
                    raise
                question = result.value[QUESTION_FIELD]
                if not isinstance(question, str) or not question.strip():
                    raise ValueError(
                        f"Question Skill returned no question for {document_id}/{unit.unit_id}"
                    )
                unit.source[QUESTION_FIELD] = question.strip()
                write_json(output_path, annotated)
                self._log(
                    dataset_name,
                    f"questions:{document_id}:{unit.unit_id}",
                    result,
                    [skill],
                    inputs=[content_path],
                    outputs=[output_path],
                    detail={"question": question.strip()},
                )

            validate_document(annotated, require_structural_questions=True)
            write_json(output_path, annotated)
            print(f"[{dataset_name}] generated questions for {document_id}")
        self.questioned.add(dataset_name)

    def match(self, dataset_name: str, stage: dict[str, Any]) -> None:
        dataset = self.config["datasets"][dataset_name]
        self.questions(dataset_name)
        directory = self._dataset_dir(dataset_name)
        document_a, document_b = dataset["match_pair"]
        path_a = self._questions_path(directory, document_a)
        path_b = self._questions_path(directory, document_b)
        documents = {document_a: read_json(path_a), document_b: read_json(path_b)}
        for document in documents.values():
            validate_document(document, require_structural_questions=True)

        output_path = self._matches_path(directory, document_a, document_b, stage["id"])
        payload = self._initial_match_output(dataset_name, stage)
        if output_path.exists() and not self.force:
            payload = read_json(output_path)
            self._validate_match_output(payload, dataset_name, stage, documents)

        directions = {
            (direction["source_document_id"], direction["target_document_id"]): direction
            for direction in payload["directions"]
        }
        order = [(document_a, document_b), (document_b, document_a)]
        skill: SkillRef | None = None

        for source_id, target_id in order:
            existing = directions.get((source_id, target_id), {}).get("matches", [])

            def checkpoint(matches: list[dict[str, Any]]) -> None:
                directions[(source_id, target_id)] = {
                    "source_document_id": source_id,
                    "target_document_id": target_id,
                    "matches": matches,
                }
                payload["directions"] = [
                    directions[pair] for pair in order if pair in directions
                ]
                write_json(output_path, payload)

            direction, skill = self._match_direction(
                dataset_name,
                stage,
                skill,
                source_id,
                documents[source_id],
                path_a if source_id == document_a else path_b,
                target_id,
                documents[target_id],
                path_a if target_id == document_a else path_b,
                existing,
                output_path,
                checkpoint,
            )
            directions[(source_id, target_id)] = direction
            checkpoint(direction["matches"])

        self._validate_match_output(
            payload,
            dataset_name,
            stage,
            documents,
            require_complete=True,
        )
        print(f"[{dataset_name}] completed {stage['id']} in both directions")

    @staticmethod
    def _initial_match_output(
        dataset_name: str,
        stage: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "dataset_id": dataset_name,
            "stage_id": stage["id"],
            "candidate_view": stage["view"],
            "directions": [],
        }

    @staticmethod
    def _validate_match_output(
        payload: Any,
        dataset_name: str,
        stage: dict[str, Any],
        documents: dict[str, list[dict[str, Any]]],
        *,
        require_complete: bool = False,
    ) -> None:
        expected_fields = {
            "schema_version",
            "dataset_id",
            "stage_id",
            "candidate_view",
            "directions",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise ValueError(f"Match output must contain exactly {sorted(expected_fields)}")
        if payload["schema_version"] != 1:
            raise ValueError("Unsupported match schema version")
        if payload["dataset_id"] != dataset_name or payload["stage_id"] != stage["id"]:
            raise ValueError("Match output does not belong to this dataset and stage")
        if payload["candidate_view"] != stage["view"]:
            raise ValueError("Match output candidate view changed")
        if not isinstance(payload["directions"], list):
            raise ValueError("Match output directions must be an array")

        seen: set[tuple[str, str]] = set()
        for direction in payload["directions"]:
            if not isinstance(direction, dict) or set(direction) != {
                "source_document_id",
                "target_document_id",
                "matches",
            }:
                raise ValueError("Every direction needs source_document_id, target_document_id, matches")
            pair = (direction["source_document_id"], direction["target_document_id"])
            if pair in seen or pair[0] == pair[1] or any(item not in documents for item in pair):
                raise ValueError(f"Invalid or duplicate match direction: {pair}")
            seen.add(pair)
            source_ids = {
                candidate["unit_id"]
                for candidate in matching_candidates(documents[pair[0]], stage["view"])
            }
            target_ids = {
                candidate["unit_id"]
                for candidate in matching_candidates(documents[pair[1]], stage["view"])
            }
            validate_match_records(
                direction["matches"],
                source_ids,
                target_ids,
                require_coverage=require_complete,
            )
        if require_complete and len(seen) != 2:
            raise ValueError("A completed match output must contain both directions")

    def _match_direction(
        self,
        dataset_name: str,
        stage: dict[str, Any],
        skill: SkillRef | None,
        source_document_id: str,
        source_document: list[dict[str, Any]],
        source_path: Path,
        target_document_id: str,
        target_document: list[dict[str, Any]],
        target_path: Path,
        existing_matches: list[dict[str, Any]],
        output_path: Path,
        checkpoint: Callable[[list[dict[str, Any]]], None],
    ) -> tuple[dict[str, Any], SkillRef | None]:
        view: CandidateView = stage["view"]
        source_candidates = matching_candidates(source_document, view)
        target_candidates = matching_candidates(target_document, view)
        source_ids = {candidate["unit_id"] for candidate in source_candidates}
        target_ids = {candidate["unit_id"] for candidate in target_candidates}
        validate_match_records(
            existing_matches,
            source_ids,
            target_ids,
            require_coverage=False,
        )
        covered = {match["source_id"] for match in existing_matches}
        remaining = [candidate for candidate in source_candidates if candidate["unit_id"] not in covered]
        matches = list(existing_matches)
        batches = batch_candidates(remaining, stage.get("source_batch_size"))

        for batch_index, batch in enumerate(batches, start=1):
            if not batch:
                continue
            skill = skill or self._skill(stage)
            batch_matches, result = self._match_batch(
                dataset_name,
                stage,
                skill,
                source_document_id,
                batch,
                source_path,
                target_document_id,
                target_candidates,
                target_path,
                output_path,
                batch_index,
                len(batches),
            )
            matches.extend(batch_matches)
            validate_match_records(matches, source_ids, target_ids, require_coverage=False)
            checkpoint(matches)
            self._log(
                dataset_name,
                f"{stage['id']}:{source_document_id}-to-{target_document_id}:batch-{batch_index}",
                result,
                [skill],
                inputs=[source_path, target_path],
                outputs=[output_path],
                detail={"batch": f"{batch_index}/{len(batches)}"},
            )

        validate_match_records(matches, source_ids, target_ids)
        return ({
            "source_document_id": source_document_id,
            "target_document_id": target_document_id,
            "matches": matches,
        }, skill)

    def _match_batch(
        self,
        dataset_name: str,
        stage: dict[str, Any],
        skill: SkillRef,
        source_document_id: str,
        source_candidates: list[dict[str, Any]],
        source_path: Path,
        target_document_id: str,
        target_candidates: list[dict[str, Any]],
        target_path: Path,
        output_path: Path,
        batch_index: int,
        batch_count: int,
    ) -> tuple[list[dict[str, Any]], RunResult]:
        source_ids = {candidate["unit_id"] for candidate in source_candidates}
        target_ids = {candidate["unit_id"] for candidate in target_candidates}
        instructions = (
            "Use the attached matching Skill exactly as written for one directional pass. "
            "The harness has deterministically built the candidates. Judge every source candidate "
            "against the complete target pool. Multiple target records or one null record are valid. "
            "Return at least one record for every source_id."
        )
        prompt = (
            f"source_document_id: {source_document_id}\n"
            f"source_candidates:\n{json.dumps(source_candidates, ensure_ascii=False)}\n\n"
            f"target_document_id: {target_document_id}\n"
            f"target_candidates:\n{json.dumps(target_candidates, ensure_ascii=False)}"
        )
        schema = _match_schema()

        try:
            result = self._api().run_json(
                [skill],
                prompt,
                schema,
                policy=self._call_policy(stage),
                cacheable_prompt=instructions,
            )
        except Exception as error:
            self._log_error(
                dataset_name,
                f"{stage['id']}:{source_document_id}-to-{target_document_id}:batch-{batch_index}",
                error,
                {"batch": f"{batch_index}/{batch_count}"},
            )
            raise

        matches = result.value["matches"]
        try:
            validate_match_records(matches, source_ids, target_ids)
        except ValueError as error:
            rejected_path = output_path.with_name(
                f"{output_path.stem}.{source_document_id}-to-{target_document_id}."
                f"batch-{batch_index:02d}.rejected-{result.response_id}.json"
            )
            write_json(rejected_path, result.value)
            self._log(
                dataset_name,
                f"{stage['id']}:{source_document_id}-to-{target_document_id}:batch-{batch_index}:rejected",
                result,
                [skill],
                inputs=[source_path, target_path],
                outputs=[rejected_path],
                detail={
                    "batch": f"{batch_index}/{batch_count}",
                    "validation_error": str(error),
                },
            )
            raise
        return matches, result

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
