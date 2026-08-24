"""Package SME dataset pairs as one counterbalanced participant-study site."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from viewer_dataset import DatasetValidationError, package_dataset


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def build_study(
    sme1_dir: Path,
    sme2_dir: Path,
    output_dir: Path,
    viewer_path: Path,
    shell_path: Path,
    title: str = "Viz SME Study",
    hci_sme1_dir: Path | None = None,
    hci_sme2_dir: Path | None = None,
) -> dict[str, Any]:
    """Build a static site whose participant-ID prefix selects a dataset order."""

    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise DatasetValidationError(f"Output directory must be empty: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    public_dir = output_dir / "public"
    public_dir.mkdir()

    phase_specs = [
        ("sme1", sme1_dir.resolve(), "Viz SME 1 Viewer"),
        ("sme2", sme2_dir.resolve(), "Viz SME 2 Viewer"),
    ]
    if (hci_sme1_dir is None) != (hci_sme2_dir is None):
        raise DatasetValidationError("Both HCI SME dataset directories must be provided together")
    if hci_sme1_dir is not None and hci_sme2_dir is not None:
        phase_specs.extend([
            ("hci_sme1", hci_sme1_dir.resolve(), "HCI SME 1 Viewer"),
            ("hci_sme2", hci_sme2_dir.resolve(), "HCI SME 2 Viewer"),
        ])
    descriptors: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        for phase_key, dataset_dir, label in phase_specs:
            packaged = temporary_root / phase_key
            descriptors[phase_key] = package_dataset(
                dataset_dir,
                packaged,
                viewer_path,
                phase_key,
                label,
            )
            shutil.copytree(packaged / "public", public_dir / phase_key)

    shutil.copy2(shell_path, public_dir / "index.html")
    orders = {
        "1": ["sme1", "sme2"],
        "2": ["sme2", "sme1"],
    }
    if hci_sme1_dir is not None:
        orders.update({
            "3": ["hci_sme1", "hci_sme2"],
            "4": ["hci_sme2", "hci_sme1"],
        })

    config = {
        "schema_version": 1,
        "study_id": "sme-counterbalanced" if hci_sme1_dir is not None else "viz-sme-counterbalanced",
        "title": title,
        "orders": orders,
        "phases": {
            phase_key: {
                "label": label,
                "viewer_path": f"{phase_key}/viz/tag_matches_viewer.html",
                "dataset": descriptors[phase_key],
            }
            for phase_key, _, label in phase_specs
        },
    }
    write_json(public_dir / "study-config.json", config)
    write_json(output_dir / "package.json", {
        "name": "question-atlas-viz-study",
        "private": True,
        "version": "1.0.0",
    })
    data_headers = [
        {
            "source": f"/{phase_key}/data/(.*)",
            "headers": [{"key": "Cache-Control", "value": "public, max-age=0, must-revalidate"}],
        }
        for phase_key, _, _ in phase_specs
    ]
    write_json(output_dir / "vercel.json", {
        "version": 2,
        "headers": [
            {
                "source": "/study-config.json",
                "headers": [{"key": "Cache-Control", "value": "public, max-age=0, must-revalidate"}],
            },
            *data_headers,
        ],
    })
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sme1_dir", type=Path)
    parser.add_argument("sme2_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--title", default="Viz SME Study")
    parser.add_argument("--hci-sme1-dir", type=Path)
    parser.add_argument("--hci-sme2-dir", type=Path)
    parser.add_argument(
        "--viewer",
        type=Path,
        default=Path(__file__).resolve().parent / "viz" / "tag_matches_viewer.html",
    )
    parser.add_argument(
        "--shell",
        type=Path,
        default=Path(__file__).resolve().parent / "viz" / "counterbalanced_study.html",
    )
    args = parser.parse_args()
    config = build_study(
        args.sme1_dir,
        args.sme2_dir,
        args.output_dir,
        args.viewer.resolve(),
        args.shell.resolve(),
        args.title,
        args.hci_sme1_dir,
        args.hci_sme2_dir,
    )
    summaries = [
        f"{key}: {phase['dataset']['paper_count']} papers, {phase['dataset']['paragraph_count']} paragraphs"
        for key, phase in config["phases"].items()
    ]
    print(f"Packaged {config['title']} ({'; '.join(summaries)})")


if __name__ == "__main__":
    main()
