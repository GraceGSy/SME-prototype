"""Keep each Jev request once, with its repeated paper text stored once per cache.

Long-context requests resend whole papers, so nearly every line of one request's state
also appears in thousands of others. Each request is saved once, under its fingerprint
(the sha256 of the encoded body). Its state is saved as a list of blocks, each block as a
list of lines, and each long line as its own text file. Blocks and lines are named by a
short content hash and shared by every request in the cache. Answer-cache records and
call logs name the request's fingerprint instead of carrying a copy.

Loading rebuilds the exact body and checks its fingerprint, so a damaged or colliding
file fails loudly instead of answering for a different request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .jev import encode_request

# A line this long is stored once and referenced; shorter lines stay in their block.
LONG_LINE = 80
SHORT_HASH = 16


def fingerprint(body: dict) -> str:
    return hashlib.sha256(encode_request(body)).hexdigest()


def _short(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:SHORT_HASH]


def _compact(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _write_once(path: Path, data: bytes) -> None:
    """Content-addressed write: an existing file must already hold exactly these bytes."""
    if path.is_file():
        if path.read_bytes() != data:
            raise ValueError(f"Jev store collision at {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _blocks(state: str) -> list[list[str]]:
    """Start a block at each unindented line, so a section and its paragraphs move together."""
    blocks: list[list[str]] = []
    for line in state.split("\n"):
        if not blocks or not line.startswith(" "):
            blocks.append([])
        blocks[-1].append(line)
    return blocks


class JevStore:
    def __init__(self, root: Path):
        self.root = root
        self.requests = root / "requests"
        self.blocks = root / "text" / "blocks"
        self.lines = root / "text" / "lines"

    def save(self, body: dict) -> str:
        """Store ``body`` if it is new; return its fingerprint."""
        key = fingerprint(body)
        path = self.requests / f"{key}.json"
        if path.is_file():
            return key
        # ``order`` keeps the key order, so the rebuilt body encodes to the same bytes.
        record: dict = {
            "order": list(body),
            "request": {k: v for k, v in body.items() if k != "state"},
        }
        state = body.get("state")
        if isinstance(state, str):
            record["state_blocks"] = [self._save_block(block) for block in _blocks(state)]
        elif "state" in body:
            record["request"]["state"] = state
        _write_once(path, _compact(record))
        if self.load(key) != body:  # Never keep a record that would replay differently.
            path.unlink()
            raise ValueError("Jev store could not rebuild the request it saved")
        return key

    def _save_block(self, lines: list[str]) -> str:
        items: list = []
        for line in lines:
            if len(line) >= LONG_LINE:
                data = line.encode("utf-8")
                name = _short(data)
                _write_once(self.lines / f"{name}.txt", data)
                items.append({"line": name})
            else:
                items.append(line)
        data = _compact(items)
        name = _short(data)
        _write_once(self.blocks / f"{name}.json", data)
        return name

    def has(self, key: str) -> bool:
        return (self.requests / f"{key}.json").is_file()

    def load(self, key: str) -> dict:
        saved = json.loads((self.requests / f"{key}.json").read_bytes())
        parts = dict(saved["request"])
        if "state_blocks" in saved:
            lines = []
            for name in saved["state_blocks"]:
                for item in json.loads((self.blocks / f"{name}.json").read_bytes()):
                    if isinstance(item, str):
                        lines.append(item)
                    else:
                        text = (self.lines / f"{item['line']}.txt").read_bytes()
                        lines.append(text.decode("utf-8"))
            parts["state"] = "\n".join(lines)
        body = {k: parts[k] for k in saved["order"]}
        if fingerprint(body) != key:
            raise ValueError(f"Jev stored request {key} does not match its fingerprint")
        return body

    def request_of(self, record: dict) -> dict:
        """The full request of an answer-cache record or call log, in either format."""
        if "request" in record:
            return record["request"]
        return self.load(record["request_fingerprint"])


def compact_cache(root: Path) -> dict:
    """Move inline requests under ``root`` (a ``cache/jev`` folder) into the store.

    Every rewritten file is checked first: its request must rebuild exactly from the store.
    """
    store = JevStore(root)
    counts = {"answers": 0, "markers": 0, "call_logs": 0, "already_compact": 0}
    folders = [root, root / "long-context", root / "too-large", root / "too-large" / "long-context"]
    for folder in folders:
        for path in sorted(folder.glob("*.json")):
            record = json.loads(path.read_bytes())
            if "request" not in record:
                counts["already_compact"] += 1
                continue
            key = store.save(record["request"])
            if key != path.stem:
                raise ValueError(f"{path} is not named by its request's fingerprint")
            rest = {k: v for k, v in record.items() if k != "request"}
            _rewrite(path, {"request_fingerprint": key, **rest})
            counts["answers" if "response" in record else "markers"] += 1
    for path in sorted((root / "responses").glob("*.json")):
        record = json.loads(path.read_bytes())
        if "request" not in record:
            counts["already_compact"] += 1
            continue
        _rewrite(path, call_log(store, record))
        counts["call_logs"] += 1
    return counts


def call_log(store: JevStore, record: dict) -> dict:
    """A call log that names its request; ``questions`` keeps the log readable on its own."""
    body = record["request"]
    out = {"provider": record.get("provider", "jev"), "request_fingerprint": store.save(body)}
    out["questions"] = list(body.get("questions", {}))
    return out | {k: v for k, v in record.items() if k not in ("request", "provider")}


def _rewrite(path: Path, record: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=compact_cache.__doc__)
    parser.add_argument("cache", type=Path, help="A run's cache/jev folder")
    args = parser.parse_args()
    print(compact_cache(args.cache))
