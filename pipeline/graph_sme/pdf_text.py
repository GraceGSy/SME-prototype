"""PDF -> plain text extraction, column-aware.

Plain pdfplumber `extract_text()` orders words purely by vertical position,
which interleaves left- and right-column text on a two-column academic paper
(the common ACM/CHI/UIST template) -- headings and sentences end up split and
re-glued mid-word. This reconstructs true reading order per page: any
full-width line (title, byline, abstract box) stays in place, then the left
column top-to-bottom, then the right column top-to-bottom.

The tricky part: a left-column line and the right-column line at the same
height often share almost the same `top` coordinate (both columns sit on the
same baseline grid), so grouping words into rows by `top` alone silently
glues one line from each column into a single fake "row". The fix is to
look for the column-gutter gap -- a horizontal gap much wider than normal
word-spacing, straddling the page's midpoint -- and split a row there before
deciding what's full-width vs. left/right.
"""
from __future__ import annotations

import pdfplumber

FULL_WIDTH_FRACTION = 0.6  # a line spanning more than this fraction of the page is "full-width"
LINE_TOLERANCE = 3  # points; words within this are considered the same row, before gutter-splitting
GUTTER_MIN_GAP = 15  # points; a gap at least this wide (and >> the row's typical word-spacing) is a column gutter, not a space

WORD_X_TOLERANCE = 1.5  # pdfplumber's default (3) glues adjacent words together on some PDFs'
# justified-text encodings (no real space glyph, just a small gap); tightening this splits
# them back into real words without breaking normal letter-spacing within a word.


def _split_at_gutter(row_words: list, mid_x: float) -> list[list]:
    """If `row_words` (sorted by x0) actually contains one line from each column
    glued together at the same height, split them apart at the gutter gap."""
    if len(row_words) < 2:
        return [row_words]
    gaps = [row_words[i]["x0"] - row_words[i - 1]["x1"] for i in range(1, len(row_words))]
    max_gap = max(gaps)
    split_at = gaps.index(max_gap) + 1
    other_gaps = gaps[:split_at - 1] + gaps[split_at:]
    typical_gap = sorted(other_gaps)[len(other_gaps) // 2] if other_gaps else 0
    straddles_mid = row_words[0]["x0"] < mid_x < row_words[split_at]["x0"]
    if max_gap >= max(GUTTER_MIN_GAP, typical_gap * 4) and straddles_mid:
        return [row_words[:split_at], row_words[split_at:]]
    return [row_words]


def _page_text_in_reading_order(page) -> str:
    words = page.extract_words(x_tolerance=WORD_X_TOLERANCE)
    if not words:
        return ""
    mid_x = page.width / 2

    rows: dict[int, list] = {}
    for w in words:
        key = round(w["top"] / LINE_TOLERANCE)
        rows.setdefault(key, []).append(w)

    left_lines: list[tuple[float, str]] = []
    right_lines: list[tuple[float, str]] = []
    for key in rows:
        row_words = sorted(rows[key], key=lambda w: w["x0"])
        for line_words in _split_at_gutter(row_words, mid_x):
            top = min(w["top"] for w in line_words)
            x0 = min(w["x0"] for w in line_words)
            x1 = max(w["x1"] for w in line_words)
            text = " ".join(w["text"] for w in line_words)
            if (x1 - x0) > FULL_WIDTH_FRACTION * page.width:
                left_lines.append((top, text))  # full-width lines ride with the earlier stream
            else:
                avg_x = sum(w["x0"] for w in line_words) / len(line_words)
                (left_lines if avg_x < mid_x else right_lines).append((top, text))

    left_lines.sort(key=lambda t: t[0])
    right_lines.sort(key=lambda t: t[0])
    return "\n".join(text for _, text in left_lines + right_lines)


def extract_pdf_text(path: str, max_pages: int | None = None) -> str:
    texts: list[str] = []
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        for page in pages:
            texts.append(_page_text_in_reading_order(page))
    return "\n\n".join(texts)
