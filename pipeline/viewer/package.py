"""Validate and package one pipeline output directory for the static viewer."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

COMMON_ROOT_FILES = ("manifest.json",)
SNAPSHOT_FILE = "final_snapshot.json"
VIEWER_ASSETS = {
    "dist/app.js": "app.js",
    "styles.css": "styles.css",
}


class DatasetValidationError(ValueError):
    """Raised when a pipeline output cannot safely drive the viewer."""


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise DatasetValidationError(f"Missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatasetValidationError(f"Invalid JSON in {path}: {error}") from error


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DatasetValidationError(message)


def _validate_contract(name: str, value: Any) -> None:
    schema_path = Path(__file__).parent / "dist" / "contracts.json"
    _require(schema_path.is_file(), "Build viewer contracts first: npm run build:viewer")
    schemas = _read_json(schema_path)
    try:
        Draft202012Validator(schemas[name]).validate(value)
    except ValidationError as error:
        raise DatasetValidationError(
            f"{name} contract at {list(error.absolute_path)}: {error.message}"
        ) from error


def _validate_members(groups: list[dict[str, Any]], units: set[str], source: str) -> None:
    seen: set[str] = set()
    group_ids: set[str] = set()
    for group in groups:
        _require(group["group_id"] not in group_ids, f"{source} has duplicate group IDs")
        group_ids.add(group["group_id"])
        for member in group["members"]:
            key = f"{member['paper']}:{member['unit_id']}"
            _require(key in units, f"{source} references unknown unit {key}")
            _require(key not in seen, f"{source} assigns {key} more than once")
            seen.add(key)
    _require(seen == units, f"{source} does not account for every unit")


def validate_dataset(
    dataset_dir: Path,
    dataset_id: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Validate the viewer-facing contract and return its generated descriptor."""

    dataset_dir = dataset_dir.resolve()
    manifest = _read_json(dataset_dir / "manifest.json")
    _validate_contract("manifest", manifest)
    _require(
        isinstance(manifest, list) and manifest, "manifest.json must contain an ordered paper list"
    )

    paper_ids: list[str] = []
    paragraph_units: set[str] = set()
    section_units: set[str] = set()
    paragraph_count = 0
    for entry in manifest:
        paper_id = entry.get("paper_id")
        paper_file = entry.get("file")
        _require(bool(paper_id and paper_file), "Every manifest entry needs paper_id and file")
        _require(paper_id not in paper_ids, f"Duplicate paper_id in manifest: {paper_id}")
        paper = _read_json(dataset_dir / paper_file)
        _validate_contract("paper", paper)
        _require(
            paper.get("paper_id") == paper_id, f"{paper_file} does not match paper_id {paper_id}"
        )
        _require(isinstance(paper.get("sections"), list), f"{paper_file} has no sections list")
        _require(isinstance(paper.get("paragraphs"), list), f"{paper_file} has no paragraphs list")

        section_ids = {unit.get("id") for unit in paper["sections"]}
        paragraph_ids = {unit.get("id") for unit in paper["paragraphs"]}
        _require(
            None not in section_ids and len(section_ids) == len(paper["sections"]),
            f"{paper_file} has duplicate or missing section IDs",
        )
        _require(
            None not in paragraph_ids and len(paragraph_ids) == len(paper["paragraphs"]),
            f"{paper_file} has duplicate or missing paragraph IDs",
        )
        for section in paper["sections"]:
            _require("text" in section, f"{paper_file}:{section.get('id')} has no text field")
        for paragraph in paper["paragraphs"]:
            _require(
                bool(str(paragraph.get("text", "")).strip()),
                f"{paper_file}:{paragraph.get('id')} has no extracted text",
            )
            _require(
                paragraph.get("section_id") in section_ids,
                f"{paper_file}:{paragraph.get('id')} has an unknown section_id",
            )

        paper_ids.append(paper_id)
        section_units.update(f"{paper_id}:{unit_id}" for unit_id in section_ids)
        paragraph_units.update(f"{paper_id}:{unit_id}" for unit_id in paragraph_ids)
        paragraph_count += len(paragraph_ids)

    resolved_id = dataset_id or dataset_dir.name
    _require(
        bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", resolved_id)),
        "dataset_id must use lowercase letters, numbers, dashes, or underscores",
    )
    snapshot = _read_json(dataset_dir / SNAPSHOT_FILE)
    _validate_contract("snapshot", snapshot)
    shared_groups = snapshot.get("groups")
    singleton_groups = snapshot.get("singletons")
    section_groups = snapshot.get("section_groups")
    _require(
        snapshot.get("schema_version") == 1, f"{SNAPSHOT_FILE} has an unsupported schema version"
    )
    _require(snapshot.get("mode") == "final_snapshot", f"{SNAPSHOT_FILE} has an invalid mode")
    _require(isinstance(shared_groups, list), f"{SNAPSHOT_FILE} has no shared groups list")
    _require(isinstance(singleton_groups, list), f"{SNAPSHOT_FILE} has no singleton list")
    _require(isinstance(section_groups, list), f"{SNAPSHOT_FILE} has no section groups list")
    _validate_members(shared_groups + singleton_groups, paragraph_units, SNAPSHOT_FILE)
    _validate_members(section_groups, section_units, SNAPSHOT_FILE)

    for group in shared_groups:
        represented_papers = {member.get("paper") for member in group.get("members", [])}
        _require(
            len(represented_papers) >= 2,
            f"{SNAPSHOT_FILE} shared group {group.get('group_id')} represents fewer than two papers",
        )
    for group in singleton_groups:
        members = group.get("members", [])
        represented_papers = {member.get("paper") for member in members}
        _require(
            bool(members) and len(represented_papers) == 1,
            f"{SNAPSHOT_FILE} singleton {group.get('group_id')} must represent exactly one paper",
        )
    return {
        "schema_version": 1,
        "mode": "final_snapshot",
        "dataset_id": resolved_id,
        "label": label or resolved_id.replace("-", " ").replace("_", " ").title(),
        "paper_count": len(paper_ids),
        "paragraph_count": paragraph_count,
        "snapshot_file": SNAPSHOT_FILE,
        "stats": snapshot.get("stats") or {},
    }


