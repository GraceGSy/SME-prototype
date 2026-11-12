"""Read-only indexes over existing journals and provider receipts; never call a model."""

import hashlib
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from ..files import read_json
from ..incremental_graph.graph import graph_from_events
from ..providers.jev import encode_request


def inside(root, path):
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Trace path outside selected directory")
    return path


def journal(revision, name):
    path = inside(revision, revision / "provenance" / (name + ".jsonl"))
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        # An active run may still be appending the final line.
        rows = []
        for line in stream:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                if line.endswith("\n"):
                    raise
        return rows


def refs(event):
    return [v for k, v in event.items() if k.endswith("attempt_id") and v]


def event_subject(e):
    return next(
        (e[k] for k in ("title", "node_id", "source_id", "target_node_id", "source") if e.get(k)),
        "",
    )


class Trace:
    def __init__(self, run, rev):
        self.run = run
        self.revision = inside(run, run / "revisions" / rev)
        self.attempts = {a["attempt_id"]: a for a in journal(self.revision, "attempts")}
        self.events = journal(self.revision, "events")
        fallback = inside(self.revision, self.revision / "events.json")
        if not self.events and fallback.is_file():
            self.events = read_json(fallback)
        self.by_event = {e["event_id"]: i for i, e in enumerate(self.events)}
        self.effects = defaultdict(list)
        self.explanations = set()
        for e in self.events:
            for key in refs(e):
                self.effects[key].append(e)
            if e.get("explanation_attempt_id"):
                self.explanations.add(e["explanation_attempt_id"])
        self.files = {}
        self.by_identity = defaultdict(list)
        self.archive = []
        self.uses = defaultdict(list)
        self.rejected = {}
        for p in inside(run, run / "cache/rejected").glob("*.json"):
            rejected = read_json(inside(run, p))
            rid = rejected.get("result", {}).get("raw_response", {}).get("id")
            if rid:
                self.rejected[rid] = dict(
                    reason=rejected.get("error"), key=rejected["request"]["key"]
                )
        for key, a in self.attempts.items():
            raw = a.get("raw_response", {})
            if raw.get("id"):
                self.uses[raw["id"]].append(key)
            if key not in self.explanations:
                for call in raw.get("jev", {}).get("calls", []):
                    self.uses[call["fingerprint"]].append(key)
        for folder in ("responses", "openai-responses", "jev/responses"):
            for p in sorted(inside(run, run / "cache" / folder).glob("*.json")):
                record = read_json(inside(run, p))
                if "request" in record and record.get("provider") == "jev":
                    identity = hashlib.sha256(encode_request(record["request"])).hexdigest()
                    title = " / ".join(record["request"].get("questions", {})) or "Jev request"
                    if record.get("call_index") is not None:
                        title = f"Call {record['call_index']} / {title}"
                else:
                    identity = record.get("response", {}).get("id")
                    title = identity or p.stem
                # The archive can grow while the debugger is paused; keep old links stable.
                idx = "receipt-" + hashlib.sha256(f"{folder}/{p.name}".encode()).hexdigest()[:20]
                self.files[idx] = (p, identity)
                if identity:
                    self.by_identity[identity].append(idx)
                error = record.get("http_status") or record.get("error_type")
                if identity in self.rejected:
                    error = "Rejected output"
                    title = self.rejected[identity]["key"]
                self.archive.append(
                    dict(
                        id=idx,
                        title=title,
                        provider=record.get("provider", ""),
                        status=str(error) if error else "Saved",
                        linked=bool(self.uses.get(identity)),
                    )
                )

    def index(self):
        rows = []
        for key, a in self.attempts.items():
            raw, out = a.get("raw_response", {}), a.get("normalized", {})
            provider = a.get("model", {}).get("provider") or ("jev" if "jev" in raw else "unknown")
            effects = self.effects[key]
            if key in self.explanations:
                outcome = "Explained accepted match"
            elif any(e["action"] == "accepted_match_explained" for e in effects):
                outcome = "Accepted match"
            elif "target_id" in out:
                outcome = "Selected candidate" if out["target_id"] else "No match"
            else:
                outcome = {"question": "Question", "role_statement": "Role statement"}.get(
                    a.get("output_kind"), "Recorded"
                )
            rows.append(
                dict(
                    id=key,
                    title=a["request_key"],
                    stage=a["stage_id"],
                    paper=a["paper_index"],
                    provider=provider,
                    status=outcome,
                    cached=a.get("cache_hit", False),
                    target=out.get("target_id"),
                )
            )
        failure = inside(self.revision, self.revision / "failure.json")
        sample = inside(self.revision, self.revision / "sample.json")
        return dict(
            decisions=rows,
            receipts=self.archive,
            failure=read_json(failure) if failure.is_file() else None,
            sample_note=read_json(sample).get("description") if sample.is_file() else None,
            events=[
                dict(
                    id=e["event_id"],
                    title=event_subject(e),
                    status=e["action"],
                    paper=e["paper_index"],
                )
                for e in self.events
            ],
        )

    def receipt(self, key):
        p, identity = self.files[key]
        raw = read_json(p)
        jev = raw.get("provider") == "jev"
        response = raw.get("response_text") if jev else raw.get("response")
        if jev and isinstance(response, str):
            try:
                response = json.loads(response)
            except ValueError:
                pass
        sent = raw.get(
            "request_parameters",
            {k: raw[k] for k in ("messages", "schema", "api_schema", "policy") if k in raw},
        )
        if "request_parameters" in raw and "messages" in raw:
            sent["messages" if raw["provider"] == "anthropic" else "input"] = raw["messages"]
        return dict(
            provider=raw.get("provider"),
            sent=raw.get("request") if jev else sent,
            capture="Saved Jev request body"
            if jev
            else "Saved SDK parameters"
            if "request_parameters" in raw
            else "Saved messages, schema and policy; the complete SDK request was not recorded.",
            returned=response,
            attempts=self.uses.get(identity, []),
            error=raw.get("http_status") or raw.get("error_type"),
            rejection=self.rejected.get(identity),
        )

    def stage_result(self, a):
        """Use only explicit attempt IDs and the opposing votes in the same saved batch."""
        stage = a["stage_id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", stage):
            return {}

        def read_stage(name):
            path = inside(
                self.revision, self.revision / "stages" / f"{a['paper_index']:04d}-{name}.json"
            )
            return read_json(path) if path.is_file() else None

        data = read_stage(stage)
        key = a["attempt_id"]
        if isinstance(data, list):
            row = next(
                (r for r in data if isinstance(r, dict) and r.get("attempt_id") == key), None
            )
            return {"written": row} if row else {}
        if not isinstance(data, dict):
            return {}
        for batch in [data] if "forward" in data else data.values():
            if not isinstance(batch, dict) or not isinstance(batch.get("forward"), dict):
                continue
            for side, other in (("forward", "reverse"), ("reverse", "forward")):
                votes, opposite = batch.get(side) or {}, batch.get(other) or {}
                vote = next((v for v in votes.values() if v.get("attempt_id") == key), None)
                if not vote:
                    continue
                source, target = vote["source_id"], vote["target_id"]
                reply = opposite.get(target)
                result = dict(
                    opposite=reply,
                    incoming=[
                        v for v in opposite.values() if v.get("target_id") == source and v != reply
                    ],
                )
                if stage in ("section_matching", "paragraph_matching"):
                    unit = source if side == "forward" else target
                    assignments = read_stage(stage.replace("_matching", "_reconciliation")) or {}
                    if unit in assignments:
                        result.update(unit=unit, group=assignments[unit])
                return result
        return {}

    def decision(self, key):
        a = self.attempts[key]
        raw = a.get("raw_response", {})
        calls = []
        if key not in self.explanations:
            for call in raw.get("jev", {}).get("calls", []):
                fp = call["fingerprint"]
                p = inside(self.run, self.run / "cache/jev" / (fp + ".json"))
                cached = read_json(p) if re.fullmatch("[0-9a-f]{64}", fp) and p.is_file() else {}
                sent = cached.get("request")
                ids = self.by_identity.get(fp, [])
                if sent is None and ids:
                    sent = self.receipt(ids[0])["sent"]
                reply = call.get("response") or cached.get("response")
                calls.append(
                    dict(
                        provider="Jev",
                        phase=" / ".join((reply or {}).get("answers", {})),
                        cached=bool(a.get("cache_hit") or call.get("cache_hit")),
                        sent=sent,
                        returned=reply,
                        receipts=ids,
                        capture="Saved Jev request body" if sent else "Request body unavailable",
                        options=call.get("option_ids"),
                    )
                )
        if "jev" not in raw or set(raw) != {"jev"}:
            ids = self.by_identity.get(raw.get("id"), [])
            record = self.receipt(ids[0]) if ids else {}
            calls.append(
                dict(
                    provider=a["model"].get("provider", "unknown"),
                    phase=a.get("skill_ref") or a["output_kind"],
                    cached=a.get("cache_hit"),
                    sent=record.get(
                        "sent", {k: a.get(k) for k in ("rendered_system", "rendered_user")}
                    ),
                    capture=record.get("capture", "Journal only; not a complete API request."),
                    returned=record.get("returned", {k: v for k, v in raw.items() if k != "jev"}),
                    receipts=ids,
                )
            )
        return dict(
            result=a.get("normalized"),
            calls=calls,
            effects=self.effects[key],
            stage_result=self.stage_result(a),
            model=a.get("model"),
            candidates=a.get("candidate_ids", []),
        )

    def event(self, key):
        i = self.by_event[key]
        e = self.events[i]
        graph = graph_from_events(self.events[: i + 1])
        nodes = [
            e.get(k)
            for k in (
                "node_id",
                "source_node_id",
                "target_node_id",
                "source",
                "target",
                "target_id",
            )
        ]
        return dict(
            event=e,
            groups=graph.number_of_nodes(),
            edges=graph.number_of_edges(),
            affected={k: graph.nodes[k] for k in nodes if k and k in graph},
            attempts=refs(e),
        )


