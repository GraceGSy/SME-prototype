"""Build the quantitative audit PDF from every saved Question Atlas run."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean
from typing import Any

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


PIPELINE_DIR = Path(__file__).resolve().parent
REPO_DIR = PIPELINE_DIR.parent
DEFAULT_RUNS_DIR = PIPELINE_DIR / "output" / "runs"
DEFAULT_OUTPUT = REPO_DIR / "output" / "pdf" / "question_atlas_run_analysis.pdf"

NAVY = HexColor("#17324d")
BLUE = HexColor("#2f80ed")
PALE_BLUE = HexColor("#edf5ff")
TEAL = HexColor("#2a9d8f")
GREEN = HexColor("#4f8a5b")
GOLD = HexColor("#c58b22")
ORANGE = HexColor("#d96c2c")
RED = HexColor("#b5483a")
INK = HexColor("#24313d")
MID = HexColor("#66737f")
LIGHT = HexColor("#e4e9ee")
WASH = HexColor("#f5f7f9")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def paragraph_key(value: Any) -> str:
    if isinstance(value, str):
        return value
    return f"{value.get('paper')}:{value.get('unit_id')}"


@dataclass(frozen=True)
class Snapshot:
    epoch: int
    group_count: int
    assigned: frozenset[str]
    unassigned: frozenset[str]
    memberships: int
    multi_assigned: int
    newly_assigned: int

    @property
    def total(self) -> int:
        return len(self.assigned | self.unassigned)

    @property
    def coverage(self) -> float:
        return 100.0 * len(self.assigned) / self.total if self.total else 0.0


@dataclass
class RunAudit:
    run_id: str
    metadata: dict[str, Any]
    history: dict[str, Any] | None
    snapshots: list[Snapshot]
    condition_key: str

    @property
    def status(self) -> str:
        return str(self.metadata.get("status") or "unknown")

    @property
    def config(self) -> dict[str, Any]:
        return self.metadata.get("config") or {}

    @property
    def final(self) -> Snapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    @property
    def is_complete(self) -> bool:
        return self.status == "complete"

    @property
    def is_partial(self) -> bool:
        return not self.is_complete and bool(self.snapshots)

    @property
    def runtime_minutes(self) -> float | None:
        try:
            started = datetime.fromisoformat(self.metadata["started_at"])
            completed = datetime.fromisoformat(self.metadata["completed_at"])
        except (KeyError, TypeError, ValueError):
            return None
        return (completed - started).total_seconds() / 60.0


CONDITION_NAMES = {
    "bootstrap": "Bootstrap failure",
    "legacy": "Legacy reassignment",
    "baseline": "Monotonic baseline",
    "question_only": "Question-only replication",
    "fixed_section": "Fixed-section labels",
    "full_paper": "Full-paper labels",
    "representative": "Representative group evidence",
    "all_evidence": "All group evidence",
}

CONDITION_DESCRIPTIONS = {
    "bootstrap": (
        "Infrastructure launch attempt. It stopped before section extraction because the "
        "server used the wrong Python environment, so it contains no analytical outcome."
    ),
    "legacy": (
        "Earlier non-monotonic prototype. It retained only two initial supergroups and "
        "reassigned every paragraph on every epoch, so coverage could rise or fall and its "
        "group count is not comparable to the current complete group set."
    ),
    "baseline": (
        "First complete append-only implementation. It ran fresh extraction and sticky "
        "orphan assignment, but predates the controlled fixed-corpus experiment metadata."
    ),
    "question_only": (
        "Fresh end-to-end rerun from the three PDFs. During orphan assignment, Claude saw "
        "each complete orphan paragraph and the candidate group questions, but no text from "
        "paragraphs already assigned to those groups."
    ),
    "fixed_section": (
        "Reused the replication's exact paragraph ids, boundaries, text, sections, order, "
        "and relations. Claude regenerated only the paragraph questions while seeing each "
        "paragraph's complete containing section; downstream matching and epochs were rerun."
    ),
    "full_paper": (
        "Reused the same exact fixed paragraph corpus, but Claude regenerated paragraph "
        "questions while seeing the complete paper. This tests broader labeling context "
        "without changing paragraph boundaries or source text."
    ),
    "representative": (
        "Copied the question-only replication's complete pre-epoch state. During orphan "
        "assignment, each group question was accompanied by deterministic corpus-TF-IDF "
        "medoid paragraphs: at most two per source paper and six per group."
    ),
    "all_evidence": (
        "Copied the same pre-epoch state, then accompanied every candidate group question "
        "with the complete text of every paragraph already assigned to that group. This is "
        "what 'all group evidence' means; only assignment evidence changed."
    ),
}


def snapshot_from_state(state: dict[str, Any]) -> Snapshot:
    groups = state.get("groups") or []
    group_members = [
        {paragraph_key(member) for member in group.get("members") or []}
        for group in groups
    ]
    assigned = set().union(*group_members) if group_members else set()
    frequencies = Counter(key for members in group_members for key in members)
    unassigned = {paragraph_key(item) for item in state.get("unassigned_paragraphs") or []}
    return Snapshot(
        epoch=int(state.get("epoch") or 0),
        group_count=len(groups),
        assigned=frozenset(assigned),
        unassigned=frozenset(unassigned),
        memberships=sum(len(members) for members in group_members),
        multi_assigned=sum(count > 1 for count in frequencies.values()),
        newly_assigned=len(state.get("newly_assigned_paragraphs") or []),
    )


def classify_condition(metadata: dict[str, Any], history: dict[str, Any] | None) -> str:
    label = (metadata.get("config") or {}).get("experiment_label")
    label_map = {
        "exact-replication": "question_only",
        "fixed-section-context": "fixed_section",
        "full-paper-context": "full_paper",
        "representative-evidence-assignment": "representative",
        "evidence-aware-assignment": "all_evidence",
    }
    if label in label_map:
        return label_map[label]
    if history is None:
        return "bootstrap"
    if int(history.get("schema_version") or 1) == 1:
        return "legacy"
    return "baseline"


def load_runs(runs_dir: Path) -> list[RunAudit]:
    runs: list[RunAudit] = []
    for directory in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        metadata_path = directory / "analysis_run.json"
        if not metadata_path.exists():
            continue
        metadata = read_json(metadata_path)
        history_path = directory / "epoch_history.json"
        history = read_json(history_path) if history_path.exists() else None
        states: list[dict[str, Any]] = []
        if history:
            if history.get("initial_state"):
                states.append(history["initial_state"])
            states.extend(history.get("epochs") or [])
        snapshots = [snapshot_from_state(state) for state in states]
        runs.append(
            RunAudit(
                run_id=directory.name,
                metadata=metadata,
                history=history,
                snapshots=snapshots,
                condition_key=classify_condition(metadata, history),
            )
        )
    return runs


def latest_complete_by_condition(runs: list[RunAudit]) -> dict[str, RunAudit]:
    result: dict[str, RunAudit] = {}
    for run in runs:
        if run.is_complete:
            result[run.condition_key] = run
    return result


def relabel_stats(run: RunAudit, runs_dir: Path) -> dict[str, float | int]:
    path = runs_dir / run.run_id / "paragraph_context_relabel.json"
    data = read_json(path)
    changes: list[dict[str, Any]] = []
    for paper in data.get("papers") or []:
        changes.extend(paper.get("changes") or [])
        for section in paper.get("sections") or []:
            changes.extend(section.get("changes") or [])

    def words(text: str) -> int:
        return len(re.findall(r"[A-Za-z0-9']+", text))

    return {
        "total": len(changes),
        "changed": sum(item.get("previous_question") != item.get("question") for item in changes),
        "old_words": mean(words(item.get("previous_question") or "") for item in changes),
        "new_words": mean(words(item.get("question") or "") for item in changes),
        "similarity": mean(
            SequenceMatcher(
                None,
                item.get("previous_question") or "",
                item.get("question") or "",
            ).ratio()
            for item in changes
        ),
    }


def evidence_characters(run: RunAudit) -> list[int]:
    if not run.history:
        return []
    return [
        int(((epoch.get("assignment") or {}).get("context") or {}).get("evidence_characters") or 0)
        for epoch in run.history.get("epochs") or []
    ]


def assignment_overlap(reference: RunAudit, treatment: RunAudit) -> float:
    if not reference.final or not treatment.final:
        return 0.0
    union = reference.final.assigned | treatment.final.assigned
    return 100.0 * len(reference.final.assigned & treatment.final.assigned) / len(union)


def short_run_id(run_id: str) -> str:
    match = re.match(r"(\d{4})(\d{2})(\d{2})T(\d{6})Z", run_id)
    return f"{match.group(2)}/{match.group(3)} {match.group(4)}" if match else run_id[:15]


def escape(value: Any) -> str:
    return html.escape(str(value), quote=False)


BASE_STYLES = getSampleStyleSheet()
STYLE = {
    "kicker": ParagraphStyle(
        "Kicker", parent=BASE_STYLES["Normal"], fontName="Helvetica-Bold",
        fontSize=7.2, leading=9, textColor=BLUE, spaceAfter=7, tracking=1.1,
    ),
    "title": ParagraphStyle(
        "Title", parent=BASE_STYLES["Title"], fontName="Helvetica-Bold",
        fontSize=23, leading=25, textColor=NAVY, alignment=TA_LEFT, spaceAfter=8,
    ),
    "subtitle": ParagraphStyle(
        "Subtitle", parent=BASE_STYLES["Normal"], fontSize=9.4, leading=13,
        textColor=MID, spaceAfter=12,
    ),
    "h1": ParagraphStyle(
        "H1", parent=BASE_STYLES["Heading1"], fontName="Helvetica-Bold",
        fontSize=14, leading=17, textColor=NAVY, spaceBefore=4, spaceAfter=7,
    ),
    "h2": ParagraphStyle(
        "H2", parent=BASE_STYLES["Heading2"], fontName="Helvetica-Bold",
        fontSize=10.5, leading=13, textColor=INK, spaceBefore=7, spaceAfter=4,
    ),
    "body": ParagraphStyle(
        "Body", parent=BASE_STYLES["BodyText"], fontSize=8.3, leading=11.5,
        textColor=INK, spaceAfter=5,
    ),
    "small": ParagraphStyle(
        "Small", parent=BASE_STYLES["BodyText"], fontSize=7.1, leading=9.4,
        textColor=MID, spaceAfter=3,
    ),
    "table": ParagraphStyle(
        "Table", parent=BASE_STYLES["BodyText"], fontSize=6.8, leading=8.4,
        textColor=INK,
    ),
    "table_header": ParagraphStyle(
        "TableHeader", parent=BASE_STYLES["BodyText"], fontName="Helvetica-Bold",
        fontSize=6.7, leading=8, textColor=colors.white,
    ),
    "card": ParagraphStyle(
        "Card", parent=BASE_STYLES["BodyText"], fontSize=8, leading=10.8,
        textColor=INK,
    ),
    "center_small": ParagraphStyle(
        "CenterSmall", parent=BASE_STYLES["BodyText"], fontSize=6.8, leading=8.4,
        textColor=INK, alignment=TA_CENTER,
    ),
}


def para(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, STYLE[style])


def table_cell(value: Any, header: bool = False, center: bool = False) -> Paragraph:
    style = "table_header" if header else "center_small" if center else "table"
    return para(escape(value), style)


def audit_table(
    rows: list[list[Any]],
    widths: list[float],
    *,
    centered_columns: set[int] | None = None,
) -> Table:
    centered_columns = centered_columns or set()
    rendered = [
        [table_cell(value, header=True) for value in rows[0]],
        *[
            [table_cell(value, center=index in centered_columns) for index, value in enumerate(row)]
            for row in rows[1:]
        ],
    ]
    table = Table(rendered, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, NAVY),
        ("LINEBELOW", (0, 1), (-1, -2), 0.35, LIGHT),
    ]
    for row_index in range(1, len(rows)):
        if row_index % 2 == 0:
            style.append(("BACKGROUND", (0, row_index), (-1, row_index), WASH))
    table.setStyle(TableStyle(style))
    return table


class StatStrip(Flowable):
    def __init__(self, items: list[tuple[str, str]]):
        super().__init__()
        self.items = items
        self.height = 58

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        self.width = available_width
        return self.width, self.height

    def draw(self) -> None:
        canvas = self.canv
        gap = 7
        tile_width = (self.width - gap * (len(self.items) - 1)) / len(self.items)
        for index, (value, label) in enumerate(self.items):
            x = index * (tile_width + gap)
            canvas.setFillColor(PALE_BLUE if index < 3 else WASH)
            canvas.setStrokeColor(LIGHT)
            canvas.roundRect(x, 0, tile_width, self.height, 5, fill=1, stroke=1)
            canvas.setFillColor(NAVY)
            canvas.setFont("Helvetica-Bold", 18)
            canvas.drawCentredString(x + tile_width / 2, 29, value)
            canvas.setFillColor(MID)
            canvas.setFont("Helvetica-Bold", 6.4)
            canvas.drawCentredString(x + tile_width / 2, 13, label.upper())


class CoverageChart(Flowable):
    def __init__(self, series: list[tuple[str, list[float], Any, bool]]):
        super().__init__()
        self.series = series
        self.height = 205

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        self.width = available_width
        return self.width, self.height

    def draw(self) -> None:
        canvas = self.canv
        left, right, bottom, top = 36, 8, 58, 12
        plot_width = self.width - left - right
        plot_height = self.height - bottom - top
        canvas.setFont("Helvetica", 6.5)
        for value in (0, 25, 50, 75, 100):
            y = bottom + plot_height * value / 100
            canvas.setStrokeColor(LIGHT)
            canvas.setLineWidth(0.5)
            canvas.line(left, y, left + plot_width, y)
            canvas.setFillColor(MID)
            canvas.drawRightString(left - 6, y - 2, str(value))
        for epoch in range(4):
            x = left + plot_width * epoch / 3
            canvas.setFillColor(MID)
            canvas.drawCentredString(x, bottom - 13, f"E{epoch}")

        for label, values, color, dashed in self.series:
            if len(values) < 2:
                continue
            canvas.setStrokeColor(color)
            canvas.setFillColor(colors.white)
            canvas.setLineWidth(1.8)
            canvas.setDash(4, 2) if dashed else canvas.setDash()
            points = [
                (left + plot_width * index / 3, bottom + plot_height * value / 100)
                for index, value in enumerate(values[:4])
            ]
            for first, second in zip(points, points[1:]):
                canvas.line(first[0], first[1], second[0], second[1])
            for x, y in points:
                canvas.circle(x, y, 2.2, fill=1, stroke=1)
            canvas.setDash()

        columns = 3
        column_width = self.width / columns
        for index, (label, _values, color, dashed) in enumerate(self.series):
            row, column = divmod(index, columns)
            x = column * column_width + 6
            y = 34 - row * 13
            canvas.setStrokeColor(color)
            canvas.setLineWidth(1.8)
            canvas.setDash(4, 2) if dashed else canvas.setDash()
            canvas.line(x, y, x + 16, y)
            canvas.setDash()
            canvas.setFillColor(INK)
            canvas.setFont("Helvetica", 6.5)
            available = column_width - 28
            text = label
            while stringWidth(text, "Helvetica", 6.5) > available and len(text) > 4:
                text = text[:-2]
            if text != label:
                text = text.rstrip() + "..."
            canvas.drawString(x + 21, y - 2.2, text)


class AuditDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str):
        super().__init__(
            filename,
            pagesize=letter,
            leftMargin=0.5 * inch,
            rightMargin=0.5 * inch,
            topMargin=0.52 * inch,
            bottomMargin=0.48 * inch,
            title="Question Atlas quantitative run audit",
            author="Question Atlas",
            subject="Descriptive analysis of saved Question Atlas pipeline runs",
        )
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="normal",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(PageTemplate(id="audit", frames=[frame], onPage=draw_page_chrome))


def draw_page_chrome(canvas: Any, document: AuditDocTemplate) -> None:
    canvas.saveState()
    if document.page > 1:
        canvas.setFillColor(NAVY)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawString(document.leftMargin, letter[1] - 22, "QUESTION ATLAS / QUANTITATIVE RUN AUDIT")
        canvas.setStrokeColor(LIGHT)
        canvas.line(document.leftMargin, letter[1] - 27, letter[0] - document.rightMargin, letter[1] - 27)
    canvas.setStrokeColor(LIGHT)
    canvas.line(document.leftMargin, 25, letter[0] - document.rightMargin, 25)
    canvas.setFillColor(MID)
    canvas.setFont("Helvetica", 6.4)
    canvas.drawString(document.leftMargin, 15, "Source: saved local run artifacts. Descriptive analysis; no human ground truth.")
    canvas.drawRightString(letter[0] - document.rightMargin, 15, str(document.page))
    canvas.restoreState()


def finding_cards(items: list[tuple[str, str]]) -> Table:
    cells = [
        para(f"<b>{escape(title)}</b><br/>{escape(body)}", "card")
        for title, body in items
    ]
    rows = [cells[index : index + 2] for index in range(0, len(cells), 2)]
    table = Table(rows, colWidths=[266, 266], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WASH),
                ("BOX", (0, 0), (-1, -1), 0.5, LIGHT),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def inventory_rows(runs: list[RunAudit]) -> list[list[Any]]:
    rows: list[list[Any]] = [
        ["Run", "Condition", "Status", "Min", "Paras", "Groups", "Coverage", "Orphans"]
    ]
    for run in runs:
        final = run.final
        suffix = "*" if run.is_partial else ""
        status = "complete" if run.is_complete else "failed E3" if run.is_partial else "failed"
        condition = CONDITION_NAMES[run.condition_key]
        if run.is_partial:
            condition += " attempt"
        rows.append(
            [
                short_run_id(run.run_id),
                condition,
                status,
                f"{run.runtime_minutes:.1f}" if run.runtime_minutes is not None else "-",
                final.total if final else "-",
                f"{final.group_count}{suffix}" if final else "-",
                f"{final.coverage:.1f}%{suffix}" if final else "-",
                f"{len(final.unassigned)}{suffix}" if final else "-",
            ]
        )
    return rows


def build_story(runs: list[RunAudit], runs_dir: Path) -> list[Any]:
    complete = [run for run in runs if run.is_complete]
    failed = [run for run in runs if not run.is_complete]
    conditions = latest_complete_by_condition(runs)
    final_coverages = [run.final.coverage for run in complete if run.final]
    modern_groups = [
        run.final.group_count
        for run in complete
        if run.final and run.condition_key not in {"legacy"}
    ]

    question_only = conditions["question_only"]
    fixed_section = conditions["fixed_section"]
    full_paper = conditions["full_paper"]
    representative = conditions["representative"]
    all_evidence = conditions["all_evidence"]
    baseline = conditions["baseline"]
    fixed_stats = relabel_stats(fixed_section, runs_dir)
    full_stats = relabel_stats(full_paper, runs_dir)

    story: list[Any] = [
        para("QUESTION ATLAS / RUN AUDIT", "kicker"),
        para("Quantitative analysis of all saved pipeline runs", "title"),
        para(
            "A descriptive audit of every operational run saved through August 4, 2026. "
            "The report separates infrastructure failures, the legacy non-monotonic prototype, "
            "fresh runs, fixed-corpus labeling treatments, and controlled assignment-evidence treatments.",
            "subtitle",
        ),
        StatStrip(
            [
                (str(len(runs)), "operational runs"),
                (str(len(complete)), "completed"),
                (str(len(failed)), "failed"),
                (f"{min(final_coverages):.0f}-{max(final_coverages):.0f}%", "final coverage range"),
                (f"{min(modern_groups)}-{max(modern_groups)}", "modern final groups"),
            ]
        ),
        Spacer(1, 10),
        para("Executive findings", "h1"),
        finding_cards(
            [
                (
                    "1. Assignment evidence forms a breadth gradient.",
                    f"With an identical pre-epoch state, final coverage was {question_only.final.coverage:.1f}% with questions only, "
                    f"{representative.final.coverage:.1f}% with representative paragraphs, and {all_evidence.final.coverage:.1f}% with every group paragraph.",
                ),
                (
                    "2. Full-paper labels changed topology more than coverage.",
                    f"On the same 323 fixed paragraphs, fixed-section and full-paper labels ended at {fixed_section.final.coverage:.1f}% and "
                    f"{full_paper.final.coverage:.1f}% coverage, but at {fixed_section.final.group_count} versus {full_paper.final.group_count} groups.",
                ),
                (
                    "3. Representative evidence is the middle condition.",
                    f"It retained {assignment_overlap(question_only, representative):.1f}% final-assignment Jaccard overlap with question-only assignment, "
                    f"versus {assignment_overlap(question_only, all_evidence):.1f}% for all group evidence, while leaving 40 rather than 78 orphans.",
                ),
                (
                    "4. These are behavior measurements, not quality scores.",
                    "Coverage, group count, and overlap show how the pipeline behaves. No run establishes whether assignments or analogies are conceptually correct.",
                ),
            ]
        ),
        Spacer(1, 10),
        para("Run inventory", "h1"),
        audit_table(
            inventory_rows(runs),
            [67, 146, 54, 31, 38, 39, 53, 43],
            centered_columns={2, 3, 4, 5, 6, 7},
        ),
        Spacer(1, 5),
        para(
            "* Partial values are the last durable E2 snapshot from the failed representative-evidence attempt, not a final outcome. "
            "The completed representative run has the same configuration and identical E0-E2 results, so the failed attempt is not an independent replicate.",
            "small",
        ),
        PageBreak(),
        para("What each condition means", "h1"),
        para(
            "The condition name is shorthand for which information was held fixed and which information Claude received. "
            "The definitions below are part of the analysis, not merely run labels.",
            "body",
        ),
    ]

    guide_rows = [["Condition", "Plain-language definition"]]
    guide_order = [
        "bootstrap",
        "legacy",
        "baseline",
        "question_only",
        "fixed_section",
        "full_paper",
        "representative",
        "all_evidence",
    ]
    for condition_key in guide_order:
        guide_rows.append([CONDITION_NAMES[condition_key], CONDITION_DESCRIPTIONS[condition_key]])
    story.extend(
        [
            audit_table(guide_rows, [132, 400]),
            Spacer(1, 12),
            para("Controlled comparison structure", "h1"),
            finding_cards(
                [
                    (
                        "Label-context comparison",
                        "Fixed-section and full-paper labels reuse identical paragraph ids, text, order, sections, and relations. Both use question-only orphan assignment. Only the context used to regenerate paragraph questions differs.",
                    ),
                    (
                        "Assignment-evidence comparison",
                        "Question-only, representative evidence, and all group evidence share the exact same pre-epoch files. The assignment prompt's view of existing group members is the controlled difference.",
                    ),
                    (
                        "Fresh-run comparison",
                        "The monotonic baseline and question-only replication reran extraction from PDFs. Their paragraph corpora differ, so they measure end-to-end instability rather than a clean prompt ablation.",
                    ),
                    (
                        "Failure accounting",
                        "Both failed runs remain in the inventory. A failed run counts operationally but contributes no final treatment outcome; a durable partial epoch is marked explicitly.",
                    ),
                ]
            ),
            Spacer(1, 10),
            para("How to read the metrics", "h1"),
            para(
                "<b>Coverage</b> is the percentage of extracted paragraphs assigned to at least one group. "
                "<b>Memberships</b> count every many-to-many placement. <b>Multi</b> counts paragraphs present in more than one group. "
                "<b>Orphans</b> are paragraphs assigned to no group. Fewer groups indicate broader aggregation, not necessarily a better abstraction.",
                "body",
            ),
            PageBreak(),
            para("Coverage across epochs", "h1"),
            para(
                "E0 is the initial state; E1-E3 are refinement epochs. Current append-only runs can only gain coverage. "
                "The dashed legacy series can lose coverage because it reassigned every paragraph at each epoch.",
                "body",
            ),
        ]
    )

    series_specs = [
        ("legacy", "Legacy reassignment", MID, True),
        ("baseline", "Monotonic baseline", NAVY, False),
        ("question_only", "Question-only replication", BLUE, False),
        ("fixed_section", "Fixed-section labels", GREEN, False),
        ("full_paper", "Full-paper labels", GOLD, False),
        ("representative", "Representative evidence", ORANGE, False),
        ("all_evidence", "All group evidence", RED, False),
    ]
    coverage_series = [
        (
            label,
            [snapshot.coverage for snapshot in conditions[key].snapshots],
            color,
            dashed,
        )
        for key, label, color, dashed in series_specs
    ]
    story.append(CoverageChart(coverage_series))
    story.extend([Spacer(1, 5), para("Run dynamics", "h1")])

    dynamics_rows: list[list[Any]] = [
        ["Condition", "Coverage path (%)", "Group-count path", "Net unique assigned", "Final memberships", "Multi"]
    ]
    for key, label, _color, _dashed in series_specs:
        run = conditions[key]
        coverage_path = " / ".join(f"{snapshot.coverage:.1f}" for snapshot in run.snapshots)
        group_path = " / ".join(str(snapshot.group_count) for snapshot in run.snapshots)
        net = [
            len(current.assigned) - len(previous.assigned)
            for previous, current in zip(run.snapshots, run.snapshots[1:])
        ]
        dynamics_rows.append(
            [
                label,
                coverage_path,
                group_path,
                " / ".join(f"{value:+d}" for value in net),
                run.final.memberships,
                run.final.multi_assigned,
            ]
        )
    story.extend(
        [
            audit_table(
                dynamics_rows,
                [112, 133, 91, 94, 60, 42],
                centered_columns={1, 2, 3, 4, 5},
            ),
            Spacer(1, 7),
            para(
                f"Most assignments occurred in E1, but later epochs mattered for the context-heavy conditions. "
                f"Full-paper labels added 176, 70, and 25 unique paragraphs across E1-E3; representative evidence added 123, 46, and 33. "
                f"The fixed-section condition nearly saturated by E2, adding only one paragraph in E3.",
                "body",
            ),
            PageBreak(),
            para("Controlled comparisons", "h1"),
            para("A. Assignment evidence: what existing group content does Claude see?", "h2"),
            para(
                "All three runs copy the question-only replication's pre-epoch artifacts byte-for-byte. "
                "The orphan paragraph is always supplied in full; the treatment changes only the evidence attached to candidate group questions.",
                "body",
            ),
        ]
    )

    evidence_rows: list[list[Any]] = [
        ["Condition", "Existing group-member text supplied", "Evidence chars E1/E2/E3", "Coverage", "Orphans", "Groups", "Multi", "Jaccard vs Q-only"]
    ]
    for key, description in [
        ("question_only", "None; group question only"),
        ("representative", "TF-IDF medoids; max 2/paper, 6/group"),
        ("all_evidence", "Every paragraph already assigned to group"),
    ]:
        run = conditions[key]
        chars = evidence_characters(run)
        evidence_rows.append(
            [
                CONDITION_NAMES[key],
                description,
                " / ".join(f"{value / 1000:.0f}k" for value in chars),
                f"{run.final.coverage:.1f}%",
                len(run.final.unassigned),
                run.final.group_count,
                run.final.multi_assigned,
                f"{assignment_overlap(question_only, run):.1f}%",
            ]
        )
    story.extend(
        [
            audit_table(
                evidence_rows,
                [85, 150, 82, 45, 39, 35, 31, 65],
                centered_columns={2, 3, 4, 5, 6, 7},
            ),
            Spacer(1, 6),
            para(
                f"Coverage declines from {question_only.final.coverage:.1f}% to {representative.final.coverage:.1f}% to {all_evidence.final.coverage:.1f}% as existing-member evidence becomes richer. "
                f"Representative evidence preserves 279 of the question-only run's final assignments and adds 4 not present there; all group evidence preserves 239 and adds 6. "
                "Both evidence-aware treatments produced zero many-to-many assignments. This pattern is consistent with more conservative assignment, but one run per treatment cannot identify why.",
                "body",
            ),
            para("B. Paragraph-question context: section versus complete paper", "h2"),
            para(
                "The strict comparison is fixed-section versus full-paper: both preserve the same 323 paragraph units and rerun downstream stages with question-only assignment.",
                "body",
            ),
        ]
    )

    context_rows = [
        ["Condition", "Question-label context", "Labels changed", "Mean question words", "E0 groups / coverage", "Final groups / coverage", "Orphans"],
        [
            "Question-only replication",
            "Fresh section extraction; boundaries and labels regenerated",
            "not fixed",
            f"{fixed_stats['old_words']:.1f}",
            f"{question_only.snapshots[0].group_count} / {question_only.snapshots[0].coverage:.1f}%",
            f"{question_only.final.group_count} / {question_only.final.coverage:.1f}%",
            len(question_only.final.unassigned),
        ],
        [
            "Fixed-section labels",
            "Fixed units; complete containing section",
            f"{fixed_stats['changed']}/{fixed_stats['total']}",
            f"{fixed_stats['new_words']:.1f}",
            f"{fixed_section.snapshots[0].group_count} / {fixed_section.snapshots[0].coverage:.1f}%",
            f"{fixed_section.final.group_count} / {fixed_section.final.coverage:.1f}%",
            len(fixed_section.final.unassigned),
        ],
        [
            "Full-paper labels",
            "Fixed units; complete paper",
            f"{full_stats['changed']}/{full_stats['total']}",
            f"{full_stats['new_words']:.1f}",
            f"{full_paper.snapshots[0].group_count} / {full_paper.snapshots[0].coverage:.1f}%",
            f"{full_paper.final.group_count} / {full_paper.final.coverage:.1f}%",
            len(full_paper.final.unassigned),
        ],
    ]
    story.extend(
        [
            audit_table(
                context_rows,
                [92, 135, 62, 62, 67, 73, 43],
                centered_columns={2, 3, 4, 5, 6},
            ),
            Spacer(1, 6),
            para(
                f"Fixed-section and full-paper labels end with nearly the same coverage ({fixed_section.final.coverage:.1f}% versus {full_paper.final.coverage:.1f}%), "
                f"yet full-paper context halves the final group count from {fixed_section.final.group_count} to {full_paper.final.group_count}. "
                f"It also produces longer questions on average ({full_stats['new_words']:.1f} versus {fixed_stats['new_words']:.1f} words). "
                "This supports a strong context effect on clustering topology, not a claim that broader clusters are more correct.",
                "body",
            ),
            para("C. Reproducibility and failed attempts", "h2"),
            para(
                f"The monotonic baseline extracted {baseline.final.total} paragraphs and ended at {baseline.final.coverage:.1f}% coverage in {baseline.final.group_count} groups. "
                f"The fresh question-only replication extracted {question_only.final.total} and ended at {question_only.final.coverage:.1f}% in {question_only.final.group_count} groups. "
                "Because extraction and labels were regenerated and the harness changed, this is end-to-end instability rather than a clean repeatability estimate. "
                "The failed representative-evidence attempt reached E2 at 77.4% coverage before refine_epochs.py exited non-zero; its completed replacement reused identical cached E0-E2 outputs, so it is recovery evidence, not an independent replicate.",
                "body",
            ),
            para("What the current runs support", "h2"),
            finding_cards(
                [
                    (
                        "Supported",
                        "Append-only assignment makes coverage monotonic. Labeling context materially changes group topology. Supplying existing group paragraphs suppresses assignment breadth, with representative evidence intermediate between question-only and all-evidence prompts.",
                    ),
                    (
                        "Not established",
                        "Higher coverage is not higher accuracy. Fewer groups are not necessarily better analogies. One run per controlled treatment cannot separate prompt effects from model stochasticity or cache-path effects.",
                    ),
                ]
            ),
            Spacer(1, 8),
            para("Recommended next technical evaluation", "h2"),
            para(
                "Freeze one paragraph corpus and one pre-epoch state, clear treatment-specific caches, and run at least five independent replicates of question-only, representative-evidence, and all-group-evidence assignment. "
                "Human-label a stratified sample of assigned and orphan paragraphs. Report assignment precision and recall, top-1 agreement, orphan correctness, group coherence, analogical-role agreement, and between-run stability alongside coverage and group count.",
                "body",
            ),
        ]
    )
    return story


def build_report(runs_dir: Path, output_path: Path) -> list[RunAudit]:
    runs = load_runs(runs_dir)
    if not runs:
        raise RuntimeError(f"No analysis_run.json files found under {runs_dir}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = AuditDocTemplate(str(output_path))
    document.build(build_story(runs, runs_dir))
    return runs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runs = build_report(args.runs_dir.resolve(), args.output.resolve())
    complete = sum(run.is_complete for run in runs)
    failed = len(runs) - complete
    print(f"Wrote {args.output.resolve()} from {len(runs)} runs ({complete} complete, {failed} failed).")


if __name__ == "__main__":
    main()
