"""Shared helper: locate a short marker string inside a larger text and slice
the text into consecutive chunks between markers found in order. Used both to
locate section headings in a paper's raw text, and to locate paragraph start
markers inside a section's own text -- same problem at different scales.
"""
from __future__ import annotations

import re


def find_marker(text: str, marker: str, start_from: int) -> int | None:
    """Locate `marker` in `text` at or after `start_from`. Tries the marker as
    given, then with any leading numbering ("4.", "4)") stripped, joining
    words with \\s* so extraction-time spacing quirks don't break the match."""
    candidates = [marker]
    stripped = re.sub(r"^[\d.\)\s]+", "", marker).strip()
    if stripped and stripped != marker:
        candidates.append(stripped)

    for candidate in candidates:
        tokens = candidate.split()
        if not tokens:
            continue
        pattern = r"\s*".join(re.escape(t) for t in tokens)
        m = re.search(pattern, text[start_from:], re.IGNORECASE)
        if m:
            return start_from + m.start()
    return None


def slice_by_markers(text: str, markers: list[str]) -> list[str | None]:
    """Given markers expected to occur in order in `text`, return the slice of
    text from each marker's start to the next found marker's start (or end of
    text for the last one). None where a marker couldn't be located."""
    positions: list[int | None] = []
    cursor = 0
    for marker in markers:
        pos = find_marker(text, marker, cursor)
        positions.append(pos)
        if pos is not None:
            cursor = pos + 1  # next marker must be found strictly after this one starts

    slices: list[str | None] = []
    for i, start in enumerate(positions):
        if start is None:
            slices.append(None)
            continue
        end = len(text)
        for j in range(i + 1, len(positions)):
            if positions[j] is not None:
                end = positions[j]
                break
        slices.append(text[start:end].strip())
    return slices
