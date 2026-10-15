"""Branded infographics for sdsmanager.com articles, drawn from templates (docs/infographic-audit.md).

The six templates reproduce the house style the October 2026 inner images converged on (style A): Inter,
near-black titles, periwinkle and logo yellow, lavender cards, the SDS Manager logo bottom-right. A model
never draws them: it (or a person) fills a small spec, and this module lays it out, so every rule is a check.

    render(kind, spec) -> Infographic(svg, png, webp, width, height, alt, problems)

Kinds: "steps", "decision", "columns", "part_to_whole", "bars", "form_anatomy" (TEMPLATES has each one's
fields and limits). Text is set in Inter and drawn as vector outlines (fontTools, as sds-hero-stock's svgify
does for the hero headline), so the SVG needs no installed font. Every text run is drawn through one method
that records its size and the colour behind it, so legibility and contrast are measured on what was drawn.

Layout is designed at 800 px wide, the width the site serves inner images at; the PNG is twice that and the
WebP 1200 px (the blog skill's minimum for inline images).
"""

import io
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from . import house

FONTS = Path(__file__).parent / "vendor" / "sds_hero_stock" / "assets" / "fonts"
LOGO = Path(__file__).parent / "vendor" / "sds_hero_stock" / "assets" / "sds-manager-logo.svg"
WEIGHTS = {400: "Inter-Regular.ttf", 600: "Inter-SemiBold.ttf", 700: "Inter-Bold.ttf"}

W = 800  # design width: the site serves inner images at 800 px
M = 40  # outer margin
PNG_SCALE = 2
WEBP_WIDTH = 1200
WEBP_BUDGET = 100_000  # bytes (ehs-seo-blog-optimized: inline images under about 100 KB)
MIN_TEXT = 12  # px at 800 px wide
LINE = 1.35  # line height, in font sizes

# Style A tokens (measured on the October 2026 graphics; periwinkle and yellow are the logo's own colours).
# White text needs a deeper periwinkle than the logo's #626DF9, which gives white only about 4.2:1.
INK = "#2E3039"
MUTED = "#5F6472"
PERI = "#626DF9"  # accents without text on them: borders, dots, lines, arrows
PERI_DEEP = "#4D55D6"  # fills that carry white text
PERI_TEXT = "#4A51C9"  # periwinkle text on white or lavender
PERI_LIGHT = "#B4B9FC"
LAVENDER = "#F1F2FE"
LAVENDER_BORDER = "#C9CDFB"
YELLOW = "#FFC93C"
YELLOW_SOFT = "#FFF5D9"
YELLOW_BORDER = "#F0C04A"
CARD = "#F8F8FC"
RULE = "#DCDEE8"
WHITE = "#FFFFFF"


class InfographicError(Exception):
    """The spec can't be drawn (missing fields, unknown kind); the message says what to fix."""


@dataclass
class Infographic:
    kind: str
    svg: str
    png: bytes
    webp: bytes
    width: int
    height: int
    alt: str
    problems: list = field(default_factory=list)  # [{"level": "block"|"advise", "text": ...}]

    @property
    def blocked(self):
        return any(p["level"] == "block" for p in self.problems)


# ---- Colour ----


def _luminance(hex_colour):
    value = hex_colour.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    """WCAG contrast ratio of two #rrggbb colours."""
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _needed_contrast(size, weight):
    # WCAG "large text": 24 px, or 18.66 px bold.
    return 3.0 if size >= 24 or (size >= 18.66 and weight >= 700) else 4.5


# ---- Type ----


@dataclass(frozen=True)
class _Face:
    glyphs: object
    cmap: dict
    hmtx: object
    upm: int
    ascent: float  # in em


@cache
def _face(weight):
    from fontTools.ttLib import TTFont

    font = TTFont(FONTS / WEIGHTS[weight])
    return _Face(
        font.getGlyphSet(),
        font.getBestCmap(),
        font["hmtx"],
        font["head"].unitsPerEm,
        font["hhea"].ascent / font["head"].unitsPerEm,
    )


def fonts_missing():
    return [name for name in WEIGHTS.values() if not (FONTS / name).is_file()]


def text_width(text, weight, size):
    face = _face(weight)
    space = face.cmap.get(32)
    total = 0
    for ch in text:
        name = face.cmap.get(ord(ch)) or space
        total += face.hmtx[name][0]
    return total * size / face.upm


