"""One-time layout inputs for the three audited dissent repairs; no API calls.

Verified PDF-specific running headers/footers are removed. Body indentation,
footnotes and page breaks remain for the unchanged native extraction Skill.
Requires pdfplumber. Refuses to overwrite prepared inputs.
"""

import hashlib
import re
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/dissent-extraction-20260910"
SOURCES = {
    "banuelos_jimenez": (
        "Banuelos-Jimenez v. Garland/23a0097p-06_dissent_Gilman.pdf",
        8,
        14,
        "GILMAN, Circuit Judge",
        "No. 22-3331",
    ),
    "porter": (
        "Porter v. Board of Trustees of North Carolina State University/221712_dissent_Richardson.pdf",
        20,
        43,
        "RICHARDSON, Circuit Judge",
        None,
    ),
    "westmoreland": (
        "Westmoreland v. Butler County/22a0053p-06_dissent_Bush.pdf",
        13,
        33,
        "JOHN K. BUSH, Circuit Judge",
        "No. 21-5168",
    ),
}


def prepare():
    for case, (relative, first, last, author, header) in SOURCES.items():
        source = ROOT.parent.parent / "legal corpus" / relative
        target = OUTPUT / f"{case}_dissent.layout.txt"
        if target.exists():
            raise FileExistsError(target)
        pages = []
        with pdfplumber.open(source) as document:
            if len(document.pages) != last - first + 1:
                raise ValueError(f"Unexpected page count: {source}")
            for number, page in enumerate(document.pages, first):
                lines = [line.rstrip() for line in page.extract_text(layout=True).splitlines()]
                while lines and not lines[0]:
                    lines.pop(0)
                while lines and not lines[-1]:
                    lines.pop()
                if header:
                    if not lines[0].strip().startswith(header) or not re.search(
                        rf"Page\s+{number}$", lines[0]
                    ):
                        raise ValueError(f"Unexpected header on page {number}: {source}")
                    lines.pop(0)
                elif lines.pop().strip() != str(number):
                    raise ValueError(f"Unexpected footer on page {number}: {source}")
                if number == first:
                    start = next(i for i, line in enumerate(lines) if author in line)
                    lines = lines[start:]
                pages.append("\n".join(lines).strip("\n"))
        text = "\n\f\n".join(pages) + "\n"
        if "\ufffd" in text:
            raise ValueError(f"Replacement characters: {source}")
        OUTPUT.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        print(
            case,
            "pages",
            len(pages),
            "words",
            len(text.split()),
            "pdf_sha256",
            hashlib.sha256(source.read_bytes()).hexdigest(),
        )
        print("Ending:", " ".join(text.split()[-30:]))


if __name__ == "__main__":
    prepare()
