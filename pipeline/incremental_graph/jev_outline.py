"""Render a Jev decision in focus-first order without changing graph or source identity."""

from collections import defaultdict
from itertools import groupby

from .evidence_encoding import source_address
from .match_evidence import candidate_handle


def _location(unit):
    if "source_position" in unit:
        return unit["paper_key"], *unit["source_position"]
    if unit.get("source_spans"):
        return unit["paper_key"], unit.get("source_section", unit["source_spans"][0][0]), 0
    return None


def _parts(unit):
    paper, sec, pos = _location(unit)
    if "source_spans" in unit:
        start = 0
        for number, paragraph, length in unit["source_spans"]:
            yield (paper, number, paragraph), unit["full_text"][start : start + length], True
            start += length + 2
    else:
        for offset, field in enumerate(
            ("previous_paragraph", "paragraph_under_consideration", "next_paragraph"), -1
        ):
            if part := unit.get(field):
                yield (paper, sec, pos + offset), part["full_text"], offset == 0


def _unpositioned(nodes, level):
    """Frozen inputs without source coordinates: do not infer overlap from equal text."""
    labels, blocks = {}, []
    for i, node in enumerate(nodes):
        label = f"Option {i}" if i else "Focus"
        if i:
            labels[candidate_handle(node)] = label
        members = node.get("members", [node])
        lines = [f"{label} ({level}{' group' if len(members) > 1 else ''})"]
        if len(members) > 1 and node.get("role_statement"):
            lines.append("Group role: " + node["role_statement"])
        for n, unit in enumerate(members, 1):
            center = unit.get("paragraph_under_consideration", unit)
            q = center.get("role_statement")
            lines.append(
                " ".join(
                    filter(
                        None,
                        [
                            unit.get("paper_key"),
                            unit.get("section_label"),
                            f"Member {n}" if len(members) > 1 else "",
                            f"Role: {q}" if q else "",
                        ],
                    )
                )
            )
            lines.append(center["full_text"])
            for key, name in (("previous_paragraph", "Before"), ("next_paragraph", "After")):
                if neighbor := unit.get(key):
                    lines.append(f"{name} (context only): {neighbor['full_text']}")
        blocks.append("\n".join(filter(None, lines)))
    return "\n\n".join([blocks[0], "Candidates", *blocks[1:]]), labels


def _section_outline(context, outline):
    sections = outline["sections"]
    groups = outline["groups"]
    group_names = {frozenset(g["members"]): name for name, g in groups.items()}
    owners, labels = {}, {}
    for index, node in enumerate([context["focus"], *context["candidates"]]):
        members = [
            source_address(*_location(unit), numbers=outline["numbers"])
            for unit in node.get("members", [node])
        ]
        label = members[0] if len(members) == 1 else "Group " + group_names[frozenset(members)]
        if index:
            labels[candidate_handle(node)] = label
        for member in members:
            if member not in sections or member in owners:
                raise ValueError(f"Expected one decision role for top-level section {member}")
            owners[member] = ("Candidates" if index else "Focus", label)

    blocks = {"Focus": [], "Context": [], "Candidates": []}
    node_blocks = {label: block for block, label in owners.values()}
    for name, group in groups.items():
        # A participating node states its shared role beside its own members.
        if block := node_blocks.get("Group " + name):
            blocks[block].append(f"Group {name} Role: {group['role_statement']}")
    for addr, (paper, title, role, content) in sections.items():
        block, label = owners.get(addr, ("Context", addr))
        member = f" (member of {label})" if label != addr else ""
        # Remove extraction line breaks, not words or punctuation.
        content = " ".join(line.strip() for line in content.splitlines() if line.strip())
        blocks[block].append(
            f"Section: {addr} {paper} / {title}{member}\nRole: {role}\nContent: {content}"
        )
    for name, group in groups.items():
        if "Group " + name in node_blocks:
            continue
        members = ", ".join(
            addr + (" (fan-in)" if role == "fan_in" else "")
            for addr, role in group["members"].items()
        )
        blocks["Context"].append(
            f"Prior match: Group {name}: {members} | {group['role_statement']}"
        )
    return "\n\n".join("\n".join([name, *rows]) for name, rows in blocks.items()), labels


