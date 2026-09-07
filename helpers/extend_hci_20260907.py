"""Append Examplore to the rescued HCI pair; default is a no-API replay check."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from helpers.recover_hci_20260907 import ROOT, RecoveryProvider, ReplayComplete
from pipeline.files import directory_hash, read_json, write_json
from pipeline.incremental_graph.configuration import PromptRepository
from pipeline.incremental_graph.input_data import load_manifest
from pipeline.incremental_graph.llm import AnthropicJudgmentProvider
from pipeline.incremental_graph.runner import IncrementalGraphRunner
from pipeline.incremental_graph.runs import RunState

PAIR = ROOT / "runs/hci-first-two-content-20260907-rescued"
OUTPUT = ROOT / "runs/hci-first-three-content-20260907"


def run(execute=False):
    state = RunState.model_validate(
        read_json(ROOT / "runs/hci-first-two-content-20260907/run.json")
    )
    for stage in state.config.stages:
        if stage.id == "paragraph_matching":
            stage.max_tokens = 1024
    manifest, papers = load_manifest(PAIR / "inputs/manifest.yaml")
    _, incoming = load_manifest(ROOT / "datasets/hci-five-paper/content/manifest.yaml")
    papers.append(incoming[2])
    if [paper.paper_id for paper in papers] != [
        "abstractexplorer",
        "corpusstudio",
        "examplore_chi18",
    ]:
        raise ValueError("Expected the existing pair followed by Examplore")
    source = PAIR / "revisions/revision-0003"
    records = {
        row["request_key"]: row
        for row in (
            json.loads(line)
            for line in (source / "provenance/attempts.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
    }
    if len(records) != 471:
        raise ValueError("Expected 471 completed pair judgments")
    with tempfile.TemporaryDirectory() as temporary:
        output = OUTPUT if execute else Path(temporary)
        output.mkdir(parents=True, exist_ok=True)
        if execute:
            inputs = output / "inputs"
            expected = {
                "pair": directory_hash(PAIR / "inputs"),
                "third": directory_hash(ROOT / "datasets/hci-five-paper/content"),
            }
            if not inputs.exists():
                shutil.copytree(PAIR / "inputs", inputs / "pair")
                shutil.copyfile(
                    ROOT / "datasets/hci-five-paper/content/examplore_chi18.content.json",
                    inputs / "examplore_chi18.content.json",
                )
                write_json(output / "source-hashes.json", expected)
            elif read_json(output / "source-hashes.json") != expected:
                raise ValueError("Source inputs changed")
        revisions = sorted((output / "revisions").glob("revision-*"))
        revision = output / "revisions" / f"revision-{len(revisions) + 1:04d}"
        live = AnthropicJudgmentProvider(
            PromptRepository(state.config.prompt_root, state.config.context_root),
            state.config.model,
            output / "cache",
            state.config.skill_root,
        )
        judge = RecoveryProvider(live, records, {}, output, execute=execute)
        runner = IncrementalGraphRunner(
            state.config, judge, revision, max_granularity=manifest.max_granularity
        )
        try:
            summary = runner.run(papers)
        except ReplayComplete as boundary:
            if judge.reused != 471:
                raise ValueError("The original pair was not fully preserved") from boundary
            print(f"Verified all 471 pair judgments. First new request: {boundary}")
        except Exception as error:
            write_json(
                revision / "failure.json", {"type": type(error).__name__, "message": str(error)}
            )
            raise
        else:
            write_json(
                revision / "extension.json",
                {"source_revision": str(source), "reused_pair_judgments": judge.reused},
            )
            print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    run(parser.parse_args().execute)
