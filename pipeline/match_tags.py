"""Updated stage 2: tags are now free-text questions/phrases (not a fixed
vocabulary -- see extract_sections.py / extract_fine_grained.py), so this
replaces the old mutual-best-match reciprocal filtering with something
simpler and more exploratory:

For every unit (section or paragraph), and separately for EACH other paper,
find the 3 tags in that paper most similar to this unit's tag, each with a
similarity score in [0, 1]. This is directional and NOT reciprocity-filtered
(unlike the old match_sections.py) -- unit X's top 3 in paper B does not
imply any of those B units have X back in their own top 3. It's saved as an
interim candidate file (tag_matches.json), not a final matched-links result;
narrowing these candidates down (e.g. to mutual matches) is a later step.

Matching always happens within one granularity at a time: sections only
compare to other sections, paragraphs only to other paragraphs.

Similarity is computed directly on the tag strings via text_similarity()
(lexical Jaccard + character-ratio blend, same function used elsewhere in
this project) -- purely the tag, not blended with the unit's own text this
time, per the current instructions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from align_graphs import text_similarity
from pipeline_paths import output_dir
from section_schema import GRANULARITIES, SectionedPaper

OUTPUT_DIR = output_dir()
TOP_K = int(os.environ.get("SME_MATCH_TOP_K", "3"))


def _load(path: Path) -> SectionedPaper:
    return SectionedPaper.model_validate(json.loads(path.read_text()))


def top_matches(tag: str, other_units: list, k: int = TOP_K) -> list[tuple]:
    scored = [(other, text_similarity(tag, other.tag)) for other in other_units]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]


def match_granularity(
    papers: dict[str, SectionedPaper], granularity: str
) -> list[dict]:
    paper_ids = list(papers.keys())
    entries = []
    for paper_id in paper_ids:
        units = getattr(papers[paper_id], granularity)
        for unit in units:
            matches = []
            for other_id in paper_ids:
                if other_id == paper_id:
                    continue
                other_units = getattr(papers[other_id], granularity)
                for other_unit, score in top_matches(unit.tag, other_units):
                    matches.append(
                        {
                            "paper": other_id,
                            "unit_id": other_unit.id,
                            "tag": other_unit.tag,
                            "similarity": round(score, 3),
                        }
                    )
            entries.append(
                {
                    "paper": paper_id,
                    "unit_id": unit.id,
                    "tag": unit.tag,
                    "matches": matches,
                }
            )
    return entries


def main() -> None:
    manifest = json.loads((OUTPUT_DIR / "manifest.json").read_text())
    papers = {m["paper_id"]: _load(OUTPUT_DIR / m["file"]) for m in manifest}

    output: dict[str, list[dict]] = {}
    for granularity in GRANULARITIES:
        entries = match_granularity(papers, granularity)
        output[granularity] = entries
        total_matches = sum(len(e["matches"]) for e in entries)
        print(
            f"[{granularity}] {len(entries)} units, {total_matches} candidate matches (top {TOP_K} per other paper)"
        )

    out_path = OUTPUT_DIR / "tag_matches.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
