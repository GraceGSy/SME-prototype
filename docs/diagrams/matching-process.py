"""Write docs/diagrams/matching-process.svg (hand-laid-out, level-agnostic)."""
import sys
from html import escape

out = sys.argv[1]
W, H = 1130, 1120
FONT = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
INK, MUTED, LINE = "#1f2328", "#5b6470", "#d5dae1"
ACT = {
    "jev": ("#6b4fa0", "#f4f0fb"),
    "claude": ("#b4621a", "#fdf3e7"),
    "rule": ("#2f6e45", "#edf6f0"),
    "data": ("#2c6280", "#eef4f8"),
}
parts = []


def add(s):
    parts.append(s)


def text(x, y, s, size=14, weight=400, fill=INK, anchor="start", extra=""):
    add(
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}" {extra}>{escape(s)}</text>'
    )


def lines(x, y, rows, size=13.5, gap=20, fill=INK):
    for i, row in enumerate(rows):
        text(x, y + i * gap, row, size=size, fill=fill)


def badge(x, y, n, actor):
    color = ACT[actor][0]
    add(f'<circle cx="{x}" cy="{y}" r="13" fill="{color}"/>')
    text(x, y + 5, str(n), size=14, weight=700, fill="#fff", anchor="middle")


def card(x, y, w, h, actor, n, title, body, chip=None, body_width=None):
    stroke, fill = ACT[actor]
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" '
        f'stroke="{stroke}" stroke-opacity="0.45" stroke-width="1.3"/>')
    if n is not None:
        badge(x + 30, y + 31, n, actor)
        text(x + 52, y + 37, title, size=17, weight=700)
    else:
        text(x + 18, y + 37, title, size=17, weight=700)
    lines(x + 18, y + 66, body)
    if chip:
        cw = 11 + 7.4 * len(chip)
        cy = y + h - 36
        add(f'<rect x="{x + 18}" y="{cy}" width="{cw}" height="24" rx="12" fill="#fff" '
            f'stroke="{stroke}" stroke-opacity="0.6"/>')
        text(x + 18 + cw / 2, cy + 16.5, chip, size=12.5, weight=600, fill=stroke, anchor="middle")


def arrow(d, color=MUTED, width=1.8, dash=None):
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash_attr} '
        f'marker-end="url(#head)"/>')


def label(y, s):
    text(70, y, s, size=12.5, weight=700, fill=MUTED, extra='letter-spacing="1.4"')


add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
    f'font-family="{FONT}">')
add('<defs><marker id="head" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" '
    f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{MUTED}"/>'
    '</marker></defs>')
