"""Strict paper loader that only accepts our skills pipeline's own output format.

`input_data.load_paper()` accepts two shapes and silently dispatches between them based
on whether a paper's JSON root is a list or a dict -- the extracted-sections format (a
list, matching our skills pipeline's `sections-with-paragraph-content(-no-appendices).json`
output) or the canonical `{paper_id, title, sections, paragraphs}` dict format (matching
the older lexical-tag-matching pipeline's own `<paper_id>.json` output elsewhere in this
repo). That flexibility exists so `incremental_graph` can consume papers already processed
by either pipeline in this codebase without a conversion step.

This module is for callers who only ever produce skills-pipeline output and would rather
have a stricter contract: a non-list JSON file is a real, clearly-worded error here, not a
silent fallback to a different parser. It does NOT reimplement any normalization logic --
it reuses `input_data._from_extracted_sections` directly, so paper/section/paragraph ID
generation, empty-content filtering, and the resulting `Paper`/`Section`/`Paragraph`
objects are byte-for-byte identical to what `input_data.load_paper` would produce for the
same file. This module only narrows what shapes are ACCEPTED -- it changes nothing about
how an accepted shape gets normalized.

Public interface mirrors `input_data.load_manifest`/`load_paper` exactly, so this is a
drop-in replacement everywhere those are used (e.g. `cli.py`'s `run_revision`) -- swap the
import, nothing else changes.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .input_data import InputError, _from_extracted_sections
from .models import Paper, PaperManifest


def load_manifest(path: Path) -> tuple[PaperManifest, list[Paper]]:
    path = path.resolve()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise InputError(f"Could not load paper manifest {path}: {error}") from error
    manifest = PaperManifest.model_validate(payload)
    papers = [
        load_paper((path.parent / entry.file).resolve(), entry.paper_id, entry.title)
        for entry in manifest.papers
    ]
    return manifest, papers


def load_paper(path: Path, paper_id: str, title: str) -> Paper:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InputError(f"Could not load paper JSON {path}: {error}") from error
    if not isinstance(payload, list):
        raise InputError(
            f"Paper JSON {path} must be a list of sections (the skills pipeline's own "
            "extracted-sections format: [{section_name, section_number, paragraphs}, ...]) "
            f"-- got a {type(payload).__name__}. This loader intentionally does not accept "
            "the canonical {paper_id, title, sections, paragraphs} format; use "
            "input_data.load_paper for that."
        )
    return _from_extracted_sections(payload, paper_id, title)