def wrap(text, weight, size, width):
    """Greedy word wrap; a single word wider than the box stays on its own line (and is reported)."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and text_width(trial, weight, size) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines or [""]


def _fmt(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


class Canvas:
    """SVG elements plus the record of every text run (for the legibility and contrast checks)."""

    def __init__(self):
        self.parts, self.problems, self.texts = [], [], []

    def add(self, element):
        self.parts.append(element)

    def rect(self, x, y, w, h, fill="none", stroke=None, rx=0, dash=None, width=1.5):
        attrs = (
            f'x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" height="{_fmt(h)}" rx="{_fmt(rx)}" fill="{fill}"'
        )
        if stroke:
            attrs += f' stroke="{stroke}" stroke-width="{_fmt(width)}"'
        if dash:
            attrs += f' stroke-dasharray="{dash}"'
        self.add(f"<rect {attrs}/>")

    def circle(self, cx, cy, r, fill):
        self.add(f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{_fmt(r)}" fill="{fill}"/>')

    def path(self, d, stroke=None, fill="none", width=1.5, dash=None):
        attrs = f'd="{d}" fill="{fill}"'
        if stroke:
            attrs += f' stroke="{stroke}" stroke-width="{_fmt(width)}"'
            attrs += ' stroke-linecap="round" stroke-linejoin="round"'
        if dash:
            attrs += f' stroke-dasharray="{dash}"'
        self.add(f"<path {attrs}/>")

    def arrow(self, x1, y1, x2, y2, colour=PERI, head=7):
        """A straight arrow from (x1, y1) to (x2, y2) with a filled head."""
        import math

        angle = math.atan2(y2 - y1, x2 - x1)
        bx, by = x2 - head * math.cos(angle), y2 - head * math.sin(angle)
        self.path(f"M{_fmt(x1)} {_fmt(y1)}L{_fmt(bx)} {_fmt(by)}", stroke=colour, width=1.8)
        left = (bx + head * 0.6 * math.sin(angle), by - head * 0.6 * math.cos(angle))
        right = (bx - head * 0.6 * math.sin(angle), by + head * 0.6 * math.cos(angle))
        self.path(
            f"M{_fmt(x2)} {_fmt(y2)}L{_fmt(left[0])} {_fmt(left[1])}L{_fmt(right[0])} {_fmt(right[1])}Z",
            fill=colour,
        )

    def text(self, x, top, text, weight, size, fill, on, anchor="start"):
        """One line of text with its top at `top`; returns its width. `on` is the colour behind it."""
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen

        face = _face(weight)
        scale = size / face.upm
        width = text_width(text, weight, size)
        x0 = x - width / 2 if anchor == "middle" else x - width if anchor == "end" else x
        base = top + size * 0.98  # the line box is size * LINE; Inter's cap height is 0.73 em
        pen = SVGPathPen(face.glyphs, ntos=_fmt)
        gx = x0
        missing = set()
        for ch in text:
            name = face.cmap.get(ord(ch))
            if name is None:
                missing.add(ch)
                name = face.cmap.get(32)
            face.glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, gx, base)))
            gx += face.hmtx[name][0] * scale
        if missing:
            self.problems.append(
                {"level": "block", "text": f"Inter has no glyph for {''.join(sorted(missing))!r}."}
            )
        if pen.getCommands():
            self.add(f'<path fill="{fill}" d="{pen.getCommands()}"/>')
        self.texts.append({"text": text, "size": size, "weight": weight, "fill": fill, "on": on})
        return width

    def paragraph(self, x, top, width, text, weight, size, fill, on, anchor="start", max_lines=None, what=""):
        """Wrapped text; returns the height used. Text over `max_lines` lines is reported, not cut."""
        lines = wrap(text, weight, size, width)
        if max_lines and len(lines) > max_lines:
            self.problems.append(
                {
                    "level": "block",
                    "text": f"Too long for its box ({len(lines)} lines, at most {max_lines}): "
                    f"{what or text[:60]!r}.",
                }
            )
        for word in text.split():
            if text_width(word, weight, size) > width + 0.5:
                self.problems.append({"level": "block", "text": f"The word {word!r} is wider than its box."})
        px = x + width / 2 if anchor == "middle" else x + width if anchor == "end" else x
        for i, line in enumerate(lines):
            self.text(px, top + i * size * LINE, line, weight, size, fill, on, anchor)
        return len(lines) * size * LINE

    def height_of(self, text, weight, size, width):
        return len(wrap(text, weight, size, width)) * size * LINE

    def svg(self, height):
        body = "".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{_fmt(height)}" '
            f'viewBox="0 0 {W} {_fmt(height)}">{body}</svg>'
        )


# ---- Shared furniture: title, subtitle, note, logo ----


def _title(canvas, spec):
    """The title (Inter Bold, near-black; a **phrase** in periwinkle, as in the hero headline) and the
    subtitle. Returns the y where the content starts."""
    y = M - 4
    title = spec["title"]
    size = 26
    # Words in order with their colour: a **phrase** is periwinkle, the rest near-black.
    words = [
        (word, part.startswith("**"))
        for part in re.split(r"(\*\*.+?\*\*)", title)
        for word in part.strip("*").split()
    ]
    lines = wrap(" ".join(w for w, _ in words), 700, size, W - 2 * M)
    if len(lines) > 2:
        canvas.problems.append(
            {"level": "block", "text": f"The title takes {len(lines)} lines; keep it to two."}
        )
    position = 0
    for i, line in enumerate(lines):
        x = M
        for _ in line.split():
            word, accent = words[position]
            position += 1
            colour = PERI_TEXT if accent else INK
            x += canvas.text(x, y + i * size * 1.2, word, 700, size, colour, WHITE) + text_width(
                " ", 700, size
            )
    y += len(lines) * size * 1.2 + 6
    if spec.get("subtitle"):
        y += canvas.paragraph(
            M, y, W - 2 * M, spec["subtitle"], 400, 15, MUTED, WHITE, max_lines=2, what="subtitle"
        )
    return y + 22


@cache
def _logo_markup():
    if not LOGO.is_file():
        return None, None
    svg = LOGO.read_text(encoding="utf-8")
    box = re.search(r'viewBox="([^"]+)"', svg)
    inner = re.sub(r"^.*?<svg[^>]*>|</svg>\s*$", "", svg, flags=re.S)
    inner = inner.replace("cls-1", "sdsm-blue").replace("cls-2", "sdsm-yellow")
    return (box.group(1) if box else "0 0 1504 501"), inner


LOGO_W = 92


def _footer(canvas, y, spec):
    """The note or source line (left) and the logo (bottom-right). Returns the canvas height."""
    note = spec.get("source") or spec.get("note") or ""
    if spec.get("source") and not spec["source"].lower().startswith("source"):
        note = f"Source: {spec['source']}"
    note_h = (
        canvas.paragraph(M, y, W - 2 * M - LOGO_W - 24, note, 400, 12, MUTED, WHITE, max_lines=3, what="note")
        if note
        else 0
    )
    box, inner = _logo_markup()
    logo_h = LOGO_W * 500.91 / 1503.89
    if inner is None:
        canvas.problems.append(
            {"level": "block", "text": "The SDS Manager logo isn't installed (docs/setup.md)."}
        )
    else:
        ly = y + max(note_h - logo_h, 0)
        canvas.add(
            f'<svg x="{W - M - LOGO_W}" y="{_fmt(ly)}" width="{LOGO_W}" height="{_fmt(logo_h)}" '
            f'viewBox="{box}">{inner}</svg>'
        )
    return y + max(note_h, logo_h) + 28


def _badge(canvas, cx, cy, number, fill=YELLOW, colour=INK, r=12, size=13):
    canvas.circle(cx, cy, r, fill)
    canvas.text(cx, cy - size * 0.62, str(number), 700, size, colour, fill, anchor="middle")


# ---- Templates ----


def _steps(canvas, spec, y):
    steps = spec["steps"]
    n = len(steps)
    gap = 26
    card_w = (W - 2 * M - gap * (n - 1)) / n
    inner = card_w - 20
    has_examples = any(s.get("example") for s in steps)
    label = (spec.get("example_label") or "Example").upper()
    title_h = max(canvas.height_of(s["title"], 700, 15, inner) for s in steps)
    example_h = max((canvas.height_of(s.get("example", ""), 400, 13, inner) for s in steps), default=0)
    card_h = 20 + 34 + 14 + title_h + (14 + 1 + 14 + 12 * LINE + 6 + example_h if has_examples else 0) + 18
    for i, step in enumerate(steps):
        x = M + i * (card_w + gap)
        canvas.rect(x, y, card_w, card_h, fill=LAVENDER, stroke=LAVENDER_BORDER, rx=12)
        _badge(canvas, x + card_w / 2, y + 20 + 17, i + 1, fill=PERI_DEEP, colour=WHITE, r=17, size=16)
        ty = y + 20 + 34 + 14
        canvas.paragraph(
            x + 10,
            ty,
            inner,
            step["title"],
            700,
            15,
            INK,
            LAVENDER,
            anchor="middle",
            max_lines=3,
            what=step["title"],
        )
        if has_examples:
            ry = ty + title_h + 14
            canvas.path(
                f"M{_fmt(x + 14)} {_fmt(ry)}H{_fmt(x + card_w - 14)}", stroke=LAVENDER_BORDER, width=1
            )
            canvas.text(x + card_w / 2, ry + 14, label, 700, 12, PERI_TEXT, LAVENDER, anchor="middle")
            canvas.paragraph(
                x + 10,
                ry + 14 + 12 * LINE + 6,
                inner,
                step.get("example", ""),
                400,
                13,
                INK,
                LAVENDER,
                anchor="middle",
                max_lines=5,
                what=step.get("example", ""),
            )
        if i < n - 1:
            ax = x + card_w + 6
            canvas.arrow(ax, y + card_h / 2, ax + gap - 12, y + card_h / 2)
    y += card_h
    if spec.get("loop"):
        pill_w = min(
            text_width(
                spec["loop"],
                600,
                14,
            )
            + 40,
            W - 2 * M - 120,
        )
        px, py = (W - pill_w) / 2, y + 30
        first_x, last_x = M + card_w / 2, M + (n - 1) * (card_w + gap) + card_w / 2
        canvas.path(
            f"M{_fmt(last_x)} {_fmt(y + 4)}Q{_fmt(last_x)} {_fmt(py + 18)} "
            f"{_fmt(px + pill_w)} {_fmt(py + 18)}",
            stroke=PERI,
            dash="5 5",
        )
        canvas.path(
            f"M{_fmt(px)} {_fmt(py + 18)}Q{_fmt(first_x)} {_fmt(py + 18)} {_fmt(first_x)} {_fmt(y + 12)}",
            stroke=PERI,
            dash="5 5",
        )
        canvas.arrow(first_x, y + 14, first_x, y + 4)
        canvas.rect(px, py, pill_w, 36, fill=LAVENDER, stroke=LAVENDER_BORDER, rx=18)
        canvas.paragraph(
            px + 20,
            py + 9,
            pill_w - 40,
            spec["loop"],
            600,
            14,
            PERI_TEXT,
            LAVENDER,
            anchor="middle",
            max_lines=1,
            what="loop",
        )
        y = py + 36
    return y + 26


def _decision(canvas, spec, y):
    questions = spec["questions"]
    q_w, gap = 470, 64
    o_w = W - 2 * M - q_w - gap
    for i, item in enumerate(questions):
        text_w = q_w - 70
        q_h = max(
            canvas.height_of(item["question"], 600, 15, text_w),
            canvas.height_of(item["yes"], 700, 14, o_w - 28),
        )
        box_h = q_h + 30
        canvas.rect(M, y, q_w, box_h, fill=LAVENDER, stroke=LAVENDER_BORDER, rx=10)
        _badge(canvas, M + 26, y + box_h / 2, i + 1)
        canvas.paragraph(
            M + 50,
            y + (box_h - canvas.height_of(item["question"], 600, 15, text_w)) / 2,
            text_w,
            item["question"],
            600,
            15,
            INK,
            LAVENDER,
            max_lines=4,
            what=item["question"],
        )
        ox = M + q_w + gap
        canvas.rect(ox, y, o_w, box_h, fill=PERI_DEEP, rx=10)
        canvas.paragraph(
            ox + 14,
            y + (box_h - canvas.height_of(item["yes"], 700, 14, o_w - 28)) / 2,
            o_w - 28,
            item["yes"],
            700,
            14,
            WHITE,
            PERI_DEEP,
            anchor="middle",
            max_lines=4,
            what=item["yes"],
        )
        canvas.arrow(M + q_w + 6, y + box_h / 2, ox - 6, y + box_h / 2)
        canvas.text(M + q_w + gap / 2, y + box_h / 2 - 22, "Yes", 600, 12, PERI_TEXT, WHITE, anchor="middle")
        y += box_h
        canvas.arrow(M + q_w / 2, y + 6, M + q_w / 2, y + 40)
        canvas.text(M + q_w / 2 + 12, y + 14, "No", 600, 12, PERI_TEXT, WHITE)
        y += 46
    fallback_h = canvas.height_of(spec["fallback"], 600, 15, q_w - 40) + 28
    canvas.rect(M, y, q_w, fallback_h, fill=WHITE, stroke=PERI, rx=10, dash="6 5")
    canvas.paragraph(
        M + 20, y + 14, q_w - 40, spec["fallback"], 600, 15, INK, WHITE, max_lines=3, what="fallback"
    )
    y += fallback_h + 26
    if spec.get("warning"):
        w_h = canvas.height_of(spec["warning"], 600, 14, W - 2 * M - 80) + 28
        canvas.rect(M, y, W - 2 * M, w_h, fill=YELLOW_SOFT, stroke=YELLOW_BORDER, rx=10)
        cx, cy = M + 30, y + w_h / 2
        canvas.path(f"M{cx} {_fmt(cy - 11)}L{cx + 12} {_fmt(cy + 10)}H{cx - 12}Z", stroke=INK, width=1.6)
        canvas.path(f"M{cx} {_fmt(cy - 3)}V{_fmt(cy + 3)}", stroke=INK, width=1.6)
        canvas.circle(cx, cy + 6.5, 1.2, INK)
        canvas.paragraph(
            M + 58,
            y + 14,
            W - 2 * M - 80,
            spec["warning"],
            600,
            14,
            INK,
            YELLOW_SOFT,
            max_lines=3,
            what="warning",
        )
        y += w_h + 26
    return y


def _columns(canvas, spec, y):
    columns = spec["columns"]
    gap = 24
    col_w = (W - 2 * M - gap) / 2
    styles = [(PERI_DEEP, WHITE, PERI), (YELLOW, INK, YELLOW_BORDER)]
    head_h = max(
        16
        + 15 * LINE
        + (canvas.height_of(c.get("subtitle", ""), 400, 13, col_w - 32) if c.get("subtitle") else 0)
        + 12
        for c in columns
    )
    body_h = max(
        18 + sum(canvas.height_of(item, 400, 14, col_w - 56) + 12 for item in c["items"]) + 6 for c in columns
    )
    for i, column in enumerate(columns):
        x = M + i * (col_w + gap)
        fill, text_colour, dot = styles[i]
        canvas.rect(x, y, col_w, head_h + body_h, fill=CARD, stroke=RULE, rx=12)
        canvas.rect(x, y, col_w, head_h, fill=fill, rx=12)
        canvas.rect(x, y + head_h - 12, col_w, 12, fill=fill)  # square off the header's bottom corners
        canvas.paragraph(
            x + 16,
            y + 16,
            col_w - 32,
            column["title"].upper(),
            700,
            15,
            text_colour,
            fill,
            max_lines=2,
            what=column["title"],
        )
        if column.get("subtitle"):
            canvas.paragraph(
                x + 16,
                y + 16 + 15 * LINE + 2,
                col_w - 32,
                column["subtitle"],
                400,
                13,
                text_colour,
                fill,
                max_lines=2,
                what=column["subtitle"],
            )
        iy = y + head_h + 18
        for item in column["items"]:
            canvas.circle(x + 24, iy + 9, 4, dot)
            iy += (
                canvas.paragraph(x + 38, iy, col_w - 56, item, 400, 14, INK, CARD, max_lines=3, what=item)
                + 12
            )
    return y + head_h + body_h + 24


SEGMENT_STYLES = [(PERI_DEEP, WHITE), (PERI_LIGHT, INK), (YELLOW, INK), (LAVENDER_BORDER, INK)]


def _part_to_whole(canvas, spec, y):
    segments = spec["segments"]
    total = sum(float(s["value"]) for s in segments)
    unit = spec.get("unit", "%")
    bar_w, bar_h = W - 2 * M, 64
    bracket = spec.get("bracket") or {}
    bracket_w = 0
    if bracket:
        # The label may run wider than a narrow segment (right-aligned to it); room is reserved above the bar.
        index = min(int(bracket.get("segment", len(segments) - 1)), len(segments) - 1)
        seg_w = bar_w * float(segments[index]["value"]) / total
        bracket_w = min(max(seg_w, 240), bar_w)
        y += canvas.height_of(bracket["text"], 600, 13, bracket_w) + 22
    x = M
    canvas.add(
        f'<clipPath id="bar"><rect x="{M}" y="{_fmt(y)}" width="{bar_w}" height="{bar_h}" rx="10"/>'
        "</clipPath>"
    )
    positions = []
    for i, segment in enumerate(segments):
        width = bar_w * float(segment["value"]) / total
        fill, colour = SEGMENT_STYLES[i % len(SEGMENT_STYLES)]
        canvas.add(
            f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(width)}" height="{bar_h}" fill="{fill}" '
            f'clip-path="url(#bar)"/>'
        )
        value = f"{_fmt(float(segment['value']))}{unit}"
        if text_width(value, 700, 28) + 16 > width:
            canvas.problems.append(
                {"level": "block", "text": f"The {value} segment is too narrow for its number."}
            )
        canvas.text(x + width / 2, y + (bar_h - 28) / 2 + 1, value, 700, 28, colour, fill, anchor="middle")
        positions.append((x, width))
        x += width
    if bracket:
        bx, bw = positions[index]
        top = y - 12
        canvas.path(
            f"M{_fmt(bx + 4)} {_fmt(top + 8)}V{_fmt(top)}H{_fmt(bx + bw - 4)}V{_fmt(top + 8)}",
            stroke=INK,
            width=1.4,
        )
        label_h = canvas.height_of(bracket["text"], 600, 13, bracket_w)
        lx = min(max(bx + bw / 2 - bracket_w / 2, M), W - M - bracket_w)
        canvas.paragraph(
            lx,
            top - label_h - 6,
            bracket_w,
            bracket["text"],
            600,
            13,
            INK,
            WHITE,
            anchor="middle",
            max_lines=2,
            what="bracket",
        )
    y += bar_h + 14
    label_h = 0
    for (sx, sw), segment in zip(positions, segments, strict=True):
        label_h = max(
            label_h,
            canvas.paragraph(
                sx + 4,
                y,
                sw - 8,
                segment["label"],
                600,
                14,
                INK,
                WHITE,
                anchor="middle",
                max_lines=3,
                what=segment["label"],
            ),
        )
    return y + label_h + 26


def _bars(canvas, spec, y):
    bars = sorted(spec["bars"], key=lambda b: float(b["value"]), reverse=True)
    unit = spec.get("unit", "%")
    top_value = max(float(b["value"]) for b in bars)
    scale_max = float(spec.get("max") or (100 if unit == "%" and top_value <= 100 else top_value))
    label_w = min(max(text_width(b["label"], 600, 14) for b in bars) + 16, 280)
    area_x, area_w = M + label_w, W - 2 * M - label_w - 56
    highlight = spec.get("highlight", 0)
    row_h = 38
    for tick in range(5):
        tx = area_x + area_w * tick / 4
        canvas.path(f"M{_fmt(tx)} {_fmt(y)}V{_fmt(y + row_h * len(bars))}", stroke=RULE, width=1)
    for i, bar in enumerate(bars):
        ry = y + i * row_h
        weight = 600 if i == highlight else 400
        canvas.paragraph(
            M, ry + 10, label_w - 16, bar["label"], weight, 14, INK, WHITE, max_lines=1, what=bar["label"]
        )
        bw = area_w * float(bar["value"]) / scale_max
        canvas.rect(area_x, ry + 8, max(bw, 2), 22, fill=PERI_DEEP if i == highlight else PERI_LIGHT, rx=4)
        value = f"{_fmt(float(bar['value']))}{unit}"
        # A white backing so a gridline never runs through the number.
        canvas.rect(area_x + bw + 4, ry + 8, text_width(value, 700, 14) + 8, 22, fill=WHITE)
        canvas.text(area_x + bw + 8, ry + 11, value, 700, 14, INK, WHITE)
    y += row_h * len(bars) + 8
    for tick in range(5):
        value = scale_max * tick / 4
        canvas.text(
            area_x + area_w * tick / 4, y, f"{_fmt(value)}{unit}", 400, 12, MUTED, WHITE, anchor="middle"
        )
    return y + 12 * LINE + 22


def _form_anatomy(canvas, spec, y):
    parts = spec["parts"]
    form_x, form_w = M, 330
    call_x = form_x + form_w + 44
    call_w = W - M - call_x
    header_h = 26 + canvas.height_of(spec["form_title"].upper(), 700, 14, form_w - 32)
    canvas.rect(form_x, y, form_w, header_h, fill=PERI_DEEP, rx=10)
    canvas.rect(form_x, y + header_h - 12, form_w, 12, fill=PERI_DEEP)
    canvas.paragraph(
        form_x + 16,
        y + 13,
        form_w - 32,
        spec["form_title"].upper(),
        700,
        14,
        WHITE,
        PERI_DEEP,
        max_lines=2,
        what="form title",
    )
    top = y
    y += header_h + 12
    for i, part in enumerate(parts):
        name = f"{i + 1}. {part['name']}"
        call_h = 15 * LINE + 2 + canvas.height_of(part.get("description", ""), 400, 13, call_w)
        widget = part.get("widget") or {}
        widget_h = 0
        if widget.get("type") == "split":
            half = (form_w - 24 - 46) / 2
            widget_h = max(
                canvas.height_of(label, 400, 12, half - 10) for label in widget.get("items", [])[:2] or [""]
            )
        box_h = max(64 if widget else 54, call_h + 8, 34 + widget_h + 10)
        bx = form_x + 12
        bw = form_w - 24
        canvas.rect(bx, y, bw, box_h, fill=CARD, stroke=RULE, rx=8)
        _badge(canvas, bx + 18, y + 18, i + 1, r=10, size=12)
        canvas.paragraph(
            bx + 34,
            y + 11,
            bw - 46,
            part["name"].upper(),
            700,
            12,
            PERI_TEXT,
            CARD,
            max_lines=1,
            what=part["name"],
        )
        ly = y + 34
        if widget.get("type") == "chips":
            cx = bx + 34
            for chip in widget.get("items", [])[:5]:
                cw = text_width(chip, 400, 12) + 22
                canvas.rect(cx, ly - 2, cw, 22, fill=WHITE, stroke=LAVENDER_BORDER, rx=6)
                canvas.text(cx + cw / 2, ly + 2, chip, 400, 12, MUTED, WHITE, anchor="middle")
                cx += cw + 8
        elif widget.get("type") == "split":
            half = (bw - 46) / 2
            for k, label in enumerate(widget.get("items", [])[:2]):
                canvas.paragraph(
                    bx + 34 + k * half,
                    ly - 2,
                    half - 10,
                    label,
                    400,
                    12,
                    MUTED,
                    CARD,
                    max_lines=2,
                    what=label,
                )
            canvas.path(
                f"M{_fmt(bx + 34 + half - 5)} {_fmt(ly - 4)}V{_fmt(y + box_h - 8)}", stroke=RULE, width=1
            )
        else:
            for k in range(2):
                lw = (bw - 50) * (1 if k == 0 else 0.7)
                canvas.path(
                    f"M{_fmt(bx + 34)} {_fmt(ly + 4 + k * 10)}H{_fmt(bx + 34 + lw)}", stroke=RULE, width=2
                )
        # The leader line and the callout.
        my = y + 18
        canvas.path(f"M{_fmt(bx + bw)} {_fmt(my)}H{_fmt(call_x - 10)}", stroke=PERI, width=1.2)
        canvas.circle(call_x - 10, my, 3, PERI)
        canvas.text(call_x, y + 9, name, 700, 15, INK, WHITE)
        if part.get("description"):
            canvas.paragraph(
                call_x,
                y + 9 + 15 * LINE + 2,
                call_w,
                part["description"],
                400,
                13,
                MUTED,
                WHITE,
                max_lines=3,
                what=part["description"],
            )
        y += box_h + 10
    canvas.rect(form_x, top, form_w, y - top + 2, stroke=LAVENDER_BORDER, rx=10, width=1.5)
    return y + 24


TEMPLATES = {
    # kind: (draw, {list field: (min, max)}, required text fields, what it is for)
    "steps": (
        _steps,
        {"steps": (3, 6)},
        ["title"],
        "Numbered steps in a row, optional example per step and loop",
    ),
    "decision": (
        _decision,
        {"questions": (2, 5)},
        ["title", "fallback"],
        "Yes/no questions down the page, a Yes outcome for each, a fallback, an optional warning",
    ),
    "columns": (
        _columns,
        {"columns": (2, 2)},
        ["title"],
        "Two columns compared, a coloured header and a bullet list each",
    ),
    "part_to_whole": (
        _part_to_whole,
        {"segments": (2, 4)},
        ["title", "source"],
        "One 100% bar split into shares, labels under, an optional bracket",
    ),
    "bars": (
        _bars,
        {"bars": (3, 8)},
        ["title", "source"],
        "Horizontal bars, sorted, the top one highlighted",
    ),
    "form_anatomy": (
        _form_anatomy,
        {"parts": (4, 10)},
        ["title", "form_title"],
        "A form drawn as a wireframe, each part numbered with a callout",
    ),
}


# ---- Spec hygiene, alt text and the build ----


def _clean(value):
    """House mechanics on every string in the spec (dashes, quotes, spacing); returns (value, fixes)."""
    fixes = {}
    if isinstance(value, str):
        fixed, counts = house.mechanical_fix(value)
        fixed = fixed.strip()
        for name, n in counts.items():
            fixes[name] = fixes.get(name, 0) + n
        return fixed, fixes
    if isinstance(value, list):
        out = []
        for item in value:
            item, item_fixes = _clean(item)
            out.append(item)
            for name, n in item_fixes.items():
                fixes[name] = fixes.get(name, 0) + n
        return out, fixes
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            item, item_fixes = _clean(item)
            out[key] = item
            for name, n in item_fixes.items():
                fixes[name] = fixes.get(name, 0) + n
        return out, fixes
    return value, fixes


def _validate(kind, spec):
    if kind not in TEMPLATES:
        raise InfographicError(f"Unknown infographic type {kind!r}; use one of {', '.join(TEMPLATES)}.")
    _, lists, required, _ = TEMPLATES[kind]
    problems = []
    for name in required:
        if not str(spec.get(name) or "").strip():
            problems.append({"level": "block", "text": f"The {name.replace('_', ' ')} is missing."})
    for name, (low, high) in lists.items():
        items = spec.get(name) or []
        if not low <= len(items) <= high:
            problems.append(
                {
                    "level": "block",
                    "text": f"{len(items)} {name.replace('_', ' ')}; this layout takes {low} to {high}.",
                }
            )
    if kind == "columns":
        for column in spec.get("columns") or []:
            if not 2 <= len(column.get("items") or []) <= 8:
                problems.append(
                    {"level": "block", "text": f"Each column takes 2 to 8 items ({column.get('title')!r})."}
                )
    if kind == "part_to_whole":
        total = sum(float(s.get("value") or 0) for s in spec.get("segments") or [])
        if spec.get("unit", "%") == "%" and abs(total - 100) > 1:
            problems.append({"level": "block", "text": f"The shares add up to {_fmt(total)}%, not 100%."})
    return problems


def alt_text(kind, spec):
    """A sentence for screen readers (10-125 characters), never the file name (ehs-seo-blog-optimized)."""
    title = spec.get("title", "").replace("**", "").rstrip(".")
    detail = {
        "steps": lambda: (
            f"{len(spec.get('steps', []))} steps from {spec['steps'][0]['title']} "
            f"to {spec['steps'][-1]['title']}"
        ),
        "decision": lambda: f"{len(spec.get('questions', []))} yes or no questions",
        "columns": lambda: " compared with ".join(c["title"] for c in spec.get("columns", [])),
        "part_to_whole": lambda: ", ".join(
            f"{_fmt(float(s['value']))}{spec.get('unit', '%')} {s['label']}" for s in spec.get("segments", [])
        ),
        "bars": lambda: (
            f"{len(spec.get('bars', []))} bars, highest "
            f"{max(spec['bars'], key=lambda b: float(b['value']))['label']}"
        ),
        "form_anatomy": lambda: f"the {len(spec.get('parts', []))} parts of the form",
    }[kind]
    try:
        text = f"{title}: {detail()}."
    except (KeyError, IndexError, TypeError, ValueError):
        text = f"{title}."
    if len(text) > 125:
        text = text[:122].rsplit(" ", 1)[0].rstrip(",:") + "..."
    return text


def numbers_missing_from(spec, article):
    """Figures in the spec (numbers, percentages) that the article doesn't contain: data must come from the
    article's own cited statistics, never be invented (ehs-seo-blog-optimized, step 4)."""
    found = set(re.findall(r"\d+(?:[.,]\d+)?", article or ""))
    values = []

    def walk(value):
        if isinstance(value, str):
            values.extend(re.findall(r"\d+(?:[.,]\d+)?", value))
        elif isinstance(value, int | float) and not isinstance(value, bool):
            values.append(_fmt(float(value)))
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key not in ("segment", "highlight", "max"):
                    walk(item)

    walk(spec)
    return sorted({value for value in values if value not in found})