add(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

# Header and legend
text(70, 58, "How a new document joins the graph", size=27, weight=700)
text(70, 86, "One procedure for every level: first sections, then paragraphs inside each "
     "matched section group.", size=15, fill=MUTED)
lx = 70
for actor, name in (("jev", "Jev judges"), ("claude", "Claude writes"), ("rule", "Fixed rule in code")):
    add(f'<circle cx="{lx + 7}" cy="{114}" r="7" fill="{ACT[actor][0]}"/>')
    text(lx + 21, 119, name, size=13.5, fill=MUTED)
    lx += 40 + 8 * len(name)

# Documents 1 and 2
add(f'<rect x="70" y="138" width="1020" height="62" rx="12" fill="#f6f7f9" stroke="{LINE}"/>')
text(90, 165, "Documents 1 and 2", size=14.5, weight=700)
text(90, 187, "Document 1 seeds the graph: each unit starts its own group.  Document 2 skips "
     "steps 2 and 3: Jev reads both documents whole and picks directly.", size=13.5, fill=MUTED)

# Steps 1-4: narrowing one unit's options
label(236, "FOR EACH NEW UNIT  ·  DOCUMENT 3 ON")
cw, gap, top, ch = 225, 40, 250, 172
xs = [70 + i * (cw + gap) for i in range(4)]
card(xs[0], top, cw, ch, "rule", 1, "Candidates",
     ["Every group at this level", "inside the same parent", "group as the unit."], "all groups, e.g. 40")
card(xs[1], top, cw, ch, "jev", 2, "Shortlist",
     ["Jev ranks every candidate", "in one long-context call", "and keeps the top 10."], "at most 10")
card(xs[2], top, cw, ch, "jev", 3, "Yes / no",
     ["One question per", "shortlisted group: does", "the unit play this role?"], "the yeses, e.g. 3")
card(xs[3], top, cw, ch, "jev", 4, "Pick",
     ["Jev ranks the yeses.", "Top two within 0.10: ask", "again; still close: hold."], "one pick, or none")
for i in range(3):
    x = xs[i] + cw
    arrow(f"M{x + 6},{top + ch / 2} H{x + gap - 6}")
text(580, top + ch + 32, "Asked both ways: the same yes/no answers also let each group pick among "
     "the new units that said yes to it.", size=13.5, fill=MUTED, anchor="middle",
     extra='font-style="italic"')

# Step 5: decide
arrow(f"M580,{top + ch + 46} V{top + ch + 80}")
label(522, "5  DECIDE  ·  FIXED RULES")
dw, dg, dtop, dh = 326, 21, 536, 142
dx = [70 + i * (dw + dg) for i in range(3)]
card(dx[0], dtop, dw, dh, "rule", None, "Mutual match → join",
     ["The unit and the group", "picked each other."])
card(dx[1], dtop, dw, dh, "rule", None, "Fan-in → join",
     ["A one-way pick joins when", "the unit's neighbour in the", "same document joined that", "group mutually."])
card(dx[2], dtop, dw, dh, "rule", None, "No match → new group",
     ["The unit starts a group", "of one. Step 6 may still", "place it later."])

# Glyphs: unit (circle) and group (rounded square)
def unit(cx, cy, fill="#2c6280"):
    add(f'<circle cx="{cx}" cy="{cy}" r="9" fill="{fill}"/>')


def group(x, y):
    add(f'<rect x="{x}" y="{y}" width="34" height="26" rx="7" fill="#fff" stroke="#2f6e45" stroke-width="2"/>')


g = ACT["rule"][0]
# mutual: unit <-> group
gx, gy = dx[0] + 228, dtop + 70
unit(gx, gy)
group(gx + 50, gy - 13)
add(f'<path d="M{gx + 13},{gy} H{gx + 45}" stroke="{g}" stroke-width="2" '
    'marker-start="url(#head)" marker-end="url(#head)"/>')
# fan-in: unit <-> group mutually; its neighbour -> group one way
gx, gy = dx[1] + 232, dtop + 50
unit(gx, gy)
unit(gx, gy + 38, "#7b9bb0")
add(f'<path d="M{gx},{gy + 10} V{gy + 28}" stroke="#7b9bb0" stroke-width="2" stroke-dasharray="3 3"/>')
add(f'<rect x="{gx + 50}" y="{gy - 13}" width="34" height="64" rx="8" fill="#fff" stroke="#2f6e45" stroke-width="2"/>')
add(f'<path d="M{gx + 13},{gy} H{gx + 45}" stroke="{g}" stroke-width="2" '
    'marker-start="url(#head)" marker-end="url(#head)"/>')
add(f'<path d="M{gx + 13},{gy + 38} H{gx + 45}" stroke="{g}" stroke-width="2" '
    'marker-end="url(#head)"/>')
text(gx - 20, gy + 70, "neighbour", size=11, fill=MUTED)
# new group: a lone unit in its own group
gx, gy = dx[2] + 250, dtop + 57
add(f'<rect x="{gx - 18}" y="{gy - 15}" width="36" height="30" rx="8" fill="#fff" '
    f'stroke="{g}" stroke-width="2" stroke-dasharray="4 3"/>')
unit(gx, gy)

# Steps 6 and 7
arrow(f"M315,{dtop + dh + 6} V{dtop + dh + 40}")
rw, rtop, rh = 490, 724, 118
card(70, rtop, rw, rh, "jev", 6, "Recover groups of one",
     ["Each group of one repeats steps 2 to 5 against groups that",
      "already span documents, and joins on a mutual or fan-in match."])
card(600, rtop, rw, rh, "claude", 7, "Rewrite group roles",
     ["Claude rewrites the role statement of every group",
      "that changed."])
arrow(f"M{70 + rw + 6},{rtop + rh / 2} H{600 - 6}")

# Step 8: one level down
btop, bh = 900, 196
arrow(f"M845,{rtop + rh + 6} V{btop - 6}")
stroke, fill = ACT["data"]
add(f'<rect x="70" y="{btop}" width="1020" height="{bh}" rx="14" fill="{fill}" stroke="{stroke}" '
    'stroke-opacity="0.55" stroke-width="1.5" stroke-dasharray="7 5"/>')
badge(100, btop + 32, 8, "data")
text(122, btop + 38, "One level down: the same steps for paragraphs", size=17, weight=700)

# Illustration: one section group, three documents, paragraphs coloured by paragraph group
ix, iy = 96, btop + 62
add(f'<rect x="{ix}" y="{iy}" width="330" height="116" rx="10" fill="#fff" stroke="{stroke}" stroke-opacity="0.5"/>')
text(ix + 14, iy + 22, "Section group: Method", size=12.5, weight=700, fill=stroke)
colors = {"a": "#8fb8d4", "b": "#e3b37a", "c": "#d7dbe0"}
layout = [("Doc 1", "abc"), ("Doc 2", "ab"), ("Doc 3", "acb")]
for i, (name, paras) in enumerate(layout):
    cx = ix + 16 + i * 104
    text(cx, iy + 46, name, size=11.5, fill=MUTED)
    for j, key in enumerate(paras):
        add(f'<rect x="{cx}" y="{iy + 54 + j * 18}" width="90" height="12" rx="4" fill="{colors[key]}"/>')
# Bullets
bx = 460
rows = [
    ("Steps 1 to 7 run again on the new document's paragraphs.", 0),
    ("Candidates are only the paragraph groups inside the same section group.", 0),
    ("Base case: a one-paragraph section matched to a one-paragraph section", 0),
    ("passes its match down; no question is asked.", 1),
    ("Same colour in the box = same paragraph group; grey = alone.", 0),
]
y = btop + 78
for row, cont in rows:
    if not cont:
        add(f'<circle cx="{bx}" cy="{y - 5}" r="3" fill="{stroke}"/>')
    text(bx + 14, y, row, size=14)
    y += 24 if not cont else 26

# Loop back from step 8 to step 1
arrow(f"M70,{btop + 120} H40 V{top + ch / 2} H64", color=stroke, width=2, dash="6 5")
text(30, (btop + 120 + top + ch / 2) / 2, "then for paragraphs", size=12.5, weight=600, fill=stroke,
     anchor="middle", extra=f'transform="rotate(-90 30 {(btop + 120 + top + ch / 2) / 2})"')

add("</svg>")
open(out, "w", encoding="utf-8").write("\n".join(parts))
print("wrote", out)
