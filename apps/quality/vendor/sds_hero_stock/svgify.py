"""Turn a Gemini hero PNG into a layered, editable SVG with the exact brand layer.

Layers (bottom to top), all on a 1440x810 canvas:
  photo      the Gemini image, embedded as JPEG
  veil       vector linear gradient, measured stops (translucent, not a panel)
  glow       vector radial gradient from the bottom-left corner
  edge tint  vector periwinkle band down the right edge
  logo       the real SDS Manager logo paths from the site SVG
  headline   Inter Bold, outlined to paths (or live <text> with --live-text)

Two kinds of input are detected automatically (--photo skips detection and forces photo mode):
  photo     a Step 1 background photo: everything above is added.
  finished  a Step 2 hero that already has Gemini's veil, logo and text: Gemini's
            logo and headline are erased (inpainted over the veil) and replaced with
            the exact vector versions; Gemini's own veil is kept unless --apply-veil.

Usage:
  python svgify.py [PNG] --headline "**Topic Term:** | Grey explainer" [-o out.svg]
With no PNG, the newest PNG in sds-hero/inbox or Gemini_Generated_Image_*.png in Downloads is used.
"""
import argparse
import base64
import io
import re
from pathlib import Path

import numpy as np
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageFont

import hero_compose as hc

W, H = hc.W * hc.S, hc.H * hc.S  # 1440 x 810
PERI = "#626DF9"
GREY = "#626262"
# Veil opacity across the width, measured from 44 live template-A heroes.
VEIL_STOPS = [(0, .96), (.35, .96), (.40, .92), (.45, .77), (.50, .55),
              (.55, .31), (.60, .12), (.66, .03), (.70, 0)]
# Periwinkle share of the glow by distance from the bottom-left corner (fraction of r).
GLOW_STOPS = [(0, .53), (.30, .32), (.60, .16), (.80, .05), (1, 0)]
GLOW_R = 640
LOGO_SVG = hc.HERE / "assets" / "sds-manager-logo.svg"


# ---------- input ----------

def newest_gemini_png():
    """Newest PNG in sds-hero/inbox, else the newest Gemini download."""
    cands = list((hc.HERE / "inbox").glob("*.png"))
    cands += list((Path.home() / "Downloads").glob("Gemini_Generated_Image_*.png"))
    if not cands:
        raise SystemExit("No PNG given, none in sds-hero/inbox and no Gemini_Generated_Image_*.png in Downloads.")
    return max(cands, key=lambda p: p.stat().st_mtime)


def is_finished(img):
    """A Step 2 hero: a bright veil on the left 30% with text-like ink on it (headline, logo).

    The veil can be tinted (Gemini often makes it periwinkle), so brightness alone isn't enough;
    a raw photo can also be bright on the left, so ink alone isn't enough either.
    """
    a = np.asarray(img.convert("RGB").resize((720, 405))).astype(int)
    left = a[:, :216]
    lum = left.mean(2)
    R, G, B = left[..., 0], left[..., 1], left[..., 2]
    bright_veil = np.median(lum) > 200
    # saturated periwinkle/blue strokes or dark-grey strokes in the headline band
    band = left[90:300]
    bl = (band[..., 2] - band[..., 0] > 50) & (band.mean(2) < 190)
    grey = (np.abs(band[..., 0] - band[..., 2]) < 20) & (band.mean(2) < 130)
    ink = (bl | grey).mean()
    return bool(np.median(lum) > 225 or (bright_veil and ink > 0.02))


# ---------- erase Gemini's logo and headline ----------

