"""Runtime paths shared by the active question-mapping pipeline."""
from __future__ import annotations

import os
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
REPO_DIR = PIPELINE_DIR.parent


def papers_dir() -> Path:
    return Path(os.environ.get("SME_PAPERS_DIR", REPO_DIR / "papers")).resolve()


def output_dir() -> Path:
    return Path(
        os.environ.get("SME_OUTPUT_DIR", PIPELINE_DIR / "output" / "sections")
    ).resolve()
