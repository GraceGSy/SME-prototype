"""Build the public run selector. Redact source text except in approved snapshots."""

import argparse
from pathlib import Path

from ..files import read_json, write_json
from .package import _copy_viewer, _require_empty_output, _write_site_config, validate_dataset
from .server import VIEWER, RunCatalog

# The publication list is explicit: discovering a new local run does not authorize publishing it.
LABELS = {
    "hci-five-paper-fan-in-v2-20261118": "HCI | 5 papers | Jev: section fan-in | Nov 18",
    "hci-three-paper-fan-in-20261118": "HCI | 3 papers | Jev: section fan-in experiment | Nov 18",
    "hci-three-paper-roles-v2-20261117": "HCI | 3 papers | Jev: yes/no filter then ranking, new roles | Nov 17",
    "hci-three-paper-section-nodes-20261115": "HCI | 3 papers | Jev: section nodes, pairwise from paper 3 | Nov 15",
    "hci-first-three-jev-singletons-20261105-verified": "HCI | 3 papers | Jev: revised paragraph matching | Nov 5",
    "reuters-technology-jev-singletons-20261105": "Reuters | 5 articles | Run 2: revised paragraph matching | Nov 5",
    "reuters-technology-jev-20261105": "Reuters | 5 articles | Run 1: original matching | Nov 5",
    "hci-first-two-jev-uncapped-20261025-01": "HCI | 2 papers | Jev: uncapped run | Oct 25",
    "hci-first-two-jev-20261025-01": "HCI | 2 papers | Jev: original run | Oct 25",
    "hci-section-medium-excerpts-20260917": "HCI | 2 to 5 papers | Claude: section matching | Sep 17",
    "hci-concise-fresh-20260907": "HCI | 2 to 5 papers | Claude: subsection matching | Sep 7",
    "hci-first-three-content-20260907": "HCI | 3 papers | Earlier three-paper run | Sep 7",
    "hci-first-two-content-20260907-rescued": "HCI | 2 papers | Recovered two-paper run | Sep 7",
    "legal-opinions-first-pair-20260910": "Legal | 2 opinions | Subsection matching | Sep 10",
    "legal-opinions-section-pair-20260910": "Legal | 2 opinions | Section matching: baseline | Sep 10",
    "legal-opinions-section-fewshot-pair-20260910": "Legal | 2 opinions | Section matching: with examples | Sep 10",
    "legal-opinions-paragraph-fewshot-pair-20260910": "Legal | 2 opinions | Paragraph matching: with examples | Sep 10",
    "jev-smoke-20261025-small-01": "Synthetic | 2 examples | Jev verification test | Oct 25",
}

# Only these frozen snapshots may publish the supplied Reuters articles.
SOURCE_TEXT_SNAPSHOTS = {
    ("reuters-technology-jev-singletons-20261105", "revision-0001"),
    ("reuters-technology-jev-20261105", "revision-0001"),
}


def package_catalog(runs: Path, output: Path, labels: dict[str, str] = LABELS) -> list[dict]:
    _require_empty_output(output)
    public = output / "public"
    _copy_viewer(VIEWER / "index.html", public)
    catalog = RunCatalog(runs)
    entries = []
    redacted = "Source text is not included in this results viewer."
    for entry in catalog.entries(include_checkpoints=True):
        key = entry["id"]
        if key not in labels:
            continue
        label = labels[key]
        entry.update(label=label, collection=label.split(" | ")[0], revisionLabels={})
        for rev in entry.get("sectionRevisions", []):
            # A section checkpoint has no paragraph dataset; publish its section map.
            if (key, rev) in SOURCE_TEXT_SNAPSHOTS:
                raise ValueError("Source-text approval covers completed snapshots only")
            section_map = catalog.section_map(key, rev)
            for paper in section_map["papers"]:
                for unit in paper["sections"] + paper["paragraphs"]:
                    unit["text"] = redacted
            write_json(public / "runs" / key / rev / "section-map.json", section_map)
            entry["revisionLabels"][rev] = (
                f"Revision {int(rev.split('-')[1])} | {len(section_map['papers'])} documents | "
                "sections only"
            )
        for rev in entry["revisions"]:
            if rev in entry.get("sectionRevisions", []):
                continue
            src = catalog.dataset(key, rev)
            validate_dataset(src)
            dst = public / "runs" / key / rev
            manifest = read_json(src / "manifest.json")
            snapshot = read_json(src / "final_snapshot.json")
            include_source = (key, rev) in SOURCE_TEXT_SNAPSHOTS
            if include_source:
                entry.setdefault("sourceTextRevisions", []).append(rev)
            write_json(dst / "manifest.json", manifest)
            write_json(dst / "final_snapshot.json", snapshot)
            for paper in manifest:
                doc = read_json(src / paper["file"])
                if not include_source:
                    for unit in doc["sections"] + doc["paragraphs"]:
                        unit["text"] = redacted
                write_json(dst / paper["file"], doc)
            descriptor = validate_dataset(dst, key, label)
            write_json(dst / "dataset.json", descriptor)
            entry["revisionLabels"][rev] = (
                f"Revision {int(rev.split('-')[1])} | {len(manifest)} documents | "
                f"{descriptor['paragraph_count']} paragraphs"
            )
        entries.append(entry)
    if not entries:
        raise ValueError("No selected completed runs found")
    write_json(public / "local.json", entries)
    index = public / "index.html"
    html = index.read_text(encoding="utf-8")
    index.write_text(
        html.replace('<html lang="en">', '<html lang="en" data-public-catalog>'), encoding="utf-8"
    )
    _write_site_config(output, "question-atlas-runs")
    return entries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    entries = package_catalog(args.runs, args.output)
    print(
        f"Packaged {len(entries)} runs and {sum(len(e['revisions']) for e in entries)} snapshots."
    )