def erase_brand(img):
    import cv2  # only needed for finished heroes; photo mode works without OpenCV
    a = np.asarray(img.convert("RGB"))
    ai = a.astype(int)
    R, G, B = ai[..., 0], ai[..., 1], ai[..., 2]
    lum = ai.mean(2)
    gray = lum.astype(np.uint8)
    # thin dark strokes (text) stand out against the veil in a black-hat transform
    bh = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31)))
    ink = (bh > 22) | ((B - R > 50) & (lum < 205)) | ((R > 190) & (G > 130) & (B < 140) & (R - B > 80))
    mask = np.zeros(ink.shape, bool)

    # logo: everything ink-like in the top-left corner box
    lz = ink[: int(H * 0.26), : int(W * 0.32)]
    ys, xs = np.nonzero(lz)
    if len(xs):
        mask[max(ys.min() - 6, 0): ys.max() + 7, max(xs.min() - 6, 0): xs.max() + 7] = True

    # headline: rows with ink in the opaque part of the veil (x 6-34% W), each
    # line followed rightwards until a gap wider than a word space
    y0, y1 = int(H * 0.22), int(H * 0.78)
    rows = ink[y0:y1, int(W * 0.06): int(W * 0.34)].sum(1) > 2
    lines, start = [], None
    for i, r in enumerate(np.append(rows, False)):
        if r and start is None:
            start = i
        elif not r and start is not None:
            if i - start >= 8:
                lines.append((y0 + start, y0 + i))
            start = None
    for ly0, ly1 in lines:
        band = ink[ly0:ly1, : int(W * 0.66)]
        cols = band.any(0)
        xs = np.nonzero(cols)[0]
        if not len(xs):
            continue
        x, gap, right = xs[0], 0, xs[0]
        while x < len(cols):
            gap = 0 if cols[x] else gap + 1
            if cols[x]:
                right = x
            if gap > 45:
                break
            x += 1
        mask[ly0 - 6: ly1 + 6, max(xs[0] - 6, 0): right + 7] |= ink[ly0 - 6: ly1 + 6, max(xs[0] - 6, 0): right + 7]
    mask = cv2.dilate(mask.astype(np.uint8) * 255, np.ones((7, 7), np.uint8))
    out = cv2.inpaint(np.ascontiguousarray(a[..., ::-1]), mask, 9, cv2.INPAINT_TELEA)[..., ::-1]
    return Image.fromarray(out), int((mask > 0).sum()), len(lines)


