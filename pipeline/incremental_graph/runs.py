"""Start, extend, or retry an ordered graph using immutable prepared inputs.

Appending recomputes finalized structure and paragraph scope in insertion order.
Content-addressed judgment caching reuses unchanged decisions; it is not an
in-place append to already-finalized paragraph nodes.
"""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field

from ..files import directory_hash, read_json, write_json
from ..providers.jev import JevSettings
from ..providers.registry import load_api_key
from ..providers.settings import ModelSettings
from .configuration import PromptRepository, load_pipeline_config
from .input_data import load_manifest
from .judgments import CachedJudgments
from .models import Granularity, PaperManifest, PipelineConfig, SchemaVersion, StrictModel
from .runner import IncrementalGraphRunner

DEFAULT_CONFIG = Path(__file__).parent / "configs/incremental-v1.yaml"
RevisionId = Annotated[str, Field(pattern=r"^revision-[0-9]{4,}$")]


class RunState(StrictModel):
    schema_version: SchemaVersion = 1
    mode: Literal["ordered_graph"] = "ordered_graph"
    config: PipelineConfig
    max_granularity: Granularity
    policy_sha256: str
    revision_count: int = Field(default=0, ge=0)
    current_revision: RevisionId | None = None
    latest_revision: RevisionId | None = None
    input_sha256: dict[RevisionId, str] = Field(default_factory=dict)


def _policy_hash(config: PipelineConfig) -> str:
    pipeline = Path(__file__).resolve().parents[1]
    source_files = [
        *Path(__file__).parent.glob("*.py"),
        pipeline / "document.py",
        pipeline / "files.py",
        *(pipeline / "providers").glob("*.py"),
    ]
    assets = {
        "config": config.model_dump(mode="json"),
        "code": {
            path.relative_to(pipeline).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(source_files)
        },
        "dependencies": {
            name: version(name)
            for name in (config.model.provider, "networkx", "pydantic", "PyYAML", "jsonschema")
        },
        "prompts": directory_hash(config.prompt_root),
        "contexts": directory_hash(config.context_root),
        "skills": {
            name: directory_hash(config.skill_root / name)
            for name in sorted({stage.skill for stage in config.stages if stage.skill})
        },
    }
    return hashlib.sha256(json.dumps(assets, sort_keys=True).encode()).hexdigest()


def _inputs(path: Path) -> tuple[PaperManifest, list[Any]]:
    manifest, _ = load_manifest(path)
    return manifest, [read_json(path.resolve().parent / entry.file) for entry in manifest.papers]


def _state(run_dir: Path) -> RunState:
    state = RunState.model_validate(read_json(run_dir / "run.json"))
    if state.policy_sha256 != _policy_hash(state.config):
        raise ValueError(
            "Graph code, prompts, or Skills changed; start a new run instead of mixing policies"
        )
    return state


def _saved_inputs(run_dir: Path, state: RunState, revision: str) -> tuple[PaperManifest, list[Any]]:
    input_dir = run_dir / "inputs" / revision
    if state.input_sha256.get(revision) != directory_hash(input_dir):
        raise ValueError("Saved inputs changed; do not mix edited documents into an existing run")
    return _inputs(input_dir / "manifest.yaml")


def start_graph(
    manifest_path: Path,
    run_dir: Path,
    config_path: Path = DEFAULT_CONFIG,
    *,
    provider: str | None = None,
    model: str | None = None,
    jev: bool = False,
    jev_model: str | None = None,
    jev_max_calls: int | None = None,
    max_api_responses: int | None = None,
) -> dict[str, Any]:
    if (provider is None) != (model is None):
        raise ValueError("Pass provider and model together, or use the saved configuration")
    manifest, documents = _inputs(manifest_path)
    if len(manifest.papers) < 2:
        raise ValueError("A new graph requires at least two prepared papers")
    config = load_pipeline_config(config_path)
    if (jev_model is not None or jev_max_calls is not None) and not (jev or config.jev):
        raise ValueError("Jev overrides require --jev or a Jev configuration")
    if jev or config.jev:
        settings = config.jev or JevSettings()
        overrides = {}
        if jev_model is not None:
            overrides["model"] = jev_model
        if jev_max_calls is not None:
            overrides["max_calls"] = jev_max_calls
        config.jev = JevSettings.model_validate({**settings.model_dump(), **overrides})
    if provider is not None:
        config.model = ModelSettings.model_validate(
            {
                **config.model.model_dump(),
                "provider": provider,
                "name": model,
            }
        )
    if max_api_responses is not None:
        config.model = ModelSettings.model_validate(
            {**config.model.model_dump(), "max_api_responses_per_process": max_api_responses}
        )
    if config.jev:
        # Fail before buying question generation or creating a run with missing credentials.
        load_api_key(config.skill_root.parent, "TYPESAFE_API_KEY")
        load_api_key(config.skill_root.parent, f"{config.model.provider.upper()}_API_KEY")
    state = RunState(
        config=config, max_granularity=manifest.max_granularity, policy_sha256=_policy_hash(config)
    )
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    return _execute(run_dir, state, manifest, documents)


