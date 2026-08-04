"""Local API and static server for repeatable Question Atlas analyses."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import uuid
import webbrowser
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from env_utils import load_dotenv_upwards
from pipeline_paths import PIPELINE_DIR, REPO_DIR, papers_dir

SERVER_OUTPUT_DIR = PIPELINE_DIR / "output"
RUNS_DIR = SERVER_OUTPUT_DIR / "runs"
UPLOADS_DIR = SERVER_OUTPUT_DIR / "uploads"
LATEST_PATH = SERVER_OUTPUT_DIR / "latest_run.json"
SAFE_ARTIFACT = re.compile(r"^[a-zA-Z0-9_.-]+$")
SAFE_MODEL = re.compile(r"^[a-zA-Z0-9_.:-]{1,120}$")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_COUNT = 20

DEFAULT_CONFIG = {
    "experiment_label": "",
    "model": "claude-sonnet-5",
    "max_epochs": 3,
    "section_weight": 0.15,
    "question_stability_threshold": 0.97,
    "section_context_max_chars": 0,
    "paragraph_chunk_chars": 50_000,
    "assignment_batch_chars": 80_000,
    "representative_per_paper": 2,
    "representative_max_per_group": 6,
    "match_top_k": 3,
    "section_group_threshold": 0.33,
    "paragraph_group_threshold": 0.45,
    "supergroup_threshold": 0.33,
    "paragraph_context": "section",
    "assignment_context": "question_only",
    "reuse_scope": "fresh",
    "source_run_id": "",
}


def analysis_python() -> Path:
    """Prefer the project environment even when the server uses global Python."""
    candidates = (
        PIPELINE_DIR / ".venv" / "Scripts" / "python.exe",
        PIPELINE_DIR / ".venv" / "bin" / "python",
    )
    return next((path for path in candidates if path.is_file()), Path(sys.executable))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_paper_id(filename: str) -> str:
    stem = Path(filename).stem.strip()
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", stem).strip("._-")
    return (normalized or "paper")[:100]


def upload_metadata() -> list[dict]:
    uploads = []
    for path in sorted(
        UPLOADS_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
    ):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        stored = UPLOADS_DIR / data.get("stored_filename", "")
        if stored.is_file():
            uploads.append(data)
    return uploads


def save_upload(filename: str, data: bytes) -> dict:
    if not filename.lower().endswith(".pdf"):
        raise ValueError(f"{filename!r} is not a PDF filename")
    if not data.startswith(b"%PDF"):
        raise ValueError(f"{filename!r} does not contain a valid PDF header")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"{filename!r} exceeds the 50 MB upload limit")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    upload_id = uuid.uuid4().hex
    paper_id = safe_paper_id(filename)
    stored_filename = f"{upload_id}--{paper_id}.pdf"
    stored_path = UPLOADS_DIR / stored_filename
    stored_path.write_bytes(data)
    metadata = {
        "upload_id": upload_id,
        "paper_id": paper_id,
        "filename": Path(filename).name,
        "stored_filename": stored_filename,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "uploaded_at": utc_now(),
    }
    (UPLOADS_DIR / f"{upload_id}.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata


def saved_runs() -> list[dict]:
    rows = []
    for run_dir in sorted(RUNS_DIR.glob("*"), key=lambda item: item.name, reverse=True):
        metadata_path = run_dir / "analysis_run.json"
        if not metadata_path.is_file():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(
            {
                "run_id": metadata.get("run_id", run_dir.name),
                "status": metadata.get("status", "unknown"),
                "started_at": metadata.get("started_at"),
                "completed_at": metadata.get("completed_at"),
                "model": metadata.get("model"),
                "experiment_label": metadata.get("config", {}).get(
                    "experiment_label", ""
                ),
                "paragraph_context": metadata.get("config", {}).get(
                    "paragraph_context", "section"
                ),
                "assignment_context": metadata.get("config", {}).get(
                    "assignment_context", "question_only"
                ),
                "reuse_scope": metadata.get("config", {}).get(
                    "reuse_scope", "fresh"
                ),
                "papers": [
                    paper.get("paper_id") for paper in metadata.get("papers", [])
                ],
                "has_results": (run_dir / "epoch_history.json").is_file(),
            }
        )
    return rows


class RunManager:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.state = {
            "run_id": None,
            "status": "idle",
            "stage": None,
            "started_at": None,
            "completed_at": None,
            "logs": [],
            "error": None,
            "config": None,
        }
        if LATEST_PATH.is_file():
            latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
            self.state.update(latest)
            self.state["status"] = (
                "complete" if self._artifact_path("epoch_history.json") else "idle"
            )

    def _artifact_path(self, filename: str, run_id: str | None = None) -> Path | None:
        selected_run = run_id or self.state.get("run_id")
        if not selected_run:
            return None
        path = RUNS_DIR / selected_run / filename
        return path if path.is_file() else None

    def snapshot(self) -> dict:
        with self.lock:
            state = dict(self.state)
            state["logs"] = list(self.state["logs"][-300:])
            state["has_results"] = bool(self._artifact_path("epoch_history.json"))
            return state

    def artifact(self, filename: str, run_id: str | None = None) -> Path | None:
        if not SAFE_ARTIFACT.fullmatch(filename) or (
            run_id and not SAFE_ARTIFACT.fullmatch(run_id)
        ):
            return None
        with self.lock:
            return self._artifact_path(filename, run_id)

    @staticmethod
    def _resolve_papers(
        paper_ids: list[str], upload_ids: list[str]
    ) -> list[tuple[Path, str]]:
        library = {path.stem: path for path in papers_dir().glob("*.pdf")}
        invalid = sorted(set(paper_ids) - set(library))
        if invalid:
            raise ValueError(f"Unknown library paper ids: {invalid}")

        uploads = {item["upload_id"]: item for item in upload_metadata()}
        missing_uploads = sorted(set(upload_ids) - set(uploads))
        if missing_uploads:
            raise ValueError(f"Unknown uploaded paper ids: {missing_uploads}")

        selected = [
            (library[paper_id], library[paper_id].name) for paper_id in paper_ids
        ]
        selected.extend(
            (
                UPLOADS_DIR / uploads[upload_id]["stored_filename"],
                uploads[upload_id]["filename"],
            )
            for upload_id in upload_ids
        )
        if len(selected) < 2:
            raise ValueError("Select or upload at least two papers")
        return selected

    def start(
        self,
        paper_ids: list[str],
        upload_ids: list[str],
        config: dict,
        api_key: str | None = None,
    ) -> dict:
        with self.lock:
            if self.process and self.process.poll() is None:
                raise RuntimeError("An analysis is already running")
            selected = self._resolve_papers(paper_ids, upload_ids)
            effective_key = (api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
            if not effective_key:
                raise ValueError(
                    "Provide a Claude API key or configure ANTHROPIC_API_KEY on the server"
                )

            run_id = (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                + "-"
                + uuid.uuid4().hex[:8]
            )
            run_dir = RUNS_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=False)
            command = [
                str(analysis_python()),
                str(PIPELINE_DIR / "run_analysis.py"),
                "--output-dir",
                str(run_dir),
                "--run-id",
                run_id,
                "--model",
                config["model"],
                "--max-epochs",
                str(config["max_epochs"]),
                "--section-weight",
                str(config["section_weight"]),
                "--question-stability-threshold",
                str(config["question_stability_threshold"]),
                "--section-context-max-chars",
                str(config["section_context_max_chars"]),
                "--paragraph-chunk-chars",
                str(config["paragraph_chunk_chars"]),
                "--assignment-batch-chars",
                str(config["assignment_batch_chars"]),
                "--representative-per-paper",
                str(config["representative_per_paper"]),
                "--representative-max-per-group",
                str(config["representative_max_per_group"]),
                "--match-top-k",
                str(config["match_top_k"]),
                "--section-group-threshold",
                str(config["section_group_threshold"]),
                "--paragraph-group-threshold",
                str(config["paragraph_group_threshold"]),
                "--supergroup-threshold",
                str(config["supergroup_threshold"]),
                "--experiment-label",
                config["experiment_label"],
                "--paragraph-context",
                config["paragraph_context"],
                "--assignment-context",
                config["assignment_context"],
                "--reuse-scope",
                config["reuse_scope"],
                *[str(path) for path, _ in selected],
            ]
            if config["source_run_id"]:
                source_run_dir = RUNS_DIR / config["source_run_id"]
                command[2:2] = ["--source-run-dir", str(source_run_dir)]
            public_config = {
                **config,
                "paper_ids": list(paper_ids),
                "upload_ids": list(upload_ids),
                "api_key_source": "run menu" if api_key else "server environment",
            }
            self.state = {
                "run_id": run_id,
                "status": "running",
                "stage": {"id": "starting", "label": "Starting analysis"},
                "started_at": utc_now(),
                "completed_at": None,
                "logs": [],
                "error": None,
                "config": public_config,
            }
            child_env = os.environ.copy()
            child_env["ANTHROPIC_API_KEY"] = effective_key
            child_env["SME_INPUT_NAMES_JSON"] = json.dumps(
                {str(path.resolve()): display_name for path, display_name in selected}
            )
            try:
                self.process = subprocess.Popen(
                    command,
                    cwd=PIPELINE_DIR,
                    env=child_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
            except OSError as exc:
                self.state["status"] = "failed"
                self.state["error"] = str(exc)
                raise RuntimeError(f"Could not start analysis: {exc}") from exc
            threading.Thread(
                target=self._watch, args=(self.process, run_id), daemon=True
            ).start()
            return dict(self.state)

    def _watch(self, process: subprocess.Popen[str], run_id: str) -> None:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            with self.lock:
                if line.startswith("@@STAGE "):
                    try:
                        self.state["stage"] = json.loads(line[len("@@STAGE ") :])
                    except json.JSONDecodeError:
                        pass
                elif line:
                    self.state["logs"].append(line)
                    self.state["logs"] = self.state["logs"][-500:]
        return_code = process.wait()
        with self.lock:
            self.state["completed_at"] = utc_now()
            if return_code == 0 and self._artifact_path("epoch_history.json", run_id):
                self.state["status"] = "complete"
                self.state["stage"] = {"id": "complete", "label": "Analysis complete"}
                LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
                LATEST_PATH.write_text(
                    json.dumps(self.state, indent=2), encoding="utf-8"
                )
            else:
                self.state["status"] = "failed"
                self.state["error"] = (
                    self.state["logs"][-1]
                    if self.state["logs"]
                    else f"Process exited {return_code}"
                )
            self.process = None


class AnalysisHandler(SimpleHTTPRequestHandler):
    manager: RunManager

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PIPELINE_DIR), **kwargs)

    def _json(self, value: dict | list, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2 * 1024 * 1024:
            raise ValueError("JSON request is too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def _multipart_files(self) -> list[tuple[str, bytes]]:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("Upload requests must use multipart/form-data")
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_UPLOAD_COUNT * MAX_UPLOAD_BYTES:
            raise ValueError("Upload request is too large")
        body = self.rfile.read(length)
        envelope = (
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
        )
        message = BytesParser(policy=policy.default).parsebytes(envelope)
        files = []
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data" or not part.get_filename():
                continue
            files.append((part.get_filename(), part.get_payload(decode=True) or b""))
        if not files:
            raise ValueError("No PDF files were supplied")
        if len(files) > MAX_UPLOAD_COUNT:
            raise ValueError(f"Upload at most {MAX_UPLOAD_COUNT} papers at once")
        return files

    @staticmethod
    def _validated_config(payload: dict) -> dict:
        config = {
            "experiment_label": str(
                payload.get("experiment_label", DEFAULT_CONFIG["experiment_label"])
            ).strip(),
            "model": str(payload.get("model", DEFAULT_CONFIG["model"])).strip(),
            "max_epochs": int(payload.get("max_epochs", DEFAULT_CONFIG["max_epochs"])),
            "section_weight": float(
                payload.get("section_weight", DEFAULT_CONFIG["section_weight"])
            ),
            "question_stability_threshold": float(
                payload.get(
                    "question_stability_threshold",
                    DEFAULT_CONFIG["question_stability_threshold"],
                )
            ),
            "section_context_max_chars": int(
                payload.get(
                    "section_context_max_chars",
                    DEFAULT_CONFIG["section_context_max_chars"],
                )
            ),
            "paragraph_chunk_chars": int(
                payload.get(
                    "paragraph_chunk_chars", DEFAULT_CONFIG["paragraph_chunk_chars"]
                )
            ),
            "assignment_batch_chars": int(
                payload.get(
                    "assignment_batch_chars", DEFAULT_CONFIG["assignment_batch_chars"]
                )
            ),
            "representative_per_paper": int(
                payload.get(
                    "representative_per_paper",
                    DEFAULT_CONFIG["representative_per_paper"],
                )
            ),
            "representative_max_per_group": int(
                payload.get(
                    "representative_max_per_group",
                    DEFAULT_CONFIG["representative_max_per_group"],
                )
            ),
            "match_top_k": int(
                payload.get("match_top_k", DEFAULT_CONFIG["match_top_k"])
            ),
            "section_group_threshold": float(
                payload.get(
                    "section_group_threshold", DEFAULT_CONFIG["section_group_threshold"]
                )
            ),
            "paragraph_group_threshold": float(
                payload.get(
                    "paragraph_group_threshold",
                    DEFAULT_CONFIG["paragraph_group_threshold"],
                )
            ),
            "supergroup_threshold": float(
                payload.get(
                    "supergroup_threshold", DEFAULT_CONFIG["supergroup_threshold"]
                )
            ),
            "paragraph_context": str(
                payload.get("paragraph_context", DEFAULT_CONFIG["paragraph_context"])
            ),
            "assignment_context": str(
                payload.get("assignment_context", DEFAULT_CONFIG["assignment_context"])
            ),
            "reuse_scope": str(
                payload.get("reuse_scope", DEFAULT_CONFIG["reuse_scope"])
            ),
            "source_run_id": str(
                payload.get("source_run_id", DEFAULT_CONFIG["source_run_id"])
            ).strip(),
        }
        if len(config["experiment_label"]) > 100 or any(
            ord(char) < 32 for char in config["experiment_label"]
        ):
            raise ValueError(
                "experiment_label must be at most 100 printable characters"
            )
        if not SAFE_MODEL.fullmatch(config["model"]):
            raise ValueError("model contains unsupported characters")
        if not 0 <= config["max_epochs"] <= 20:
            raise ValueError("max_epochs must be between 0 and 20")
        for name in (
            "section_weight",
            "question_stability_threshold",
            "section_group_threshold",
            "paragraph_group_threshold",
            "supergroup_threshold",
        ):
            if not 0 <= config[name] <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if not 0 <= config["section_context_max_chars"] <= 1_000_000:
            raise ValueError(
                "section_context_max_chars must be between 0 and 1,000,000"
            )
        if not 0 <= config["paragraph_chunk_chars"] <= 500_000:
            raise ValueError("paragraph_chunk_chars must be between 0 and 500,000")
        if not 10_000 <= config["assignment_batch_chars"] <= 500_000:
            raise ValueError(
                "assignment_batch_chars must be between 10,000 and 500,000"
            )
        if not 1 <= config["representative_per_paper"] <= 20:
            raise ValueError("representative_per_paper must be between 1 and 20")
        if not 1 <= config["representative_max_per_group"] <= 100:
            raise ValueError(
                "representative_max_per_group must be between 1 and 100"
            )
        if not 1 <= config["match_top_k"] <= 20:
            raise ValueError("match_top_k must be between 1 and 20")
        if config["paragraph_context"] not in {
            "section",
            "fixed_section",
            "full_paper",
        }:
            raise ValueError(
                "paragraph_context must be section, fixed_section, or full_paper"
            )
        if config["assignment_context"] not in {
            "question_only",
            "representative_group_paragraphs",
            "all_group_paragraphs",
        }:
            raise ValueError(
                "assignment_context must be question_only, "
                "representative_group_paragraphs, or all_group_paragraphs"
            )
        if config["reuse_scope"] not in {"fresh", "paragraph_corpus", "pre_epoch"}:
            raise ValueError(
                "reuse_scope must be fresh, paragraph_corpus, or pre_epoch"
            )
        if config["source_run_id"] and not SAFE_ARTIFACT.fullmatch(
            config["source_run_id"]
        ):
            raise ValueError("source_run_id contains unsupported characters")
        if config["reuse_scope"] == "fresh" and config["source_run_id"]:
            raise ValueError("fresh runs cannot specify source_run_id")
        if config["reuse_scope"] != "fresh" and not config["source_run_id"]:
            raise ValueError("reused runs require source_run_id")
        if (
            config["source_run_id"]
            and not (RUNS_DIR / config["source_run_id"] / "analysis_run.json").is_file()
        ):
            raise ValueError("source_run_id does not identify a saved run")
        if (
            config["reuse_scope"] == "pre_epoch"
            and config["paragraph_context"] != "section"
        ):
            raise ValueError("pre_epoch reuse cannot relabel paragraph context")
        return config

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/viz/tag_matches_viewer.html")
            self.end_headers()
            return
        if parsed.path == "/api/config":
            papers = [
                {
                    "paper_id": path.stem,
                    "filename": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
                for path in sorted(papers_dir().glob("*.pdf"))
            ]
            self._json(
                {
                    "papers": papers,
                    "uploads": upload_metadata(),
                    "runs": saved_runs(),
                    "defaults": DEFAULT_CONFIG,
                    "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
                    "status": self.manager.snapshot(),
                }
            )
            return
        if parsed.path == "/api/status":
            self._json(self.manager.snapshot())
            return
        if parsed.path.startswith("/api/artifacts/"):
            filename = unquote(parsed.path.removeprefix("/api/artifacts/"))
            run_id = parse_qs(parsed.query).get("run_id", [None])[0]
            artifact = self.manager.artifact(filename, run_id)
            if not artifact:
                self._json({"error": "Artifact not found"}, HTTPStatus.NOT_FOUND)
                return
            body = artifact.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/uploads":
                uploaded = [
                    save_upload(filename, data)
                    for filename, data in self._multipart_files()
                ]
                self._json({"uploads": uploaded}, HTTPStatus.CREATED)
                return
            if parsed.path != "/api/analyze":
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            payload = self._json_body()
            config = self._validated_config(payload)
            state = self.manager.start(
                list(payload.get("paper_ids", [])),
                list(payload.get("upload_ids", [])),
                config,
                str(payload.get("anthropic_api_key", "")).strip() or None,
            )
            self._json(state, HTTPStatus.ACCEPTED)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8743)
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open the viewer automatically"
    )
    args = parser.parse_args()
    dotenv_paths = load_dotenv_upwards(REPO_DIR)
    SERVER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    manager = RunManager()
    AnalysisHandler.manager = manager
    server = ThreadingHTTPServer((args.host, args.port), AnalysisHandler)
    key_status = "configured" if os.environ.get("ANTHROPIC_API_KEY") else "missing"
    dotenv_message = f" from {len(dotenv_paths)} dotenv file(s)" if dotenv_paths else ""
    viewer_url = f"http://{args.host}:{args.port}/"
    print(f"Question Atlas: {viewer_url} (Anthropic key {key_status}{dotenv_message})")
    if not args.no_browser:
        browser_timer = threading.Timer(0.25, webbrowser.open, args=(viewer_url,))
        browser_timer.daemon = True
        browser_timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