def soften_panel_edge(img, band=0.05):
    """Blur a hard panel edge from another tool (e.g. Gemini's curved veil) into a soft transition.

    Row by row, the edge is where the smooth panel on the left meets photo detail; a band
    around it (default 5% of the width on each side) is replaced by a heavily blurred copy,
    feathered in and out. Returns the image and the edge's x range (fractions of the width).
    """
    from scipy import ndimage as nd
    a = np.asarray(img.convert("RGB")).astype(float)
    h, w = a.shape[:2]
    L = a.mean(2)
    detail = nd.uniform_filter(np.abs(L - nd.gaussian_filter(L, 3)), 15)
    lo, hi = int(w * 0.42), int(w * 0.78)
    ref = np.median(detail[:, int(w * 0.05):int(w * 0.25)])
    edge = np.full(h, np.nan)
    for y in range(h):
        hit = np.nonzero(detail[y, lo:hi] > max(4 * ref, 2.0))[0]
        if len(hit):
            edge[y] = lo + hit[0]
    ok = ~np.isnan(edge)
    if ok.mean() < 0.5:
        return img, None
    edge = np.interp(np.arange(h), np.nonzero(ok)[0], edge[ok])
    edge = nd.median_filter(edge, size=max(31, h // 20))
    xs = np.arange(w)[None, :]
    d = np.abs(xs - edge[:, None]) / (band * w)
    weight = np.clip(1 - d, 0, 1) ** 0.7  # 1 on the edge, 0 at the band's sides
    blurred = np.stack([nd.gaussian_filter(a[..., c], w * 0.02) for c in range(3)], -1)
    out = a * (1 - weight[..., None]) + blurred * weight[..., None]
    return Image.fromarray(out.clip(0, 255).astype(np.uint8)), (round(edge.min() / w, 3), round(edge.max() / w, 3))


# ---------- vector pieces ----------

def stops(pairs, color):
    return "".join(f'<stop offset="{o:g}" stop-color="{color}" stop-opacity="{a:g}"/>' for o, a in pairs)


def gradient_defs(fade=None):
    import overlay
    band_h = [(0, .42), (.17, .25), (.33, .155), (.5, .094), (.67, .057), (1, .02)]
    band_v = [(0, 1), (.15, 1), (.37, .55), (.62, .29), (.81, .1), (1, 0)]
    return (
        f'<linearGradient id="grad-veil" x1="0" y1="0" x2="1" y2="0">{stops(overlay.veil_stops(fade), "#FCFCFC")}</linearGradient>'
        f'<radialGradient id="grad-glow" gradientUnits="userSpaceOnUse" cx="0" cy="{H}" r="{GLOW_R}">'
        f'{stops(GLOW_STOPS, PERI)}</radialGradient>'
        f'<linearGradient id="bandH" gradientUnits="userSpaceOnUse" x1="{W}" y1="0" x2="{W - 660}" y2="0">'
        f'{stops(band_h, PERI)}</linearGradient>'
        f'<linearGradient id="bandV" x1="0" y1="0" x2="0" y2="1">{stops(band_v, "#FFFFFF")}</linearGradient>'
        f'<mask id="bandMask"><rect width="{W}" height="{H}" fill="url(#bandV)"/></mask>'
    )


def gradient_layers():
    return (
        f'<g id="veil"><rect width="{W}" height="{H}" fill="url(#grad-veil)"/></g>'
        f'<g id="glow"><rect width="{W}" height="{H}" fill="url(#grad-glow)"/></g>'
        f'<g id="edge-tint" mask="url(#bandMask)"><rect width="{W}" height="{H}" fill="url(#bandH)"/></g>'
    )


def logo_layer(t):
    svg = LOGO_SVG.read_text(encoding="utf8")
    vb = re.search(r'viewBox="([^"]+)"', svg).group(1)
    inner = re.sub(r"^.*?<svg[^>]*>|</svg>\s*$", "", svg, flags=re.S)
    inner = inner.replace("cls-1", "sdsm-blue").replace("cls-2", "sdsm-yellow")
    x, y = t["logo_xy"][0] * hc.S, t["logo_xy"][1] * hc.S
    return (f'<svg id="logo" x="{x}" y="{y}" width="{hc.LOGO_W * hc.S}" height="{hc.LOGO_H * hc.S}" '
            f'viewBox="{vb}">{inner}</svg>')


def headline_layer(headline, t, font_path, live, fade=None):
    # same fitting as hero_compose: inside the veil, at most 4 lines, flagged if too long
    fit = hc.fit_headline(headline, t, font_path, hc.text_right_limit(t, fade))
    pil, lines = fit["font"], fit["lines"]
    size = pil.size
    top = t["text_top"] * hc.S - pil.getbbox("H")[1]
    ascent = pil.getmetrics()[0]
    space = pil.getlength(" ")
    if live:
        out = []
        for i, line in enumerate(lines):
            x = t["text_x"] * hc.S
            base = top + round(i * fit["pitch"] * hc.S) + ascent
            for word, acc in line:
                out.append(f'<text x="{x:.1f}" y="{base:.1f}" font-family="Inter" font-weight="700" '
                           f'font-size="{size:g}" fill="{PERI if acc else GREY}">{word}</text>')
                x += pil.getlength(word) + space
        return '<g id="headline">' + "".join(out) + "</g>"

    tt = TTFont(font_path)
    gs, cmap, hmtx = tt.getGlyphSet(), tt.getBestCmap(), tt["hmtx"]
    scale = size / tt["head"].unitsPerEm
    paths = {PERI: [], GREY: []}
    for i, line in enumerate(lines):
        x = t["text_x"] * hc.S
        base = top + round(i * fit["pitch"] * hc.S) + ascent
        for word, acc in line:
            gx = x
            for ch in word:
                name = cmap.get(ord(ch))
                if name is None:
                    continue
                pen = SVGPathPen(gs)
                gs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, gx, base)))
                if pen.getCommands():
                    paths[PERI if acc else GREY].append(pen.getCommands())
                gx += hmtx[name][0] * scale
            x += pil.getlength(word) + space
    return ('<g id="headline">' + "".join(
        f'<path fill="{c}" d="{" ".join(ds)}"/>' for c, ds in paths.items() if ds) + "</g>")


# ---------- main ----------

