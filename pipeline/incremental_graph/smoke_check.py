"""Check the deliberately small Jev fixture's expected memberships, without API calls."""

import argparse
import json
from pathlib import Path

from .compare import load_revision


def check_smoke(path: Path) -> dict:
    run = load_revision(path)
    if set(run["papers"]) != {"water", "warning"} or run["summary"]["max_granularity"] != "section":
        raise ValueError("Expected the two-document datasets/jev-smoke manifest in section mode")
    actual = {
        level: sorted(sorted(node["source_members"]) for node in run["groups"][level])
        for level in ("section", "paragraph")
    }
    expected = {
        "section": sorted([["warning:s0001", "water:s0001"], ["warning:s0002"], ["water:s0002"]]),
        "paragraph": sorted(
            [
                ["warning:s0001.p0001", "water:s0001.p0001"],
                ["warning:s0002.p0001"],
                ["water:s0002.p0001"],
            ]
        ),
    }
    passed = actual == expected
    return {
        "passed": passed,
        "revision": run["path"],
        "expected": expected,
        "actual": actual,
        "selector": "jev" if run["settings"]["jev"] else "llm",
        "note": "Synthetic smoke check only; a pass is not a corpus-quality evaluation.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    result = check_smoke(args.run)
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
