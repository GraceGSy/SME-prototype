"""Lossless wire representation: share text, never collapse candidate identities."""

from dataclasses import dataclass
from typing import Any

from ..prompts import request_prompts
from .match_evidence import candidate_handle

EVIDENCE_PROMPTS = request_prompts("evidence")


def _letters(index: int) -> str:
    """Zero-based spreadsheet labels: A..Z, AA..AZ, ..."""
    result = ""
    while index >= 0:
        result = chr(65 + index % 26) + result
        index = index // 26 - 1
    return result


def source_address(paper: str, section: int, paragraph: int = 0, *, numbers=None) -> str:
    doc = _letters(int(paper.removeprefix("paper-")) - 1)
    if numbers and (number := numbers.get(f"{paper}:{section}")):
        return f"{doc}{number}" + (f":p{paragraph}" if paragraph else "")
    return f"{doc}{section}" + (f".{paragraph}" if paragraph else "")


def _is_group(node: dict) -> bool:
    return len(node.get("members", ())) > 1


def paragraph_options(context: dict) -> tuple[str, dict[str, str]] | None:
    candidates = context["candidates"]
    if context.get("scope", {}).get("level") != "paragraph" or not candidates:
        return None
    focus = context["focus"]
    if not any("members" in n or "source_position" in n for n in [focus, *candidates]):
        return None  # Historical inputs with no graph or source-position information.
    groups = sum(_is_group(c) for c in candidates)
    if _is_group(focus):
        if groups:
            return None  # This is not a paragraph-to-group comparison in either direction.
        direction = "group_to_paragraph"
    elif not groups:
        direction = "paragraph_to_paragraph"
    elif groups == len(candidates):
        direction = "paragraph_to_group"
    else:
        direction = "paragraph_to_mixed"
    return (
        direction,
        {
            candidate_handle(c): f"{'Group' if _is_group(c) else 'Paragraph'} {_letters(i)}"
            for i, c in enumerate(candidates)
        },
    )


@dataclass
class ParagraphComparison:
    direction: str
    labels: dict[str, str]
    prefix: str
    remainder: str

    @property
    def text(self) -> str:
        return "\n\n".join(filter(None, (self.prefix, self.remainder)))


def paragraph_comparison(
    context: dict, labels: dict[str, str] | None = None
) -> ParagraphComparison | None:
    options = paragraph_options(context)
    if options is None:
        return None
    direction, defaults = options
    labels = {key: (labels or defaults)[key] for key in defaults}

    # Transform only the model-facing view. Reconciliation and evidence validation
    # still operate on the original node and its real selection handle.
    def unwrap(node, selectable):
        if len(node.get("members", ())) == 1:
            return {
                **node["members"][0],
                **({"selection_id": candidate_handle(node)} if selectable else {}),
            }
        return node

    context = {
        **context,
        "focus": unwrap(context["focus"], False),
        "candidates": [unwrap(c, True) for c in context["candidates"]],
    }
    forward = direction != "group_to_paragraph"
    focus_label = "Passage to match" if direction == "paragraph_to_paragraph" else "New paragraph"
    group_nodes = (
        [c for c in context["candidates"] if _is_group(c)] if forward else [context["focus"]]
    )
    state = passage_state(context)
    if state is None:
        # Old frozen inputs have windows but not reliable document positions.
        # Preserve the window order and never send the stored graph handles.
        def window(unit):
            parts = (
                [unit["paper_key"].replace("paper-", "Paper ") + ":"] if "paper_key" in unit else []
            )
            for field, label in (
                ("previous_paragraph", "Before (context only)"),
                ("paragraph_under_consideration", "Passage"),
                ("next_paragraph", "After (context only)"),
            ):
                if unit.get(field):
                    parts.append(f"{label}: {unit[field]['full_text']}")
            return "\n".join(parts)

        def block(node, name):
            if "members" not in node:
                return name + "\n" + window(node)
            return (
                name
                + " (read these members together)\n"
                + "\n".join(f"Member {i}: {window(m)}" for i, m in enumerate(node["members"], 1))
            )

        candidates = "\n\n".join(
            block(c, labels[candidate_handle(c)]) for c in context["candidates"]
        )
        focus = block(context["focus"], focus_label if forward else "Existing group")
        return ParagraphComparison(direction, labels, candidates, focus)

    roster = []
    for node in group_nodes:
        name = labels[candidate_handle(node)] if forward else "Existing group"
        members = []
        for unit in node["members"]:
            section, pos = unit["source_position"]
            paper = unit["paper_key"].replace("paper-", "Paper ")
            members.append(f"{paper} {section}.{pos}")
        roster.append(f"{name} members: " + "; ".join(members))

    prefix = roster[:] if forward else []
    remainder = [] if forward else roster[:]
    seen_focus = False
    for paper, rows in state["papers"].items():
        lines = [paper.replace("paper-", "Paper ")]
        for row in rows:
            if row.get("context_only"):
                role = "context only"
            elif "focus_group" in row:
                role = "existing group member"
                seen_focus = True
            elif "focus" in row:
                role = focus_label.lower()
                seen_focus = True
            elif "candidate_group" in row:
                role = labels[row["candidate_group"]] + " member"
            else:
                role = labels[row["candidate"]]
            if "member" in row:
                role += f" {row['member']}"
            lines.append(f"{row['at']} [{role}]: {row['text']}")
        (remainder if seen_focus or not forward else prefix).append("\n".join(lines))
    return ParagraphComparison(direction, labels, "\n\n".join(prefix), "\n\n".join(remainder))