def svgify(png, headline, out, template="A", focus_x=0.75, live=False, apply_veil=False, font=None, fade=None,
           soften_edge=False, force_photo=False):
    t = hc.TEMPLATES[template]
    font = font or next(str(f) for f in hc.FONTS if f.exists())
    src = Image.open(png).convert("RGB")
    finished = False if force_photo else is_finished(src.resize((W, H)))
    if finished:
        canvas = src.resize((W, H), Image.LANCZOS)  # already composed at 16:9
        canvas, erased, nlines = erase_brand(canvas)
        note = f"finished hero: erased Gemini logo + {nlines} headline line(s) ({erased} px)"
        if soften_edge:
            canvas, rng = soften_panel_edge(canvas)
            note += f"; softened a panel edge at {rng[0]:.0%}-{rng[1]:.0%} of the width" if rng else "; no panel edge found"
    else:
        canvas = hc.cover(src, W, H, focus_x)
        note = "background photo: full brand layer added"
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=90)
    photo = base64.b64encode(buf.getvalue()).decode()

    layers = [f'<image id="photo" width="{W}" height="{H}" href="data:image/jpeg;base64,{photo}"/>']
    if not finished or apply_veil:
        layers.append(gradient_layers())
    layers += [logo_layer(t), headline_layer(headline, t, font, live, fade)]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'width="{W}" height="{H}" viewBox="0 0 {W} {H}"><defs>{gradient_defs(fade)}</defs>'
           + "".join(layers) + "</svg>")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf8")
    return out, note, finished


def render_preview(svg_path):
    try:
        import resvg_py
    except ImportError:  # e.g. a sandbox without the package: the SVG itself is still complete
        return None
    png = resvg_py.svg_to_bytes(svg_path=str(svg_path), width=W)
    data = bytes(png) if not isinstance(png, str) else base64.b64decode(png)
    p = Path(svg_path).with_suffix(".preview.png")
    p.write_bytes(data)
    return p


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("png", nargs="?")
    ap.add_argument("--headline", required=True, help='"**Accent:** | grey rest" markup, as in hero_compose.py')
    ap.add_argument("-o", "--out", help="output .svg (default: <out-dir>/<title-as-filename>.svg)")
    ap.add_argument("--out-dir", default=".", help="folder for the default title-named output")
    ap.add_argument("--template", choices="ABC", default="A")
    ap.add_argument("--focus-x", type=float, default=0.75)
    ap.add_argument("--live-text", action="store_true", help="editable <text> (needs Inter installed) instead of outlines")
    ap.add_argument("--apply-veil", action="store_true", help="add the vector veil even on a finished hero")
    ap.add_argument("--soften-edge", action="store_true",
                    help="finished heroes only: blur a hard panel edge left by another tool (e.g. Gemini's curved veil)")
    ap.add_argument("--subject-left", type=float, help="subject's left edge as a fraction of the width; the veil clears just past it")
    ap.add_argument("--no-person", action="store_true", help="no person where the veil fades: the veil reaches 5%% past the subject edge")
    ap.add_argument("--fade", help="explicit fade start,end as fractions of the width, e.g. 0.45,0.61")
    ap.add_argument("--photo", action="store_true",
                    help="treat the input as a clean background photo: skip finished-hero detection "
                         "(a bright sky or sunrise on the left can be mistaken for a veil and get erased)")
    a = ap.parse_args()
    import overlay
    fade = (tuple(float(v) for v in a.fade.split(",")) if a.fade
            else overlay.subject_fade(a.subject_left or overlay.SUBJECT_LEFT, not a.no_person))
    png = Path(a.png) if a.png else newest_gemini_png()
    out = Path(a.out) if a.out else Path(a.out_dir) / (hc.title_filename(a.headline) + ".svg")
    try:
        svg, note, _ = svgify(png, a.headline, out, a.template, a.focus_x, a.live_text, a.apply_veil, fade=fade,
                              soften_edge=a.soften_edge, force_photo=a.photo)
    except hc.HeadlineTooLong as e:
        print("FLAG: " + str(e))
        raise SystemExit(3)
    prev = render_preview(svg)
    print(f"{png.name}: {note}\n  svg:     {svg} ({svg.stat().st_size // 1024} KB)\n  preview: {prev or 'skipped (optional: bootstrap.py --with-preview)'}")