def focus_outline(context):
    level = context["scope"]["level"]
    nodes = [context["focus"], *context["candidates"]]
    annotations = context.get("outline", {})
    if level == "section" and "sections" in annotations:
        return _section_outline(context, annotations)
    if any(not _location(u) for n in nodes for u in n.get("members", [n])):
        return _unpositioned(nodes, level)

    def address(*location):
        return source_address(*location, numbers=annotations.get("numbers"))

    metadata = dict(annotations.get("units", {}))
    groups = dict(annotations.get("groups", {}))
    by_members = {frozenset(g["members"]): name for name, g in groups.items()}
    rows, owners = {}, {}
    marks, labels = defaultdict(list), {}
    first_label = None
    for index, node in enumerate(nodes):
        members = node.get("members", [node])
        addresses = [address(*_location(m)) for m in members]
        group = None
        if len(members) > 1:
            group = by_members.get(frozenset(addresses))
            if not group:  # Standalone/frozen evidence can lack a graph snapshot.
                n = 1
                while (group := f"{level[0].upper()}{n}") in groups:
                    n += 1
                groups[group] = {
                    "members": dict.fromkeys(addresses),
                    "role_statement": node.get("role_statement"),
                }
            name = "Group " + group
        else:
            name = addresses[0]
        if index:
            if name in labels.values():
                name += f" (option {index})"
            labels[candidate_handle(node)] = name
        else:
            first_label = name

        for unit, addr in zip(members, addresses):
            paper, sec, pos = _location(unit)
            center = unit.get("paragraph_under_consideration", unit)
            metadata.setdefault(addr, (unit.get("section_label"), center.get("role_statement")))
            role = "focus" if index == 0 else "candidate"
            tag = f"{role} {name}" if group or name != addr else role
            marks[addr].append(tag)
            part_keys = set()
            for key, text, judged in _parts(unit):
                if rows.setdefault(key, text) != text:
                    raise ValueError(f"Inconsistent source text at {key}")
                # A selectable center outranks a neighbor from either side.
                priority = (not judged, bool(index))
                owners[key] = min(owners.get(key, priority), priority)
                part_keys.add(key[1])
            if not pos and sec not in part_keys:
                # A heading with no direct paragraphs still has its own identity.
                key = (paper, sec, -1)
                rows[key] = ""
                owners[key] = min(owners.get(key, (False, bool(index))), (False, bool(index)))
            for child in sorted(part_keys - {sec}):
                heading = address(paper, child)
                marker = "part of " + addr
                if marker not in marks[heading]:
                    marks[heading].append(marker)

    affiliations = defaultdict(list)
    for group, data in groups.items():
        for addr, role in data["members"].items():
            affiliations[addr].append((group, role))
    shown, stated = set(), set()

    def heading(addr, extra=()):
        tags = list(marks[addr]) + list(extra)
        name, role_statement = metadata.get(addr, (None, None))
        notes = []
        if addr not in shown:
            for group, role in affiliations[addr]:
                if not any(t.endswith("Group " + group) for t in tags):
                    tags.append("in Group " + group)
                if role == "fan_in":
                    tags.append("fan-in member")
                gq = groups[group]["role_statement"]
                if group not in stated and gq and gq != role_statement:
                    notes.append(f"  Group {group} Role: {gq}")
                stated.add(group)
        line = " ".join(
            filter(
                None,
                [
                    addr,
                    name if addr not in shown else "",
                    "[" + "; ".join(tags) + "]" if tags else "",
                ],
            )
        )
        if addr not in shown and role_statement:
            line += " | Role: " + role_statement
        shown.add(addr)
        return [line, *notes]

    complete = "paragraphs" in annotations
    for paper, sec, pos, text in annotations.get("paragraphs", ()):
        key = (paper, sec, pos)
        if rows.setdefault(key, text) != text:
            raise ValueError(f"Inconsistent source text at {key}")
        owners.setdefault(key, (True, False))
    blocks = {"Focus": [], "Context": [], "Candidates": []}

    def block_for(key):
        neighbor, candidate = owners[key]
        if complete and neighbor:
            return "Context"
        return "Candidates" if candidate else "Focus"

    for block, lines in blocks.items():
        keys = sorted(
            (k for k in rows if block_for(k) == block),
            key=lambda k: (int(k[0].removeprefix("paper-")), k[1], k[2]),
        )
        for (paper, sec), parts in groupby(keys, lambda k: k[:2]):
            lines.extend(heading(address(paper, sec)))
            for key in parts:
                if key[2] < 0:
                    continue
                if key[2]:
                    extra = ["context only"] if owners[key][0] else []
                    lines.extend("  " + line for line in heading(address(*key), extra))
                lines.append("    " + rows[key])

    history = []
    for group, data in groups.items():
        missing = [
            addr + (" (fan-in)" if role == "fan_in" else "")
            for addr, role in data["members"].items()
            if addr not in shown
        ]
        if missing:
            more = " also includes " if group in stated else ": "
            q = data["role_statement"] if group not in stated else None
            history.append(
                "Group " + group + more + ", ".join(missing) + (f" | Role: {q}" if q else "")
            )
    if history:
        blocks["Context" if complete else "Candidates"].extend(
            ["\nPrior matches (context only)", *history]
        )
    if complete:
        return "\n\n".join("\n".join([name, *lines]) for name, lines in blocks.items()), labels
    return "\n".join(
        [f"Focus {level}: {first_label}", *blocks["Focus"], "\nCandidates", *blocks["Candidates"]]
    ), labels
