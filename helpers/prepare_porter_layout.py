"""One-time Porter source refresh retaining PDF indentation for legal extraction.

Run with a Python environment containing pdfplumber. This does not infer or
split paragraphs; the existing extraction Skill receives the printed layout.
"""

import hashlib
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
PDF = (
    ROOT.parent.parent
    / "legal corpus/Porter v. Board of Trustees of North Carolina State University/221712_opinion_Thacker.pdf"
)
OUTPUT = ROOT / "output/porter-extraction-20260910/porter_opinion.layout.txt"


def prepare() -> None:
    if OUTPUT.exists():
        raise FileExistsError("Refusing to overwrite the prepared layout input")
    pages = []
    with pdfplumber.open(PDF) as document:
        if len(document.pages) != 17:
            raise ValueError("Expected the opinion-only PDF covering printed pages 3-19")
        for number, page in enumerate(document.pages, 3):
            lines = [line.rstrip() for line in page.extract_text(layout=True).splitlines()]
            while lines and not lines[-1]:
                lines.pop()
            if not lines or lines.pop().strip() != str(number):
                raise ValueError(f"Unexpected footer on printed page {number}")
            # Remove only outer blank lines, never paragraph indentation.
            while lines and not lines[0]:
                lines.pop(0)
            while lines and not lines[-1]:
                lines.pop()
            pages.append("\n".join(lines))
    text = "\n\f\n".join(pages) + "\n"
    if "\ufffd" in text or not text.rstrip().endswith("AFFIRMED."):
        raise ValueError("Source encoding or final disposition needs inspection")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"Prepared {len(pages)} pages: {OUTPUT}")
    print(f"PDF SHA-256: {hashlib.sha256(PDF.read_bytes()).hexdigest()}")
    print(f"Text SHA-256: {hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    prepare()
