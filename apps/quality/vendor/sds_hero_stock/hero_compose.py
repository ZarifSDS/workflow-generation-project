"""Compose an SDS Manager blog hero image from a background photo.

The photo (from Gemini or stock) carries only the scene. This script adds the
brand layer exactly as measured in ../sdsmanager-hero-image-baseline.md:
the template-A overlay (white veil, bottom-left glow, right-edge tint), logo
and two-tone headline. All templates share the A overlay.

Usage:
  python hero_compose.py PHOTO "**Accent words:** grey rest" -o out --template A

Mark the periwinkle words with **double asterisks** and force a line break
with " | " (live images usually break right after the colon). Everything else is brand grey
#626262 in every template. The headline is fitted inside the veil: at most 4 lines, ending
2% of the width before the veil thins below 80%, shrinking to 85% of the template size at
most. A headline that still doesn't fit is flagged (exit code 3) for shortening, not drawn.
Writes out.webp (720x405, what the CMS serves) and out@2x.png (1440x810 master).
"""
import argparse
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
LOGO = HERE / "assets" / "sds-manager-logo.png"
# Recovered from 44 template-A heroes: per-pixel opacity from how much each
# pixel varies across images, color from their mean. Veil ~0.95 on the left
# (the photo ghosts through), fading over x 300-480 of 720; periwinkle
# deepens toward the bottom-left; faint periwinkle band down the right edge.
OVERLAY = HERE / "assets" / "overlay_A.png"
FONTS = [
    HERE / "assets" / "fonts" / "Inter-Bold.ttf",  # bundled (SIL OFL 1.1, see Inter-OFL.txt)
    Path.home() / "AppData/Local/Microsoft/Windows/Fonts/Inter-Bold.ttf",  # per-user install
    Path("C:/Windows/Fonts/Inter-Bold.ttf"),
    Path("C:/Windows/Fonts/segoeuib.ttf"),  # fallback, slightly wider and lighter
]

# Brand tokens from the site CSS. Rendered WebP measures these as
# #6269D9 / #F7CA4C, the shift is compression, not a different color.
PERIWINKLE = (0x62, 0x6D, 0xF9)
# Non-accent headline text, every template. Template-A images measure #585858;
# a #626262 fill measures the same after downscale + WebP. Live B/C images use
# #000000 / #0F1011, which is drift, not the brand grey.
GREY = (0x62, 0x62, 0x62)

# Geometry is on the 720x405 canvas and scaled by S at render time.
# Sizes are Inter Bold px, matched to live headlines on width, cap height and stroke.
TEMPLATES = {
    # standard: 76% of live images
    "A": dict(logo_xy=(71, 50), text_x=72, text_top=122, max_w=360, size=26.5,
              pitch=33, caps=False),
    # lead phrase line: 16% (live ones are black; rendered in brand grey here)
    "B": dict(logo_xy=(38, 38), text_x=38, text_top=138, max_w=393, size=33,
              pitch=40.5, caps=False),
    # all caps: 7%
    "C": dict(logo_xy=(47, 41), text_x=48, text_top=156, max_w=370, size=25,
              pitch=29, caps=True),
}
LOGO_W, LOGO_H = 108, 36
W, H, S = 720, 405, 2


def title_filename(headline):
    """File name from the visual copy: spaces -> "-", characters invalid or awkward in file names
    and URLs (: ( ) ' ? ! , / etc.) dropped, case kept. "What Is JSA: A Guide" -> "What-Is-JSA-A-Guide"."""
    text = re.sub(r"\*\*|\|", " ", headline)
    text = re.sub(r"[:/\\]", " ", text)  # separators: "ISO 9001:2026" -> "ISO-9001-2026"
    text = re.sub(r"[^A-Za-z0-9\s-]", "", text)
    return re.sub(r"-{2,}", "-", re.sub(r"\s+", "-", text.strip())).strip("-")


