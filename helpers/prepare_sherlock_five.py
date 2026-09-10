"""One-time, lossless XHTML paragraph extraction for the five-story experiment.

No model calls or inferred scene boundaries. Only the explicitly supported
Standard Ebooks markup is accepted; unexpected body text fails validation.
"""

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
from xml.etree import ElementTree as ET

import yaml

from pipeline.document import validate_document
from pipeline.files import write_json

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "datasets/sherlock/famous-five"
COMMIT = "48ec456ea50987a81f564821457b9fb32cc2bfc6"
SOURCE = "https://raw.githubusercontent.com/standardebooks/arthur-conan-doyle_the-adventures-of-sherlock-holmes"
STORIES = [
    ("scandal_in_bohemia", "A Scandal in Bohemia", "a-scandal-in-bohemia"),
    ("redheaded_league", "The Redheaded League", "the-redheaded-league"),
    (
        "blue_carbuncle",
        "The Adventure of the Blue Carbuncle",
        "the-adventure-of-the-blue-carbuncle",
    ),
    ("speckled_band", "The Adventure of the Speckled Band", "the-adventure-of-the-speckled-band"),
    ("beryl_coronet", "The Adventure of the Beryl Coronet", "the-adventure-of-the-beryl-coronet"),
]
NS = "{http://www.w3.org/1999/xhtml}"


def extract(raw: bytes, title: str) -> list[dict]:
    root = ET.fromstring(raw)
    body = root.find(NS + "body")
    if body is None:
        raise ValueError("Expected XHTML body")
    paragraphs = []

    def walk(node):
        tag = node.tag.removeprefix(NS)
        if tag in {"h2", "h3", "hr"}:
            return
        if tag == "p":
            if any(
                child.tag.removeprefix(NS) not in {"p", "abbr", "em", "i", "b", "span", "time"}
                for child in node.iter()
            ):
                raise ValueError("Unexpected paragraph markup")
            text = "".join(node.itertext()).strip()
            if not text:
                raise ValueError("Empty source paragraph")
            paragraphs.append({"paragraph_number": len(paragraphs), "text": text})
            return
        if tag not in {"body", "article", "section", "blockquote", "footer"}:
            raise ValueError(f"Unsupported source block: {tag}")
        if (node.text or "").strip():
            raise ValueError("Text outside a paragraph")
        for child in node:
            walk(child)
            if (child.tail or "").strip():
                raise ValueError("Text outside a paragraph")

    walk(body)
    result = [
        {"section_name": title, "section_number": None, "paragraphs": paragraphs, "subsections": []}
    ]
    validate_document(result)
    return result


def prepare():
    if DEST.exists():
        raise FileExistsError("Refusing to overwrite prepared corpus")
    prepared = []
    for paper_id, title, slug in STORIES:
        url = f"{SOURCE}/{COMMIT}/src/epub/text/{slug}.xhtml"
        with urlopen(url, timeout=30) as response:
            raw = response.read()
        document = extract(raw, title)
        prepared.append((paper_id, title, url, raw, document))
    (DEST / "raw").mkdir(parents=True)
    entries, provenance = [], []
    for paper_id, title, url, raw, document in prepared:
        (DEST / "raw" / f"{paper_id}.xhtml").write_bytes(raw)
        filename = f"{paper_id}.content.json"
        write_json(DEST / filename, document)
        entries.append({"paper_id": paper_id, "title": title, "file": filename})
        paragraphs = document[0]["paragraphs"]
        provenance.append(
            {
                "paper_id": paper_id,
                "source_url": url,
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "content_sha256": hashlib.sha256((DEST / filename).read_bytes()).hexdigest(),
                "paragraphs": len(paragraphs),
                "words": sum(len(p["text"].split()) for p in paragraphs),
            }
        )
    (DEST / "manifest.yaml").write_text(
        yaml.safe_dump(
            {"schema_version": 1, "max_granularity": "paragraph", "papers": entries},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    write_json(
        DEST / "provenance.json",
        {
            "source_commit": COMMIT,
            "method": "literal XHTML p elements, including quoted letters and signatures; headings and scene separators omitted",
            "stories": provenance,
        },
    )
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    prepare()