def revisions(root):
    from .package_catalog import LABELS

    entries = []
    for p in root.glob("*/revisions/revision-*"):
        run = p.parent.parent
        if (
            not re.fullmatch(r"[\w-]+", run.name, re.ASCII)
            or not re.fullmatch(r"revision-\d{4,}", p.name)
            or not p.resolve().is_relative_to(root)
        ):
            continue
        prov = inside(p, p / "provenance")
        if not prov.is_dir():
            continue
        status = (
            "Failed"
            if (p / "failure.json").exists()
            else "Complete"
            if (p / "summary.json").exists()
            else "Unfinished"
        )
        entries.append(
            dict(
                run=run.name,
                label=LABELS.get(run.name, run.name.replace("-", " ")),
                rev=p.name,
                status=status,
                modified=p.stat().st_mtime_ns,
            )
        )
    return sorted(entries, key=lambda x: x["modified"], reverse=True)


@lru_cache(maxsize=2)
def _load(run, rev, stamp):
    return Trace(run, rev)


def load(root: Path, run: str, rev: str):
    directory = inside(root, root / run)
    p = inside(directory, directory / "revisions" / rev)
    if not inside(p, p / "provenance").is_dir():
        raise KeyError(rev)
    watched = [p / "provenance" / name for name in ("events.jsonl", "attempts.jsonl")]
    watched += [
        directory / "cache" / name
        for name in ("responses", "openai-responses", "jev/responses", "rejected")
    ]
    paths = [inside(directory, path) for path in watched + [p / "failure.json", p / "summary.json"]]
    stamp = tuple(path.stat().st_mtime_ns if path.exists() else None for path in paths)
    return _load(directory, rev, stamp)