def render(kind, spec, article=None):
    """Draw a template; returns an Infographic with its checks. Raises InfographicError for an unknown
    kind."""
    if missing := fonts_missing():
        raise InfographicError(f"The Inter fonts aren't installed ({', '.join(missing)}).")
    spec, fixes = _clean(spec)
    problems = _validate(kind, spec)
    if any(p["level"] == "block" for p in problems):
        return Infographic(
            kind, "", b"", b"", W, 0, alt_text(kind, spec) if spec.get("title") else "", problems
        )
    canvas = Canvas()
    y = _title(canvas, spec)
    y = TEMPLATES[kind][0](canvas, spec, y)
    height = round(_footer(canvas, y, spec))
    svg = canvas.svg(height)
    problems += canvas.problems
    if fixes:
        problems.append(
            {
                "level": "advise",
                "text": "House style fixed in the text: "
                + ", ".join(f"{name} ({n})" for name, n in fixes.items())
                + ".",
            }
        )
    # Legibility and contrast, measured on every text run that was drawn.
    small = sorted({t["text"] for t in canvas.texts if t["size"] < MIN_TEXT})
    if small:
        problems.append(
            {"level": "block", "text": f"Text under {MIN_TEXT} px at 800 px wide: {', '.join(small[:3])}."}
        )
    for run in canvas.texts:
        ratio = contrast(run["fill"], run["on"])
        if ratio < _needed_contrast(run["size"], run["weight"]):
            problems.append(
                {"level": "block", "text": f"Contrast {ratio:.1f}:1 is too low for {run['text'][:40]!r}."}
            )
            break
    if article is not None and (invented := numbers_missing_from(spec, article)):
        problems.append(
            {
                "level": "block",
                "text": f"Not in the article: {', '.join(invented[:5])}. Figures must "
                "come from the article's own sources.",
            }
        )
    alt = alt_text(kind, spec)
    if not 10 <= len(alt) <= 125:
        problems.append({"level": "advise", "text": "The alt text needs a look (10 to 125 characters)."})
    png, webp = _raster(svg)
    if len(webp) > WEBP_BUDGET:
        problems.append(
            {
                "level": "advise",
                "text": f"The WebP is {len(webp) // 1000} KB; inline images should stay under about 100 KB.",
            }
        )
    return Infographic(kind, svg, png, webp, W, height, alt, _dedupe(problems))


def _dedupe(problems):
    seen, out = set(), []
    for problem in problems:
        if problem["text"] not in seen:
            seen.add(problem["text"])
            out.append(problem)
    return out


def _raster(svg):
    import cairosvg
    from PIL import Image

    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=W * PNG_SCALE, background_color=WHITE)
    with Image.open(io.BytesIO(png)) as image:
        height = round(image.height * WEBP_WIDTH / image.width)
        out = io.BytesIO()
        image.convert("RGB").resize((WEBP_WIDTH, height), Image.LANCZOS).save(
            out, "WEBP", quality=88, method=6
        )
    return png, out.getvalue()
