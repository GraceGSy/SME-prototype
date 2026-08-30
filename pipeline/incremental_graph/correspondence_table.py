"""Render structured correspondence rows as human-readable Markdown tables."""
from __future__ import annotations

from typing import Any


def render_correspondence_table_markdown(
    rows: list[dict[str, Any]],
    paper_order: list[str],
) -> str:
    """Render rows whose cells contain ordered ``(label, is_reciprocal)`` pairs."""
    header = "| " + " | ".join(paper_order) + " |"
    sep = "|" + "|".join("---" for _ in paper_order) + "|"
    lines = [header, sep]
    for row in rows:
        cells = row.get("cells", {})
        formatted = []
        for pid in paper_order:
            entries = cells.get(pid, [])
            formatted.append(
                ", ".join(f"**{label}**" if is_bidirectional else label for label, is_bidirectional in entries)
            )
        lines.append("| " + " | ".join(formatted) + " |")
    return "\n".join(lines)


def render_correspondence_report_markdown(
    report: dict[str, Any],
    paper_order: list[str],
) -> str:
    """Render section and paragraph correspondence rows from one exported report."""

    sections = []
    for level in ("section", "paragraph"):
        title = "Sections and subsections" if level == "section" else "Paragraphs"
        table = render_correspondence_table_markdown(report["levels"][level], paper_order)
        sections.append(f"## {title}\n\n{table}")
    return "# Structural rerepresentation and paragraph correspondences\n\n" + "\n\n".join(sections) + "\n"
