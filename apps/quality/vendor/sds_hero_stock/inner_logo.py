"""Place the SDS Manager logo on in-article ("inner") images: infographics, charts, maps and photos.

Every inner image gets the full logo (diamonds + chevron + "SDS MANAGER"). The script judges:

  POSITION  Each corner is scored for how much the logo would clash with the image there:
            text strokes and edges under the logo, plus text in a ring around it (adjacent
            text), plus a penalty where neither logo version would be legible. The lowest
            score wins; bottom-right, the live blog's most common spot (about a third of
            inner images), wins near-ties.
  VERSION   The regular logo (diamonds #FFC93C, wordmark #626DF9) is used unless it blends into
            what is behind it; then the negative logo (diamonds #F9C93D, wordmark #FFFFFF), which
            suits darker or busy environmental shots. The choice is by contrast against the
            actual pixels behind the logo, not by a guess about the image type.

Measured from 91 live inner images (30 articles, 5 regions, 2026-10-07), bottom-right logos:
  width     median 7.6% of the image width (middle half 6.8-9.8%)  -> 7.5%, at least 56 px
  margins   median 4.5% of the width from the side, 5.1% of the height from the edge

Usage:
  python inner_logo.py IMG [IMG ...] --out-dir DIR [--corner auto|tl|tr|bl|br]
                                    [--version auto|regular|negative] [--force] [--aspect 16:9]
Writes each image under its own name into DIR and prints one JSON line per image with the
corner and version chosen, every corner's clash score and the contrast of both versions.
An image that already carries either SDS Manager logo (regular or negative) is skipped unless --force.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as nd

HERE = Path(__file__).resolve().parent
LOGOS = {"regular": HERE / "assets" / "sds-manager-logo.png",
         "negative": HERE / "assets" / "sds-manager-logo-negative.png"}
WIDTH = 0.075          # logo width as a share of the image width
MIN_PX = 56            # never narrower than this
MARGIN_X = 0.045       # gap from the side, share of the width
MARGIN_Y = 0.05        # gap from the top/bottom, share of the height
PREFER = "br"          # house default when corners score about the same
TIE = 0.15             # a corner within 15% of the best score (or 0.02 absolute) counts as a near-tie
TIE_ABS = 0.02
MIN_CONTRAST = 2.5     # regular logo needs at least this contrast (wordmark vs background)
CORNERS = ("br", "bl", "tr", "tl")
NAMES = {"br": "bottom-right", "bl": "bottom-left", "tr": "top-right", "tl": "top-left"}


def _rel_lum(rgb):
    c = np.asarray(rgb, float) / 255
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def _contrast(l1, l2):
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def logo_box(w, h, corner):
    lw = max(MIN_PX, round(WIDTH * w))
    lh = round(lw / 3.0)  # the lockup is 3:1
    x = round(MARGIN_X * w) if corner[1] == "l" else w - round(MARGIN_X * w) - lw
    y = round(MARGIN_Y * h) if corner[0] == "t" else h - round(MARGIN_Y * h) - lh
    return x, y, lw, lh


def feature_maps(rgb):
    g = rgb.mean(2)
    # text-like strokes: thin dark-on-light (black-hat) or light-on-dark (white-hat) details
    k = np.ones((9, 9))
    strokes = np.maximum(nd.grey_closing(g, footprint=k) - g, g - nd.grey_opening(g, footprint=k))
    strokes = (strokes > 28).astype(float)
    edges = np.hypot(nd.sobel(g, 0), nd.sobel(g, 1))
    edges = np.clip(edges / 255, 0, 1)
    return strokes, edges


def clash(strokes, edges, box, w, h):
    x, y, lw, lh = box
    pad_x, pad_y = int(0.6 * lw), int(1.2 * lh)  # adjacent-text ring
    inner = (slice(y, y + lh), slice(x, x + lw))
    ring = (slice(max(0, y - pad_y), min(h, y + lh + pad_y)), slice(max(0, x - pad_x), min(w, x + lw + pad_x)))
    ring_strokes = strokes[ring].sum() - strokes[inner].sum()
    ring_area = max(1, strokes[ring].size - strokes[inner].size)
    return round(3.0 * strokes[inner].mean() + 1.0 * edges[inner].mean() + 1.5 * ring_strokes / ring_area, 4)


MIN_MARK = 6       # px: smallest diamond cluster treated as a logo
MIN_FILL = 0.10    # yellow share of the cluster box (tuned on 88 labelled live images: 63/65 logos found, 2/23 false hits)


def existing_logo(rgb):
    """True when either SDS Manager logo already sits in a corner: a cluster of true-yellow
    diamonds with a blue (regular) or white (negative) chevron below it. Advisory: the skill
    also checks each image visually, and --force overrides a wrong skip."""
    a = rgb.astype(int)
    H, W = a.shape[:2]
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    yel = (R > 175) & (G > 115) & (B < 160) & (R - B > 55) & (R >= G) & (G - B > 50)
    blue = (B - R > 45) & (B - G > 30) & (B > 130)
    white = (R > 225) & (G > 225) & (B > 225)
    for ys, xs in ((slice(0, int(.3 * H)), slice(0, int(.3 * W))), (slice(0, int(.3 * H)), slice(int(.7 * W), W)),
                   (slice(int(.7 * H), H), slice(0, int(.3 * W))), (slice(int(.7 * H), H), slice(int(.7 * W), W))):
        lab, _ = nd.label(nd.binary_dilation(yel[ys, xs], iterations=2))
        for sl in nd.find_objects(lab):
            hh, ww = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            if ww < MIN_MARK or hh < MIN_MARK or ww > 0.12 * W or abs(ww / hh - 1) > 0.6:
                continue
            if yel[ys, xs][sl].mean() < MIN_FILL:
                continue
            win = (slice(sl[0].start + hh // 2, sl[0].stop + int(.7 * hh)), slice(max(0, sl[1].start - ww // 3), sl[1].stop + ww // 3))
            if blue[ys, xs][win].sum() > 0.04 * ww * hh:
                return True
            wh_below = white[ys, xs][win].mean() if white[ys, xs][win].size else 0
            right = white[ys, xs][sl[0].start: sl[0].stop, sl[1].stop: sl[1].stop + 3 * ww]
            around = white[ys, xs][max(0, sl[0].start - hh): sl[0].stop + hh, max(0, sl[1].start - ww): sl[1].stop + 4 * ww].mean()
            if 0.08 < wh_below < 0.7 and right.size and 0.05 < right.mean() < 0.6 and around < 0.6:
                return True
    return False


def choose_version(rgb, box, forced):
    """Regular unless it blends in: compare each wordmark against the typical (median) background
    behind the logo; switch to negative only when it is clearly more legible (1.25x) or the regular
    one falls under MIN_CONTRAST. The worst case (lightest / darkest 5%) is reported too."""
    x, y, lw, lh = box
    bg = _rel_lum(rgb[y:y + lh, x:x + lw].reshape(-1, 3))
    blue, white = _rel_lum(np.array([0x62, 0x6D, 0xF9])), _rel_lum(np.array([0xFF, 0xFF, 0xFF]))
    med = np.median(bg)
    reg, neg = _contrast(blue, med), _contrast(white, med)
    if forced in LOGOS:
        version = forced
    else:
        version = "negative" if (reg < MIN_CONTRAST or neg > 1.25 * reg) and neg > reg else "regular"
    worst = _contrast(blue, np.percentile(bg, 95)) if version == "regular" else _contrast(white, np.percentile(bg, 5))
    return version, round(float(reg), 2), round(float(neg), 2), round(float(worst), 2)


def crop_to_aspect(im, aspect):
    """Crop to `aspect` (w/h) keeping the most important window: the crop slides along the long
    side and keeps the position with the most colour-weighted detail (people, hands, PPE and
    equipment rather than empty ceiling or floor); a slight pull to the centre breaks ties.
    Returns the crop and its box."""
    w, h = im.size
    if abs(w / h - aspect) < 0.005:
        return im, (0, 0, w, h)
    k = min(1.0, 800 / max(w, h))
    small = im.convert("RGB").resize((max(1, round(w * k)), max(1, round(h * k))))
    g = np.asarray(small.convert("L")).astype(float)
    hsv = np.asarray(small.convert("HSV")).astype(float)
    # detail weighted by colour: people, PPE and equipment are colourful; empty ceilings and walls
    # (beams, light fittings) have edges but little saturation, so they count for less
    energy = np.hypot(nd.sobel(g, 0), nd.sobel(g, 1)) * (0.25 + hsv[..., 1] / 255)
    if w / h > aspect:                       # too wide: slide horizontally
        cw = round(h * aspect)
        prof, span, full = energy.sum(0), round(cw * k), g.shape[1]
    else:                                    # too tall: slide vertically
        ch = round(w / aspect)
        prof, span, full = energy.sum(1), round(ch * k), g.shape[0]
    csum = np.concatenate([[0], np.cumsum(prof)])
    offs = np.arange(0, full - span + 1)
    score = (csum[offs + span] - csum[offs]) * (1 - 0.02 * np.abs(offs / max(1, full - span) - 0.5))  # centre pull = tie-breaker only
    o = int(offs[np.argmax(score)] / k)
    box = (o, 0, o + cw, h) if w / h > aspect else (0, o, w, o + ch)
    return im.crop(box), box


def place(path, out_dir, corner="auto", version="auto", force=False, aspect=None):
    im = Image.open(path)
    fmt = im.format
    rgb_im = im.convert("RGB")
    crop_box = None
    if aspect:
        rgb_im, crop_box = crop_to_aspect(rgb_im, aspect)
    w, h = rgb_im.size
    # judge on a copy at most 1600 px wide (live inner images reach 9000 px); place on the original
    k = min(1.0, 1600 / w)
    small_im = rgb_im.resize((round(w * k), round(h * k)), Image.LANCZOS) if k < 1 else rgb_im
    rgb = np.asarray(small_im)
    sh, sw = rgb.shape[:2]
    if not force and existing_logo(rgb):
        return dict(file=str(path), skipped="already has the SDS Manager logo (use --force to add another)")
    strokes, edges = feature_maps(rgb.astype(float))
    scores = {}
    for c in CORNERS:
        sc = clash(strokes, edges, logo_box(sw, sh, c), sw, sh)
        _, r, n, _ = choose_version(rgb, logo_box(sw, sh, c), "auto")
        if max(r, n) < MIN_CONTRAST:  # neither version would read here
            sc += 1.0
        scores[c] = round(sc, 4)
    if corner in CORNERS:
        chosen = corner
    else:
        best = min(scores.values())
        chosen = PREFER if scores[PREFER] <= max(best * (1 + TIE), best + TIE_ABS) else min(scores, key=scores.get)
    ver, c_reg, c_neg, c_worst = choose_version(rgb, logo_box(sw, sh, chosen), version)
    box = logo_box(w, h, chosen)
    logo = Image.open(LOGOS[ver]).convert("RGBA").resize((box[2], box[3]), Image.LANCZOS)
    out = rgb_im.convert("RGBA")
    out.alpha_composite(logo, (box[0], box[1]))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / Path(path).name
    save = out.convert("RGB") if (fmt or "").upper() in ("JPEG", "WEBP") or dest.suffix.lower() in (".jpg", ".jpeg", ".webp") else out
    kw = {"quality": 92} if dest.suffix.lower() in (".jpg", ".jpeg", ".webp") else {}
    save.save(dest, **kw)
    return dict(file=str(dest), size=[w, h], crop=crop_box, corner=NAMES[chosen], version=ver, logo_px=[box[2], box[3]],
                clash={NAMES[c]: s for c, s in scores.items()},
                contrast={"regular": c_reg, "negative": c_neg, "chosen_worst_case": c_worst},
                low_contrast=bool(max(c_reg, c_neg) < MIN_CONTRAST))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--corner", default="auto", choices=["auto", *CORNERS])
    ap.add_argument("--version", default="auto", choices=["auto", "regular", "negative"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--aspect", help="crop to this aspect first, e.g. 16:9 (keeps the most detailed window)")
    a = ap.parse_args()
    aspect = None
    if a.aspect:
        num, den = (float(v) for v in a.aspect.split(":"))
        aspect = num / den
    bad = 0
    for p in a.images:
        r = place(p, a.out_dir, a.corner, a.version, a.force, aspect)
        print(json.dumps(r))
        bad += bool(r.get("low_contrast"))
    if bad:
        print(f"WARNING: {bad} image(s) where neither logo version reaches {MIN_CONTRAST}:1 behind the logo;"
              " try --corner with a calmer corner.", file=sys.stderr)


if __name__ == "__main__":
    main()
