"""Minimal dotenv loading without exposing provider secrets to the browser."""
from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_upwards(start: Path) -> list[Path]:
    loaded: list[Path] = []
    for directory in (start.resolve(), *start.resolve().parents):
        path = directory / ".env"
        if not path.is_file():
            continue
        loaded.append(path)
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if value[:1] == value[-1:] and value.startswith(("'", '"')):
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)
    return loaded
