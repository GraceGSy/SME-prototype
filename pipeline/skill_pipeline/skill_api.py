"""Small Anthropic Skills API adapter with local version and run provenance."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SKILL_BETAS = ["skills-2025-10-02"]
MESSAGE_BETAS = [
    "code-execution-2025-08-25",
    "skills-2025-10-02",
    "files-api-2025-04-14",
    "structured-outputs-2025-11-13",
]
FILE_BETAS = ["files-api-2025-04-14"]
CODE_EXECUTION_TOOL = {"type": "code_execution_20250825", "name": "code_execution"}


@dataclass(frozen=True)
class SkillRef:
    path: str
    skill_id: str
    version: str
    source_sha256: str

    def api_value(self) -> dict[str, str]:
        return {"type": "custom", "skill_id": self.skill_id, "version": self.version}


@dataclass(frozen=True)
class RunResult:
    response_id: str
    stop_reason: str
    usage: dict[str, Any]
    container_id: str | None
    value: Any = None
    raw_text: str | None = None
    transport_notes: tuple[str, ...] = ()


def _decode_json_output(text: str) -> tuple[Any, tuple[str, ...]]:
    """Decode one JSON value, or merge split matching wrappers in response order."""
    decoder = json.JSONDecoder()
    values: list[Any] = []
    position = 0
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position == len(text):
            break
        value, position = decoder.raw_decode(text, position)
        values.append(value)

    if len(values) == 1:
        return values[0], ()
    if len(values) > 1 and all(
        isinstance(value, dict) and set(value) == {"matches"} and isinstance(value["matches"], list)
        for value in values
    ):
        matches = [match for value in values for match in value["matches"]]
        return {"matches": matches}, (f"merged {len(values)} structured matching values",)
    raise ValueError(f"Expected one structured JSON value, received {len(values)}")


def load_api_key(repo_root: Path) -> str:
    """Load the API key without copying it into pipeline output or logs."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key

    for directory in [repo_root, *repo_root.parents]:
        env_path = directory / ".env"
        if not env_path.exists():
            continue
        values: dict[str, str] = {}
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip("\"'")
        key = values.get("ANTHROPIC_API_KEY")
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
            return key
    raise RuntimeError("No ANTHROPIC_API_KEY was found in the environment or an ancestor .env")


def _directory_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file() or "__pycache__" in file_path.parts or file_path.suffix == ".pyc":
            continue
        relative = file_path.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


class ClaudeSkills:
    def __init__(self, repo_root: Path, state_path: Path, model: str) -> None:
        from anthropic import Anthropic

        self.repo_root = repo_root
        self.state_path = state_path
        self.model = model
        self.client = Anthropic(api_key=load_api_key(repo_root))
        self.state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    def register(self, skill_path: Path) -> SkillRef:
        from anthropic.lib import files_from_dir

        skill_path = skill_path.resolve()
        relative = skill_path.relative_to(self.repo_root).as_posix()
        fingerprint = _directory_hash(skill_path)
        existing = self.state.get(relative)
        if existing and existing.get("source_sha256") == fingerprint:
            return SkillRef(relative, existing["skill_id"], existing["version"], fingerprint)

        files = files_from_dir(skill_path)
        if existing:
            try:
                response = self.client.beta.skills.versions.create(
                    existing["skill_id"], files=files, betas=SKILL_BETAS
                )
                skill_id = existing["skill_id"]
                version = response.version
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise
                response = self.client.beta.skills.create(files=files, betas=SKILL_BETAS)
                skill_id = response.id
                version = response.latest_version
        else:
            response = self.client.beta.skills.create(files=files, betas=SKILL_BETAS)
            skill_id = response.id
            version = response.latest_version
        if not version:
            raise RuntimeError(f"Skills API did not return a version for {relative}")

        self.state[relative] = {
            "skill_id": skill_id,
            "version": version,
            "source_sha256": fingerprint,
        }
        _atomic_json(self.state_path, self.state)
        return SkillRef(relative, skill_id, version, fingerprint)

    def run_json(
        self,
        skills: Iterable[SkillRef],
        prompt: str,
        schema: dict[str, Any],
        *,
        max_tokens: int,
    ) -> RunResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        response = self._run(skills, messages, max_tokens=max_tokens, schema=schema)
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        if not text.strip():
            raise RuntimeError(f"Claude response {response.id} contained no structured text output")
        value, notes = _decode_json_output(text)
        return self._result(response, value, raw_text=text, transport_notes=notes)

    def run_file(
        self,
        skill: SkillRef,
        prompt: str,
        input_path: Path,
        expected_filename: str,
        *,
        max_tokens: int = 2048,
    ) -> tuple[RunResult, bytes]:
        uploaded = self.client.beta.files.upload(file=input_path, betas=FILE_BETAS)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "container_upload", "file_id": uploaded.id},
                ],
            }
        ]
        response = self._run([skill], messages, max_tokens=max_tokens)
        for file_id in self._file_ids(response):
            metadata = self.client.beta.files.retrieve_metadata(file_id=file_id, betas=FILE_BETAS)
            if metadata.filename != expected_filename:
                continue
            download = self.client.beta.files.download(file_id=file_id, betas=FILE_BETAS)
            data = download.read() if hasattr(download, "read") else download.content
            return self._result(response), data
        raise RuntimeError(
            f"Claude response {response.id} did not expose the expected generated file {expected_filename!r}"
        )

    def _run(
        self,
        skills: Iterable[SkillRef],
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        schema: dict[str, Any] | None = None,
    ) -> Any:
        skill_values = [skill.api_value() for skill in skills]
        container: dict[str, Any] = {"skills": skill_values}
        for _ in range(10):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "betas": MESSAGE_BETAS,
                "container": container,
                "messages": messages,
                "tools": [CODE_EXECUTION_TOOL],
            }
            if schema is not None:
                kwargs["output_config"] = {
                    "format": {"type": "json_schema", "schema": schema},
                    "effort": "medium",
                }
            response = self.client.beta.messages.create(**kwargs)
            if response.stop_reason != "pause_turn":
                if response.stop_reason not in {"end_turn", "stop_sequence"}:
                    raise RuntimeError(f"Claude response {response.id} stopped with {response.stop_reason}")
                return response
            messages.append({"role": "assistant", "content": response.content})
            container = {"id": response.container.id, "skills": skill_values}
        raise RuntimeError("Claude Skill run exceeded ten pause_turn continuations")

    @staticmethod
    def _file_ids(response: Any) -> list[str]:
        payload = response.model_dump(mode="json")
        found: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                file_id = value.get("file_id")
                if isinstance(file_id, str) and file_id not in found:
                    found.append(file_id)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload.get("content", []))
        return found

    @staticmethod
    def _result(
        response: Any,
        value: Any = None,
        *,
        raw_text: str | None = None,
        transport_notes: tuple[str, ...] = (),
    ) -> RunResult:
        container_id = getattr(getattr(response, "container", None), "id", None)
        usage = response.usage.model_dump(mode="json") if response.usage else {}
        return RunResult(
            response.id,
            response.stop_reason,
            usage,
            container_id,
            value,
            raw_text,
            transport_notes,
        )