def _require_empty_output(output_dir: Path) -> None:
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise DatasetValidationError(f"Output directory must be empty: {output_dir}")


def _copy_viewer(viewer_path: Path, public_dir: Path) -> None:
    assets = [(viewer_path, "index.html")] + [
        (viewer_path.parent / source, target) for source, target in VIEWER_ASSETS.items()
    ]
    for source, _ in assets:
        _require(source.is_file(), f"Missing viewer asset: {source}; run npm run build:viewer")
    public_dir.mkdir(parents=True, exist_ok=True)
    for source, target in assets:
        shutil.copy2(source, public_dir / target)


def _copy_dataset(
    dataset_dir: Path,
    data_dir: Path,
    descriptor: dict[str, Any],
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest = _read_json(dataset_dir / "manifest.json")
    filenames = COMMON_ROOT_FILES + tuple(entry["file"] for entry in manifest)
    for filename in filenames:
        shutil.copy2(dataset_dir / filename, data_dir / filename)
    shutil.copy2(dataset_dir / SNAPSHOT_FILE, data_dir / SNAPSHOT_FILE)
    (data_dir / "dataset.json").write_text(
        json.dumps(descriptor, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_site_config(output_dir: Path, package_name: str) -> None:
    (output_dir / "package.json").write_text(
        json.dumps(
            {"name": package_name, "private": True, "version": "1.0.0"},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "vercel.json").write_text(
        json.dumps(
            {
                "version": 2,
                "headers": [
                    {
                        "source": "/data/(.*)",
                        "headers": [
                            {"key": "Cache-Control", "value": "public, max-age=0, must-revalidate"}
                        ],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def package_dataset(
    dataset_dir: Path,
    output_dir: Path,
    viewer_path: Path,
    dataset_id: str,
    label: str,
) -> dict[str, Any]:
    """Create a minimal static Vercel site containing one validated dataset."""

    dataset_dir = dataset_dir.resolve()
    descriptor = validate_dataset(dataset_dir, dataset_id, label)
    _require_empty_output(output_dir)

    public_dir = output_dir / "public"
    data_dir = public_dir / "data"
    _copy_viewer(viewer_path, public_dir)
    _copy_dataset(dataset_dir, data_dir, descriptor)
    _write_site_config(output_dir, f"question-atlas-{dataset_id}")
    return descriptor


def package_study(
    datasets: dict[str, dict[str, Any]],
    output_dir: Path,
    viewer_path: Path,
) -> dict[str, Any]:
    """Package validated datasets behind a participant-ID routing gate."""

    _require(bool(datasets), "A study package needs at least one dataset")
    routes: dict[str, dict[str, str]] = {}
    descriptors: dict[str, dict[str, Any]] = {}
    prepared: list[tuple[str, Path, dict[str, Any]]] = []
    for dataset_id, settings in datasets.items():
        prefix = settings["participant_prefix"]
        label = settings["label"]
        _require(bool(re.fullmatch(r"[A-Z]{2}", prefix)), f"Invalid participant prefix: {prefix}")
        _require(prefix not in routes, f"Duplicate participant prefix: {prefix}")
        dataset_dir = Path(settings["dataset_dir"]).resolve()
        descriptor = validate_dataset(dataset_dir, dataset_id, label)
        routes[prefix] = {"dataset_id": dataset_id, "label": label}
        descriptors[dataset_id] = descriptor
        prepared.append((dataset_id, dataset_dir, descriptor))

    _require_empty_output(output_dir)
    public_dir = output_dir / "public"
    root_data_dir = public_dir / "data"
    _copy_viewer(viewer_path, public_dir)
    for dataset_id, dataset_dir, descriptor in prepared:
        _copy_dataset(dataset_dir, root_data_dir / dataset_id, descriptor)

    study = {
        "schema_version": 1,
        "mode": "participant_routing",
        "participant_number_digits": 3,
        "datasets": routes,
    }
    root_data_dir.mkdir(parents=True, exist_ok=True)
    (root_data_dir / "study.json").write_text(
        json.dumps(study, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_site_config(output_dir, "question-atlas-user-study")
    return {"study": study, "datasets": descriptors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--viewer",
        type=Path,
        default=Path(__file__).resolve().parent / "index.html",
    )
    args = parser.parse_args()
    descriptor = package_dataset(
        args.dataset_dir, args.output_dir, args.viewer, args.dataset_id, args.label
    )
    print(
        f"Packaged {descriptor['label']}: {descriptor['paper_count']} papers, "
        f"{descriptor['paragraph_count']} paragraphs, final snapshot"
    )


if __name__ == "__main__":
    main()