def cover(photo, w, h, focus_x):
    """Scale to cover w x h, cropping horizontally around focus_x (0..1)."""
    scale = max(w / photo.width, h / photo.height)
    p = photo.resize((round(photo.width * scale), round(photo.height * scale)), Image.LANCZOS)
    left = int(np.clip(focus_x * p.width - 0.78 * w, 0, p.width - w))
    top = (p.height - h) // 2
    return p.crop((left, top, left + w, top + h))


def brand_layer(img, fade=None, amax=None):
    """Lay the overlay (veil, bottom-left glow, right-edge tint) over the photo; see overlay.py."""
    import overlay
    return Image.alpha_composite(img.convert("RGBA"), overlay.make(img.size, fade, amax)).convert("RGB")


def parse_runs(headline, caps):
    """Words as (text, is_accent); a lone "|" forces a line break."""
    runs = []
    for i, part in enumerate(re.split(r"\*\*", headline)):
        for word in part.replace("|", " | ").split():
            runs.append((word.upper() if caps else word, i % 2 == 1))
    return runs


def wrap(runs, font, max_w):
    lines, line = [], []
    for word, acc in runs:
        if word == "|":
            if line:
                lines.append(line)
            line = []
            continue
        trial = " ".join(w for w, _ in line + [(word, acc)])
        if line and font.getlength(trial) > max_w:
            lines.append(line)
            line = []
        line.append((word, acc))
    if line:
        lines.append(line)
    return lines


# Headline fitting. The text must end inside the veil with clear space before it thins:
# it stops VEIL_MARGIN of the width before the point where the veil drops below
# VEIL_TEXT_MIN opacity (measured on the headline rows of this photo's veil). To fit,
# the size steps down from the template size to MIN_SCALE of it, at most MAX_LINES lines.
# Smaller than that and the headline loses the live heroes' visual weight, so it is
# flagged for shortening instead of rendered.
MAX_LINES = 4
MIN_SCALE = 0.85
VEIL_TEXT_MIN = 0.75
TEXT_MAX_X = 0.46     # never past this share of the width, however far the veil reaches
VEIL_MARGIN = 0.02


class HeadlineTooLong(Exception):
    pass


def text_right_limit(t, fade=None, amax=None):
    """Right edge for the headline on the 720 canvas, from this veil's opacity on the text rows."""
    import overlay
    a = overlay.veil_alpha(fade or overlay.subject_fade(), amax)
    rows = a[int(t["text_top"]) - 10:int(t["text_top"] + MAX_LINES * t["pitch"])]
    prof = np.median(rows, 0)
    below = np.nonzero(prof[t["text_x"]:] < VEIL_TEXT_MIN)[0]
    edge = t["text_x"] + below[0] if len(below) else W
    return min(edge - VEIL_MARGIN * W, t["text_x"] + t["max_w"], TEXT_MAX_X * W)


def recolor_lines(lines):
    """One colour per line, decided after wrapping (house rule, 2026-10-12):
    - a word that lands on a line takes that line's colour, i.e. the colour most of the line's
      characters were marked with (ties go to the line's first word), so a word moved across a
      break never stays the old colour;
    - a 4-line headline always switches colour at line 3: lines 1-2 one colour, lines 3-4 the other;
    - if the markup used both colours but every line came out the same, the last line switches,
      so the headline stays two-tone."""
    def line_colour(line):
        acc = sum(len(w) for w, a in line if a)
        grey = sum(len(w) for w, a in line if not a)
        return line[0][1] if acc == grey else acc > grey
    cols = [line_colour(ln) for ln in lines]
    if len(lines) == 4:
        cols = [cols[0], cols[0], not cols[0], not cols[0]]
    elif len(lines) > 1 and len(set(cols)) == 1 and len({a for ln in lines for _, a in ln}) == 2:
        cols[-1] = not cols[-1]
    return [[(w, c) for w, _ in ln] for ln, c in zip(lines, cols)]