def passage_state(context: dict) -> dict | None:
    """Render each source occurrence once, not once per overlapping evidence window.

    Saved historical pools have no source coordinates. Do not infer positions from
    equal text: identical sentences at different positions are distinct evidence.
    """
    rows = {}
    questions = {}
    for is_focus, node in [(True, context["focus"]), *((False, c) for c in context["candidates"])]:
        group = "members" in node
        handle = "focus" if is_focus else candidate_handle(node)
        role = ("focus" if is_focus else "candidate") + ("_group" if group else "")
        members = node["members"] if group else [node]
        group_question = node.get("generated_question_metadata") if group else None
        if group_question:
            questions[handle] = group_question
        for n, unit in enumerate(members, 1):
            label = {role: True if is_focus else handle}
            if len(members) > 1:
                label["member"] = n
            if "source_position" in unit:
                section, center = unit["source_position"]
                parts = []
                for offset, key in enumerate(
                    ("previous_paragraph", "paragraph_under_consideration", "next_paragraph"), -1
                ):
                    passage = unit.get(key)
                    if passage is not None:
                        parts.append((section, center + offset, passage["full_text"], offset == 0))
                question = unit["paragraph_under_consideration"].get("generated_question_metadata")
            elif "source_spans" in unit:
                parts = []
                start = 0
                for section, position, length in unit["source_spans"]:
                    parts.append(
                        (section, position, unit["full_text"][start : start + length], True)
                    )
                    start += length + 2
                question = unit.get("generated_question_metadata")
            else:
                return None

            section_label = unit.get("section_label")
            for section, position, text, judged in parts:
                key = (unit["paper_key"], section, position)
                stored, labels = rows.setdefault(key, (text, []))
                if stored != text:
                    raise ValueError(f"Inconsistent source text at {key}")
                if judged:
                    tag = dict(label)
                    if question and question != group_question:
                        tag["question"] = question
                    if section_label:
                        tag["section"] = section_label
                    labels.append(tag)
                    # A structural unit may span several rows. State its metadata once.
                    question = None
                    section_label = None

    papers = {}
    for (paper, section, position), (text, labels) in sorted(
        rows.items(), key=lambda item: (int(item[0][0].removeprefix("paper-")), *item[0][1:])
    ):
        role = (
            {"context_only": True}
            if not labels
            else labels[0]
            if len(labels) == 1
            else {"roles": labels}
        )
        papers.setdefault(paper, []).append({"at": f"{section}.{position}", **role, "text": text})
    return {
        "scope": context["scope"],
        **({"group_questions": questions} if questions else {}),
        "papers": papers,
    }


def encode_evidence(evidence: dict[str, Any], *, candidate_handles: bool = True) -> dict[str, Any]:
    texts: dict[str, str] = {}
    references: dict[str, str] = {}

    def visit(value):
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key != "full_text":
                result[key] = visit(item)
                continue
            if not isinstance(item, str):
                raise TypeError("Evidence full_text must be a string")
            ids = []
            for text in item.split("\n\n"):
                if text not in references:
                    reference = f"text-{len(texts) + 1:04d}"
                    references[text] = reference
                    texts[reference] = text
                ids.append(references[text])
            result["full_text_refs"] = ids
        return result

    encoded = visit(evidence)
    return {
        "text_reference_contract": (
            EVIDENCE_PROMPTS["text_reference_contract"]
            + (EVIDENCE_PROMPTS["candidate_handle_suffix"] if candidate_handles else "")
        ),
        "source_texts": texts,
        **encoded,
    }
