"""One-time, source-verified curation of the 2026-09-10 native extractions.

Never imported by extraction or graph code. Original native responses remain
untouched. Remove author metadata, restore three within-footnote boundaries in
Porter, and lift Westmoreland's eight footnotes out of interrupted body sentences.
No body words are rewritten and no alternate schema is accepted.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "output/dissent-extraction-20260910"
AUTHORS = {
    "banuelos_jimenez": "GILMAN, Circuit Judge, dissenting.",
    "porter": "RICHARDSON, Circuit Judge, dissenting:",
    "westmoreland": "JOHN K. BUSH, Circuit Judge, dissenting.",
}
FOOTNOTE_STARTS = (
    "I tend to agree with Judge Motz",
    "Let's review the timeline.",
    "More critically, the majority focuses on the wrong period.",
)
# Reviewed page-bottom notes, the body continuation immediately after each,
# and the exact citation anchor. These are dataset repairs, not PDF heuristics.
WESTMORELAND_NOTES = (
    (
        "1Westmoreland does concede",
        " Tyree and Butler County, the remaining defendants",
        "(citations omitted).1",
    ),
    (
        "2Brawner's modification",
        " dissenting from the grant of stay)",
        "(defining civil-law recklessness)).2",
    ),
    (
        "3Perhaps because of these issues",
        ' ("The Fourteenth Amendment is not a font',
        "failure-to-protect claims.3",
    ),
    ("4This is true even", " \u00a7 1983 jurisprudence.", "jurisprudence.4"),
    ("5I am inclined to agree", " cell. Accepting Westmoreland", "elements 1, 3, and 4.5"),
    ("6The majority does not apply", " Kidd, which Tyree testified", "proof to satisfy it.6"),
    ("7Compare this to Castro", " 8The majority does not apply", "timing of the attack.7"),
    (
        "8The majority does not apply",
        ' "clearly established at the time"',
        "a finding of element 4.8",
    ),
)


def curate(case):
    target = ROOT / f"{case}_dissent.curated.json"
    if target.exists():
        raise FileExistsError(target)
    document = json.loads((ROOT / f"{case}_dissent.native.json").read_text(encoding="utf-8"))
    first = document[0]["paragraphs"][0]
    author = AUTHORS[case]
    if not first["text"].startswith(author):
        raise ValueError("Inspect author metadata before curation")
    first["text"] = first["text"][len(author) :].lstrip()
    if not first["text"]:
        document[0]["paragraphs"].pop(0)
    if not document[0]["paragraphs"] and not document[0]["subsections"]:
        document.pop(0)
    units = [u for s in document for u in [s, *s["subsections"]]]
    if case == "porter":
        before = " ".join(p["text"] for u in units for p in u["paragraphs"])
        for start in FOOTNOTE_STARTS:
            hits = [
                (u, i) for u in units for i, p in enumerate(u["paragraphs"]) if start in p["text"]
            ]
            if len(hits) != 1:
                raise ValueError(f"Expected exactly one verified footnote boundary: {start}")
            unit, index = hits[0]
            text = unit["paragraphs"][index]["text"]
            position = text.index(start)
            if position == 0:
                raise ValueError("Native output differs from the reviewed response")
            unit["paragraphs"][index : index + 1] = [
                {"paragraph_number": 0, "text": text[:position].rstrip()},
                {"paragraph_number": 0, "text": text[position:]},
            ]
        after = " ".join(p["text"] for u in units for p in u["paragraphs"])
        if before != after:
            raise ValueError("Curation must not change footnote wording or order")
    if case == "westmoreland":
        before = Counter(" ".join(p["text"] for u in units for p in u["paragraphs"]).split())
        notes = {}
        for start, resume, anchor in WESTMORELAND_NOTES:
            paragraphs = [p for u in units for p in u["paragraphs"]]
            hosts = [p for p in paragraphs if start in p["text"]]
            if len(hosts) != 1:
                raise ValueError(f"Expected one reviewed note: {start}")
            host = hosts[0]
            text = host["text"]
            begin = text.index(start)
            end = text.index(resume, begin)
            note = text[begin:end]
            host["text"] = text[:begin].rstrip() + text[end:]
            references = [p for p in paragraphs if anchor in p["text"]]
            if len(references) != 1:
                raise ValueError(f"Expected one source citation: {anchor}")
            notes.setdefault(id(references[0]), []).append({"paragraph_number": 0, "text": note})
        for unit in units:
            unit["paragraphs"] = [q for p in unit["paragraphs"] for q in [p, *notes.get(id(p), [])]]
        after = Counter(" ".join(p["text"] for u in units for p in u["paragraphs"]).split())
        if before != after:
            raise ValueError("Relocating footnotes must preserve every source word")
    for unit in units:
        for index, paragraph in enumerate(unit["paragraphs"]):
            paragraph["paragraph_number"] = index
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=AUTHORS)
    curate(parser.parse_args().case)
