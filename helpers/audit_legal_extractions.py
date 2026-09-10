"""Offline legal extraction triage against the ten opinion/dissent PDFs.

Requires pdfplumber. Reports potential boundary/content problems, never repairs
inputs or calls a model. Indented lines are review candidates, not infallible
paragraph labels: quotations and footnotes can also be indented.
"""

import json
import re
import unicodedata
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "datasets/legal"
PDF_ROOT = ROOT.parent.parent / "legal corpus"
CASES = {
    "banuelos_jimenez": "Banuelos-Jimenez v. Garland",
    "core_optical": "Core Optical Technologies, LLC v. Nokia Corporation",
    "lamb": "Lamb v. Kendrick",
    "porter": "Porter v. Board of Trustees of North Carolina State University",
    "westmoreland": "Westmoreland v. Butler County",
}


def compact(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def prefix(text: str) -> str:
    text = re.sub(r"^\d+\s*", "", text)
    text = re.sub(r"^.*?Circuit Judge,? dissenting\.\s*", "", text)
    return compact(" ".join(text.split()[:8]))


def audit(case: str, kind: str) -> dict:
    paper_id = f"{case}_{kind}"
    paths = list((PDF_ROOT / CASES[case]).glob(f"*_{kind}_*.pdf"))
    if len(paths) != 1:
        raise ValueError(f"Expected one source PDF for {paper_id}")
    document = json.loads((CORPUS / f"content/{paper_id}.content.json").read_text(encoding="utf-8"))
    units = [u for section in document for u in [section, *section["subsections"]]]
    paragraphs = [p["text"] for u in units for p in u["paragraphs"]]
    content = [compact(p) for p in paragraphs]
    starts = [compact(re.sub(r"^\d+\s*", "", p)) for p in paragraphs]
    raw = (CORPUS / f"raw/{paper_id}.txt").read_text(encoding="utf-8")
    raw_compact = compact(raw)
    heading_text = compact(
        " ".join(f"{u['section_number'] or ''} {u['section_name']}" for u in units)
    )
    all_content = "".join(content)
    missing_raw_lines = [
        line.strip()
        for line in raw.splitlines()
        if len(line.split()) >= 8
        and prefix(line.strip()) not in all_content
        and prefix(line.strip()) not in heading_text
    ]
    anchors, headings, page_tails = [], [], []
    indent = 166 if case == "core_optical" else 108
    with pdfplumber.open(paths[0]) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            lines = page.extract_text_lines()
            page_tails.append(
                {"pdf_page": page_number, "last_lines": [line["text"] for line in lines[-3:]]}
            )
            for line in lines:
                text = line["text"]
                heading = re.fullmatch(r"([IVX]+|[A-Z])(?:\.|\.?\s+.+)?", text.strip())
                if heading:
                    headings.append({"pdf_page": page_number, "marker": heading[1]})
                if abs(line["x0"] - indent) > 2 or len(text.split()) < 6:
                    continue
                # Use a short source line prefix so a wrap-hyphen at its end
                # can match the same word rejoined in the extracted paragraph.
                key = prefix(text)
                at_start = [i for i, p in enumerate(starts) if p.startswith(key)]
                anywhere = [i for i, p in enumerate(content) if key in p]
                anchors.append(
                    {
                        "pdf_page": page_number,
                        "top": round(line["top"], 1),
                        "text": text,
                        "at_paragraph_start": at_start,
                        "inside_paragraph": anywhere,
                        "in_prepared_raw": key in raw_compact,
                        "in_heading": key in heading_text,
                    }
                )
    tail_key = compact(" ".join(raw.split()[-8:]))
    pdf_final_line = next(
        line
        for line in reversed(page_tails[-1]["last_lines"])
        if line.strip() and not re.fullmatch(r"\d+", line.strip())
    )
    duplicated_paragraphs = [
        index
        for index, p in enumerate(content)
        if len(p) >= 80 and 0 < raw_compact.count(p) < all_content.count(p)
    ]
    return {
        "paper_id": paper_id,
        "pdf": str(paths[0]),
        "paragraph_count": len(paragraphs),
        "word_count": sum(len(p.split()) for p in paragraphs),
        "max_paragraph_words": max(len(p.split()) for p in paragraphs),
        "headings_in_content": [
            u["section_number"] for u in units if u["section_number"] is not None
        ],
        "headings_in_pdf": headings,
        "final_raw_passage_present": tail_key in all_content,
        "final_pdf_line": pdf_final_line,
        "final_pdf_passage_present": prefix(pdf_final_line) in all_content,
        "duplicated_paragraph_candidates": duplicated_paragraphs,
        "raw_line_prefixes_missing_from_content": missing_raw_lines,
        "indented_lines": len(anchors),
        "matched_starts": sum(bool(a["at_paragraph_start"]) for a in anchors),
        "possible_merged_starts": [
            a for a in anchors if not a["at_paragraph_start"] and a["inside_paragraph"]
        ],
        "missing_starts": [
            a
            for a in anchors
            if not a["inside_paragraph"] and not a["in_heading"] and a["in_prepared_raw"]
        ],
        "all_anchors": anchors,
        "page_tails": page_tails,
    }


def main() -> None:
    reports = []
    for case in CASES:
        for kind in ("opinion", "dissent"):
            result = audit(case, kind)
            reports.append(result)
            print(
                json.dumps(
                    {
                        key: result[key]
                        for key in (
                            "paper_id",
                            "paragraph_count",
                            "max_paragraph_words",
                            "indented_lines",
                            "matched_starts",
                            "final_raw_passage_present",
                        )
                    }
                ),
                flush=True,
            )
            print(
                "  merged candidates:",
                len(result["possible_merged_starts"]),
                "missing candidates:",
                len(result["missing_starts"]),
                flush=True,
            )
    output = ROOT / "output/legal-extraction-audit-20260910.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(reports, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
