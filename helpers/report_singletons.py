"""Report a saved revision's singleton outcomes without modifying it or calling an API.

python -m helpers.report_singletons EVENTS_JSON OUTPUT_DIR
The output directory must not exist. Historical runs are read, not migrated.
"""

import argparse
from pathlib import Path

from pipeline.files import read_json
from pipeline.incremental_graph.singleton_report import write_singleton_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events_json", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    report = write_singleton_report(read_json(args.events_json), args.output_dir)
    print(
        f"Wrote {report['singleton_paragraph_count']} singleton explanations to {args.output_dir}"
    )


if __name__ == "__main__":
    main()