def add_papers(manifest_path: Path, run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    state = _state(run_dir)
    if state.latest_revision != state.current_revision or state.current_revision is None:
        raise ValueError("Retry the unfinished revision before adding papers")
    previous, documents = _saved_inputs(run_dir, state, state.current_revision)
    incoming, added = _inputs(manifest_path)
    if incoming.max_granularity != state.max_granularity:
        raise ValueError("Added papers must use the graph's existing max_granularity")
    duplicates = {entry.paper_id for entry in previous.papers} & {
        entry.paper_id for entry in incoming.papers
    }
    if duplicates:
        raise ValueError(f"Papers already present: {sorted(duplicates)}")
    combined = PaperManifest(
        max_granularity=state.max_granularity, papers=[*previous.papers, *incoming.papers]
    )
    return _execute(run_dir, state, combined, [*documents, *added])


def retry_graph(
    run_dir: Path, *, paper_index: int | None = None, stage_id: str | None = None
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    state = _state(run_dir)
    if state.latest_revision is None:
        raise ValueError("There is no revision to retry")
    manifest, documents = _saved_inputs(run_dir, state, state.latest_revision)
    if (paper_index is None) != (stage_id is None):
        raise ValueError("Provide both paper index and stage, or neither")
    if paper_index is not None and not 1 <= paper_index <= len(manifest.papers):
        raise ValueError("Paper index is outside the saved input sequence")
    if stage_id is not None and stage_id not in {stage.id for stage in state.config.stages}:
        raise ValueError(f"Unknown stage: {stage_id}")
    return _execute(run_dir, state, manifest, documents, paper_index, stage_id)


def _execute(
    run_dir: Path,
    state: RunState,
    manifest: PaperManifest,
    documents: list[Any],
    force_paper_index: int | None = None,
    force_stage_id: str | None = None,
) -> dict[str, Any]:
    state.revision_count += 1
    revision = f"revision-{state.revision_count:04d}"
    input_dir = run_dir / "inputs" / revision
    input_dir.mkdir(parents=True, exist_ok=False)
    entries = []
    for index, (entry, document) in enumerate(zip(manifest.papers, documents, strict=True), 1):
        filename = f"paper-{index:04d}.json"
        write_json(input_dir / filename, document)
        entries.append({"paper_id": entry.paper_id, "title": entry.title, "file": filename})
    frozen_manifest = input_dir / "manifest.yaml"
    frozen_manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "max_granularity": state.max_granularity,
                "papers": entries,
            },
            sort_keys=False,
        ),
        encoding="utf8",
    )
    state.latest_revision = revision
    state.input_sha256[revision] = directory_hash(input_dir)
    write_json(run_dir / "run.json", state.model_dump(mode="json"))
    _, papers = load_manifest(frozen_manifest)
    config = state.config
    judge = CachedJudgments(
        PromptRepository(config.prompt_root, config.context_root),
        config.model,
        run_dir / "cache",
        config.skill_root,
        jev=config.jev,
    )
    revision_dir = run_dir / "revisions" / revision
    runner = IncrementalGraphRunner(
        config,
        judge,
        revision_dir,
        max_granularity=state.max_granularity,
        force_paper_index=force_paper_index,
        force_stage_id=force_stage_id,
    )
    try:
        summary = runner.run(papers)
    except Exception as error:
        write_json(
            revision_dir / "failure.json", {"type": type(error).__name__, "message": str(error)}
        )
        raise
    state.current_revision = revision
    write_json(run_dir / "run.json", state.model_dump(mode="json"))
    return summary
