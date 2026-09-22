"""Fresh HCI pair, then three individual additions under one observed-cost guard.

Uses the unchanged start/add/retry pipeline. Stops on failure; --retry explicitly
resumes an unfinished revision. The $3 reserve is not a provider-enforced cap.
"""

import argparse
import math
import tempfile
from pathlib import Path
from unittest.mock import patch

from helpers.usage_budget import ResponseLedger
from pipeline.files import read_json, write_json
from pipeline.incremental_graph.input_data import load_manifest
from pipeline.incremental_graph.runs import add_papers, retry_graph, start_graph
from pipeline.providers.anthropic import ClaudeSkills

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "datasets/hci-five-paper/content/sections.manifest.yaml"
RUN = ROOT / "runs/hci-section-fresh-20260917"
RESERVE_USD = 3.0


def run(budget_usd: float, *, retry: bool = False, run_dir: Path | None = None):
    run_dir = (run_dir if run_dir is not None else RUN).resolve()
    if not math.isfinite(budget_usd) or budget_usd <= RESERVE_USD:
        raise ValueError("Budget must be finite and exceed the $3 uncertainty reserve")
    manifest, papers = load_manifest(MANIFEST)
    if manifest.max_granularity != "section" or len(papers) != 5:
        raise ValueError("Expected five HCI papers at section granularity")
    if any(s.question or any(p.question for p in s.paragraphs) for d in papers for s in d.sections):
        raise ValueError("This experiment requires content-only inputs without old questions")
    if retry and not run_dir.exists():
        raise ValueError("There is no run to retry")
    if run_dir.exists():
        previous_budget = read_json(run_dir / "budget.json")
        if previous_budget["authorized_budget_usd"] != budget_usd:
            raise ValueError("Do not change this experiment's authorized budget during resume")
        if not previous_budget["last_call_usage_known"]:
            raise ValueError("Reconcile unreported usage before resuming")

    ledger = ResponseLedger(run_dir / "cache/responses")
    original = ClaudeSkills._run

    def bounded(client, *args, **kwargs):
        if client.model != "claude-sonnet-5":
            raise ValueError("Budget rates apply only to Sonnet 5")
        if client.response_dir.resolve() != ledger.directory.resolve():
            raise ValueError("Paid responses must be saved in this run's cost ledger")
        ledger.require_headroom(budget_usd, RESERVE_USD)
        before = len(ledger.seen)

        def save_budget(known):
            write_json(
                run_dir / "budget.json",
                {
                    "authorized_budget_usd": budget_usd,
                    "reserve_usd": RESERVE_USD,
                    "estimated_token_cost_usd": ledger.spent,
                    "recorded_responses": len(ledger.seen),
                    "last_call_usage_known": known,
                    "excludes": "tool fees and unreported usage; not a provider-enforced cap",
                },
            )

        # An interrupted request cannot silently become free on resume.
        save_budget(False)
        try:
            return original(client, *args, **kwargs)
        finally:
            ledger.refresh()
            save_budget(len(ledger.seen) > before)
            print(f"Recorded token cost: ${ledger.spent:.4f}", flush=True)

    with patch.object(ClaudeSkills, "_run", bounded), tempfile.TemporaryDirectory() as directory:
        if run_dir.exists():
            state = read_json(run_dir / "run.json")
            if state["latest_revision"] != state["current_revision"]:
                if not retry:
                    raise ValueError("Inspect the failure, then explicitly use --retry")
                retry_graph(run_dir)
                state = read_json(run_dir / "run.json")
            summary = read_json(run_dir / "revisions" / state["current_revision"] / "summary.json")
            completed = len(summary["paper_order"])
            if summary["paper_order"] != [p.paper_id for p in papers[:completed]]:
                raise ValueError("Saved paper order does not match this experiment")
        else:
            completed = 0
        while completed < len(papers):
            stop = 2 if completed == 0 else completed + 1
            request_path = Path(directory) / "manifest.json"
            write_json(
                request_path,
                {
                    "schema_version": 1,
                    "max_granularity": "section",
                    "papers": [
                        {
                            "paper_id": entry.paper_id,
                            "title": entry.title,
                            "file": str((MANIFEST.parent / entry.file).resolve()),
                        }
                        for entry in manifest.papers[completed:stop]
                    ],
                },
            )
            ledger.require_headroom(budget_usd, RESERVE_USD)
            print(
                f"Starting {'pair' if completed == 0 else 'addition'} through paper {stop}",
                flush=True,
            )
            summary = (
                start_graph(request_path, run_dir)
                if completed == 0
                else add_papers(request_path, run_dir)
            )
            completed = summary["paper_count"]
            print(f"Completed {completed}/5 papers; token cost ${ledger.spent:.4f}", flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget-usd", type=float, required=True)
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--run-dir", type=Path, default=RUN, help="Separate directory for this run")
    args = parser.parse_args()
    print(run(args.budget_usd, retry=args.retry, run_dir=args.run_dir))