def fit_headline(headline, t, font_path, right_x):
    """Largest size (template size down to MIN_SCALE) that fits in MAX_LINES within right_x."""
    avail = (right_x - t["text_x"]) * S
    runs = parse_runs(headline, t["caps"])
    text = " ".join(w for w, _ in runs if w != "|")
    # Explicit " | " breaks are the writer's line plan: first try to keep every given line
    # whole (smaller size, down to MIN_SCALE) before letting the wrapper split any of them.
    forced = sum(1 for w, _ in runs if w == "|") + 1
    if forced > 1 and forced <= MAX_LINES:
        for scale in np.arange(1.0, MIN_SCALE - 1e-9, -0.025):
            font = ImageFont.truetype(font_path, round(t["size"] * scale * S))
            lines = wrap(runs, font, avail)
            widest = max(font.getlength(" ".join(w for w, _ in ln)) for ln in lines)
            if len(lines) == forced and widest <= avail:
                return dict(font=font, scale=round(float(scale), 3), size=round(t["size"] * scale, 1),
                            pitch=t["pitch"] * scale, lines=recolor_lines(lines), right_x=round(right_x),
                            widest=round(widest / S), chars=len(text))
    for scale in np.arange(1.0, MIN_SCALE - 1e-9, -0.025):
        font = ImageFont.truetype(font_path, round(t["size"] * scale * S))
        lines = wrap(runs, font, avail)
        widest = max(font.getlength(" ".join(w for w, _ in ln)) for ln in lines)
        if len(lines) <= MAX_LINES and widest <= avail:
            return dict(font=font, scale=round(float(scale), 3), size=round(t["size"] * scale, 1),
                        pitch=t["pitch"] * scale, lines=recolor_lines(lines), right_x=round(right_x),
                        widest=round(widest / S), chars=len(text))
    font = ImageFont.truetype(font_path, round(t["size"] * MIN_SCALE * S))
    per_char = font.getlength(text) / max(len(text), 1)
    budget = int(MAX_LINES * avail / per_char * 0.85)  # 0.85: words don't pack lines perfectly
    lines = wrap(runs, font, avail)
    raise HeadlineTooLong(
        f"Headline does not fit: {len(text)} characters need {len(lines)} lines inside the veil even at "
        f"{MIN_SCALE:.0%} size ({t['size'] * MIN_SCALE:.1f}px); the limit is {MAX_LINES} lines. "
        f"Shorten it to about {budget} characters or fewer (keep the topic term in periwinkle).")


LAST_CONTRAST = None
LAST_FIT = None


def _rel_lum(c):
    c = np.asarray(c, float) / 255
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def headline_contrast(canvas, boxes):
    """WCAG contrast of each text color against the darkest 5% of the background behind it."""
    a = np.asarray(canvas.convert("RGB"))
    out = {}
    for acc, name, color in ((True, "periwinkle", PERIWINKLE), (False, "grey", GREY)):
        px = [a[y0:y1, x0:x1].reshape(-1, 3) for k, (x0, y0, x1, y1) in boxes if k == acc]
        if not px:
            continue
        bg = np.percentile(_rel_lum(np.concatenate(px)), 5)
        fg = _rel_lum(np.array(color))
        out[name] = round((max(bg, fg) + 0.05) / (min(bg, fg) + 0.05), 2)
    return out


