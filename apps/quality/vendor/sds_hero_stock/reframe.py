"""Reframe a stock or Gemini photo for the SDS hero layout: subject at 62% of the width, 16:9.

The layout needs the subject in the right 38% of the frame, because the headline and the
88% veil cover the left. Most stock photos centre the subject, so this crops to keep the
subject's height, shifts the subject right, and, when the photo isn't wide enough, adds
new scene on the left with a GENERATIVE fill (the new area is about 12% visible through
the veil, so it has to be real-looking scene, not a copy).

Fill modes (--fill):
  auto    (default) lama when PyTorch is installed, otherwise gemini
  gemini  writes OUT_expand.png (the photo on the wider canvas, the empty part
          flat light grey) and OUT_expand_prompt.txt. Run them in the Gemini app, save
          the result, then:  python reframe.py --merge GEMINI.png OUT.png
          The merge puts the original photo pixels back over everything Gemini wasn't
          asked to change, so the subject, PPE and tools are exactly the source's.
  lama    local LaMa inpainting (lama.py: PyTorch CPU + the big-lama model, downloaded once
          and checksum-verified). Automatic; good at continuing walls, racking and floors.
  mirror  last resort only: a blurred mirror of the left edge. Repeats are visible
          through an 88% veil.

Usage:
  python reframe.py IN.jpg OUT.png --subject L,T,R,B [--flip] [--fill auto|gemini|lama|mirror] [--scene "..."]
  python reframe.py --merge GEMINI_RESULT.png OUT.png

--subject  the subject's box as fractions of the source image: left,top,right,bottom
           (include heads, hands and the task object)
--flip     mirror the photo first, for a subject facing right. Only for photos with no text,
           numbers or logos.
--scene    a few words on the setting, used in the Gemini prompt (e.g. "warehouse packing area")
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

OUT_W, OUT_H = 1440, 810
ASPECT = 16 / 9
BLANK = (230, 230, 230)
FEATHER = 28  # px blend from generated to original at the seam

GEMINI_PROMPT = """Expand this photo to fill the flat light-grey area on the left side.
Continue the existing scene naturally into that area: {scene}, the same floor, walls, ceiling,
lighting, perspective, depth of field and colour, so it reads as one wider photograph.
Keep it calm and bright: background only, no people, no text, letters, signs, logos or labels.
Do not change anything in the existing photo. Keep the image exactly the same size and 16:9 shape."""


def geometry(W, H, box, target=0.62, margin=0.05):
    left, top, right, bottom = box[0] * W, box[1] * H, box[2] * W, box[3] * H
    h = min(H, (bottom - top) + 2 * margin * H)
    h = min(max(h, (right - left) / 0.36 / ASPECT), H)  # subject must fit in the right ~36%
    y0 = int(np.clip((top + bottom) / 2 - h / 2, 0, H - h))
    h = int(h)
    cw = int(round(h * ASPECT))
    x0 = int(round(left - target * cw))  # subject's left edge lands at `target`
    if cw <= W:
        x0 = min(x0, W - cw)
    return dict(y0=y0, h=h, cw=cw, x0=x0, pad_left=max(0, -x0), pad_right=max(0, x0 + cw - W),
                subject_left=round((left - x0) / cw, 3), subject_right=round((right - x0) / cw, 3),
                upscale=round(OUT_H / h, 2))


def place(a, g):
    """The photo on the target canvas; returns (canvas, mask of pixels that need filling)."""
    rows = a[g["y0"]:g["y0"] + g["h"]]
    canvas = np.zeros((g["h"], g["cw"], 3), np.uint8)
    canvas[:] = BLANK
    src_x0 = max(g["x0"], 0)
    dst_x0 = max(-g["x0"], 0)
    take = min(rows.shape[1] - src_x0, g["cw"] - dst_x0)
    canvas[:, dst_x0:dst_x0 + take] = rows[:, src_x0:src_x0 + take]
    mask = np.ones(canvas.shape[:2], bool)
    mask[:, dst_x0:dst_x0 + take] = False
    return canvas, mask


def merge(original, generated, mask):
    """Generated pixels only where mask is set, feathered into the original at the seam."""
    gen = np.asarray(Image.fromarray(generated).resize((original.shape[1], original.shape[0]), Image.LANCZOS)).astype(float)
    # distance into the original region, capped at FEATHER: 0 at the seam -> 1 inside
    keep = (~mask).astype(float)
    for _ in range(FEATHER // 4):
        keep = np.asarray(Image.fromarray((keep * 255).astype(np.uint8)).filter(ImageFilter.BoxBlur(2))).astype(float) / 255
    w = np.where(mask, 0.0, np.clip(keep * 2 - 1, 0, 1))[..., None]
    return (original.astype(float) * w + gen * (1 - w)).clip(0, 255).astype(np.uint8)


def fill_mirror(canvas, mask, g):
    pad = g["pad_left"]
    src = canvas[:, pad:]
    strip = src[:, :pad][:, ::-1]
    while strip.shape[1] < pad:
        strip = np.concatenate([src[:, : pad - strip.shape[1]], strip], 1)
    soft = np.asarray(Image.fromarray(np.ascontiguousarray(strip)).filter(
        ImageFilter.GaussianBlur(max(4, g["cw"] * 0.006)))).astype(float)
    w = np.clip((pad - np.arange(pad)) / 60, 0, 1)[None, :, None]
    out = canvas.copy()
    out[:, :pad] = (soft * w + strip.astype(float) * (1 - w)).astype(np.uint8)
    return out


def fill_lama(canvas, mask):
    import lama
    if not lama.available():
        sys.exit("LaMa needs PyTorch: pip install torch --index-url https://download.pytorch.org/whl/cpu"
                 " (see requirements.txt), or use --fill gemini.")
    # grow the mask a little into the photo so LaMa sees and blends the seam
    grown = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(9))) > 127
    gen = lama.inpaint(canvas, grown)
    return merge(canvas, gen, mask)


def save_out(canvas, out):
    Image.fromarray(canvas).resize((OUT_W, OUT_H), Image.LANCZOS).save(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="?")
    ap.add_argument("out")
    ap.add_argument("--subject", help="left,top,right,bottom as fractions of the source")
    ap.add_argument("--target", type=float, default=0.62)
    ap.add_argument("--flip", action="store_true")
    ap.add_argument("--fill", choices=["auto", "gemini", "lama", "mirror"], default="auto")
    ap.add_argument("--scene", default="the same setting")
    ap.add_argument("--merge", metavar="GENERATED", help="merge a Gemini expansion back for OUT")
    a = ap.parse_args()
    out = Path(a.out)
    side = out.with_name(out.stem + "_layout.json")

    if a.merge:
        lay = json.loads(side.read_text())
        canvas = np.asarray(Image.open(lay["canvas"]).convert("RGB"))
        mask = np.asarray(Image.open(lay["mask"])) > 127
        res = merge(canvas, np.asarray(Image.open(a.merge).convert("RGB")), mask)
        save_out(res, out)
        print(out, {k: lay["info"][k] for k in ("subject_left", "subject_right", "upscale")})
        print("Check the left side: new scene only, no people, text or obvious repeats.")
        return

    im = Image.open(a.src).convert("RGB")
    box = tuple(float(v) for v in a.subject.split(","))
    if a.flip:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
        box = (1 - box[2], box[1], 1 - box[0], box[3])
    arr = np.asarray(im)
    g = geometry(arr.shape[1], arr.shape[0], box, a.target)
    canvas, mask = place(arr, g)
    info = {k: g[k] for k in ("pad_left", "pad_right", "subject_left", "subject_right", "upscale")}
    info["fill_share"] = round(float(mask.mean()), 3)

    if not mask.any():
        save_out(canvas, out)
        print(out, info, "(no fill needed)")
        return
    if a.fill == "auto":
        import lama
        a.fill = "lama" if lama.available() else "gemini"
    if a.fill == "mirror":
        save_out(fill_mirror(canvas, mask, g), out)
        print(out, info, "\nWARNING: mirrored fill; repeats can show through the 88% veil. Prefer --fill gemini or lama.")
    elif a.fill == "lama":
        save_out(fill_lama(canvas, mask), out)
        print(out, info, "\nCheck the left side for smearing or repeated shapes.")
    else:
        exp = out.with_name(out.stem + "_expand.png")
        Image.fromarray(canvas).save(exp)
        msk = out.with_name(out.stem + "_mask.png")
        Image.fromarray(mask.astype(np.uint8) * 255).save(msk)
        prompt = GEMINI_PROMPT.format(scene=a.scene)
        pr = out.with_name(out.stem + "_expand_prompt.txt")
        pr.write_text(prompt, encoding="utf8")
        side.write_text(json.dumps({"canvas": str(exp), "mask": str(msk), "info": info}, indent=1))
        print(info)
        print(f"Generative fill needed for the left {100 * info['fill_share']:.0f}% of the frame.")
        print(f"1. In Gemini, attach {exp} and paste the prompt in {pr}")
        print(f"2. Save Gemini's image, then run:  python reframe.py --merge <that image> {out}")
        sys.exit(2)
    if info["upscale"] > 1.6:
        print("WARNING: upscaled %.1fx; the photo may look soft. Use a larger source." % info["upscale"])


if __name__ == "__main__":
    main()
