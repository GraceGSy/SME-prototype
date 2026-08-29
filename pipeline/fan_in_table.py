"""Tiny, schema-agnostic markdown renderer shared by `ClosestMatchGraph.
fan_in_correspondence_table()` and `ParagraphMatchGraph.fan_in_correspondence_table()`.

This module knows nothing about sections, subsections, or paragraphs -- it only turns
row dicts of the shape {"cells": {paper_id: [(label, is_confirmed), ...]}, ...} into a
two-column (or N-column) markdown table string, bolding confirmed entries. Deliberately
kept separate from both graph classes: the two `fan_in_correspondence_table()` methods
differ in real, non-mechanical ways (unit labeling, whether a `redundant_edges()`-style
filter applies, row-sort convention), so unifying THAT logic isn't warranted -- but
turning a list of (label, bool) tuples into markdown cells is genuinely shared,
presentation-only logic with no coupling to either class's unit schema.
"""
from __future__ import annotations

from typing import Any


def render_correspondence_table_markdown(
    rows: list[dict[str, Any]],
    paper_order: list[str],
) -> str:
    """rows: each a dict with a "cells" key, {paper_id: [(label, is_bidirectional), ...]}
    (as produced by either graph class's `fan_in_correspondence_table()`). paper_order:
    the paper_ids in the order they should appear as columns -- the caller's choice
    (e.g. sorted by one paper's own document order); this function has no opinion on
    row or column order, and does not sort or reorder `rows` itself.

    A cell missing from a row renders empty. Within a cell, entries are joined with
    ", " in whatever order they already appear in that row's list -- sorting (if any)
    is each `fan_in_correspondence_table()` caller's responsibility, not this
    function's, since the right sort key differs by unit type (paragraph number vs.
    section document order) and even by class (see each method's own docstring)."""
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