def compose(photo_path, headline, out, template="A", focus_x=0.75, font_path=None, fade=None, amax=None):
    t = TEMPLATES[template]
    canvas = cover(Image.open(photo_path).convert("RGB"), W * S, H * S, focus_x)
    canvas = brand_layer(canvas, fade, amax)

    logo = Image.open(LOGO).convert("RGBA").resize((LOGO_W * S, LOGO_H * S), Image.LANCZOS)
    canvas.paste(logo, (t["logo_xy"][0] * S, t["logo_xy"][1] * S), logo)

    font_path = font_path or next(str(f) for f in FONTS if f.exists())
    fit = fit_headline(headline, t, font_path, text_right_limit(t, fade, amax))
    global LAST_FIT
    LAST_FIT = {k: v for k, v in fit.items() if k not in ("font", "lines")} | {"n_lines": len(fit["lines"])}
    marked = [a for w, a in parse_runs(headline, t["caps"]) if w != "|"]
    final = [(w, a) for ln in fit["lines"] for w, a in ln]
    LAST_FIT["recoloured"] = [(w, "periwinkle" if a else "grey") for (w, a), m in zip(final, marked) if a != m]
    font = fit["font"]
    draw = ImageDraw.Draw(canvas)
    space = font.getlength(" ")
    top = t["text_top"] * S - font.getbbox("H")[1]  # put cap tops at text_top
    placed = []
    for i, line in enumerate(fit["lines"]):
        x = t["text_x"] * S
        y = top + round(i * fit["pitch"] * S)
        for word, acc in line:
            placed.append((x, y, word, acc))
            x += font.getlength(word) + space
    global LAST_CONTRAST
    LAST_CONTRAST = headline_contrast(canvas, [
        (acc, tuple(int(round(v)) for v in draw.textbbox((x, y), word, font=font))) for x, y, word, acc in placed])
    for x, y, word, acc in placed:
        draw.text((x, y), word, font=font, fill=PERIWINKLE if acc else GREY)

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out.with_name(out.name + "@2x.png"))
    canvas.resize((W, H), Image.LANCZOS).save(out.with_suffix(".webp"), quality=90)
    return out.with_suffix(".webp")


def t_end(f):
    return f["widest"] + TEMPLATES["A"]["text_x"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo")
    ap.add_argument("headline", help='e.g. "**RIDDOR Reportable Incidents:** What Actually Counts"')
    ap.add_argument("-o", "--out", help="output path without extension (default: <out-dir>/<title-as-filename>)")
    ap.add_argument("--out-dir", default=".", help="folder for the default title-named outputs")
    ap.add_argument("--template", choices="ABC", default="A")
    ap.add_argument("--focus-x", type=float, default=0.75,
                    help="horizontal position of the subject in the source photo, 0-1")
    ap.add_argument("--font", help="TTF path; defaults to Inter Bold, falling back to Segoe UI Bold")
    ap.add_argument("--subject-left", type=float,
                    help="where the subject starts, as a fraction of the width (e.g. 0.62); the veil clears just before it")
    ap.add_argument("--fade", help="explicit fade start,end as fractions of the width (only end is used), e.g. 0,0.61")
    ap.add_argument("--no-person", action="store_true",
                    help="no person where the veil fades (e.g. shelving): the veil reaches 5%% past --subject-left instead of 1%%")
    a = ap.parse_args()
    import overlay
    fade = (tuple(float(v) for v in a.fade.split(",")) if a.fade
            else overlay.subject_fade(a.subject_left or overlay.SUBJECT_LEFT, not a.no_person))
    a.out = a.out or str(Path(a.out_dir) / title_filename(a.headline))
    try:
        print(compose(a.photo, a.headline, a.out, a.template, a.focus_x, a.font, fade))
    except HeadlineTooLong as e:
        print("FLAG: " + str(e))
        raise SystemExit(3)
    f = LAST_FIT
    print(f"headline: {f['n_lines']} lines at {f['size']}px ({f['scale']:.0%} of template), "
          f"widest line ends at x={t_end(f)} of 720, text limit x={f['right_x']}")
    if f.get("recoloured"):
        print("NOTE: recoloured to match their line: " + ", ".join(f"{w} -> {c}" for w, c in f["recoloured"])
              + ". If that splits a phrase, move the line break ( | ) and rerun.")
    c = LAST_CONTRAST or {}
    print("headline contrast vs darkest 5%% of background: %s" % ", ".join(f"{k} {v}:1" for k, v in c.items()))
    if c.get("grey", 9) < 3.0 or c.get("periwinkle", 9) < 2.2:
        print("WARNING: headline contrast is low; a darker or busier area of the photo sits behind the text."
              " Reframe so a calmer, brighter part of the scene is on the left.")
