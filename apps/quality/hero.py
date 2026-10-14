"""Brand a generated hero photo with the vendored sds-hero-stock scripts.

Follows the skill's steps 3-5: reframe.py (subject at 62% of the width, 16:9) -> check_photo.py ->
hero_compose.py (veil, glow, logo, fitted headline). The scripts run unchanged as subprocesses.

The brand assets (logo, overlay data) aren't in git because the repository is public; copy them
from the skill (docs/setup.md). Without them the photo is kept and branding is skipped.
"""

import ast
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from . import scripts

VENDOR_DIR = scripts.VENDOR / "sds_hero_stock"
BRAND_ASSETS = ("sds-manager-logo.png", "overlay_A.png", "veil_color.png")
TARGET_SUBJECT_LEFT = 0.62
# Without generative fill the subject can't be moved right; from here on the veil still fits
# (overlay.subject_fade keeps it within 50-70% of the width).
MIN_SUBJECT_LEFT = 0.50
# The veil is 1 - (x / end) ** 5 with end at 50-70% of the width, so it is at least 99.7% opaque over
# the left 15% even at its narrowest: a mirrored strip that narrow doesn't show.
MIRROR_MAX_FILL = 0.15
FIT_RE = re.compile(
    r"headline: (\d+) lines at ([\d.]+)px \((\d+)% of template\), "
    r"widest line ends at x=(\d+) of 720, text limit x=(\d+)"
)


class BrandingError(Exception):
    pass


# The veil is at least 96% opaque over the left 35% of the branded frame (svgify's measured stops); text in
# the photo that ends left of this is covered by the branding. A margin keeps the call conservative.
VEIL_COVERS_UNTIL = 0.30

# Guest posts: the host's lead image (ehs-outbound-blog, platform-formatting.md). A custom domain gets the
# Open Graph default the skill uses where the crawl couldn't observe a size.
HOST_SIZES = {
    "medium.com": (1500, 750),
    "substack.com": (1200, 630),
    "linkedin.com": (1280, 720),
    "ghost.io": (1200, 630),
}
DEFAULT_HOST_SIZE = (1200, 630)
SIZE_RE = re.compile(r"(\d{3,4})\s*[x×]\s*(\d{3,4})")


@dataclass
class HeroResult:
    png: bytes | None = None  # 1440x810 master (a guest post: the photo at the host's size)
    webp: bytes | None = None  # 720x405, what the CMS serves
    svg: bytes | None = (
        None  # the skill's layered, editable SVG (photo, veil, glow, edge tint, logo, headline)
    )
    metrics: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    headline_problem: str = ""  # hero_compose's "doesn't fit" message (exit code 3)
    subject_too_far_left: bool = False  # needs a generative fill or a new photo
    for_host: bool = False  # a guest post's lead image: sized for the host, never branded

    @property
    def branded(self):
        return self.png is not None and not self.for_host

    @property
    def ready(self):
        return self.png is not None


def missing_assets():
    return [name for name in BRAND_ASSETS if not (VENDOR_DIR / "assets" / name).is_file()]


def headline_markup(title, region="US", pkeyword=""):
    """The skill's headline markup: periwinkle in **, a line break at " | ".

    US/UK/CA/AU: the topic term up to the colon is periwinkle. EU: the grey lead comes first and
    the periwinkle phrase second. Without a colon the primary keyword is the periwinkle part.
    """
    title = " ".join(title.split())
    if "**" in title:
        return title
    # A colon followed by a space separates topic and qualifier; "ISO 45001:2018" keeps its colon.
    parts = re.split(r":\s+", title, maxsplit=1)
    lead, colon, rest = (parts[0], ":", parts[1]) if len(parts) == 2 else (title, "", "")
    if colon and lead.strip() and rest.strip():
        if region == "EU":
            return f"{lead.strip()}: | **{rest.strip()}**"
        return f"**{lead.strip()}:** | {rest.strip()}"
    match = re.search(re.escape(pkeyword), title, re.IGNORECASE) if pkeyword else None
    if match:
        return f"{title[: match.start()]}**{match.group(0)}**{title[match.end() :]}"
    return title


@cache
def _compose_module():
    spec = importlib.util.spec_from_file_location("sds_hero_compose", VENDOR_DIR / "hero_compose.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file_stem(markup):
    """File name from the visual copy, exactly as the skill names its outputs."""
    return _compose_module().title_filename(markup) or "hero"


def _run(script, *args, timeout=180):
    return subprocess.run(
        [sys.executable, str(VENDOR_DIR / script), *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        cwd=VENDOR_DIR,
    )


def _dict_in(text):
    match = re.search(r"\{[^{}]*\}", text)
    return ast.literal_eval(match.group(0)) if match else {}


def _fail(result, script):
    detail = (result.stderr or result.stdout).strip().splitlines()
    raise BrandingError(f"{script} failed: {detail[-1] if detail else f'exit code {result.returncode}'}")


def _is_16_9(path):
    from PIL import Image

    with Image.open(path) as image:
        return abs(image.width / image.height - 16 / 9) < 0.03


def _reframe(source, tmp, vision, flags, metrics):
    """Returns (photo path, subject_left) or None when the photo can't be used for the layout."""
    subject = vision.get("subject")
    # Flip a right-facing subject only if it has no readable text and stays on the right when flipped.
    flip = (
        vision.get("facing") == "right"
        and not vision.get("readable_text")
        and 1 - subject[2] >= MIN_SUBJECT_LEFT
    )
    if vision.get("facing") == "right" and not flip:
        flags.append(
            "The subject faces right. That's fine if they face their task; otherwise regenerate with "
            "them facing left (flipping would move them to the left side or mirror text)."
        )
    out = tmp / "photo.png"
    args = [source, out, "--subject", ",".join(f"{v:.3f}" for v in subject)]
    args += ["--scene", vision.get("scene") or "the same setting"]
    if flip:
        args.append("--flip")
    result = _run("reframe.py", *args, "--fill", "auto")
    mirrored = None
    if result.returncode == 2:
        # A narrow strip sits under the fully opaque edge of the veil, so a copied fill can't show
        # there. The user accepted the skill's mirror fill for that case (2026-10-13).
        info = _dict_in(result.stdout)
        fill_share = info.get("fill_share", 1)
        # The mirror fill covers the left pad only; with a right pad it would leave a flat grey stripe.
        if fill_share <= MIRROR_MAX_FILL and not info.get("pad_right"):
            result = _run("reframe.py", *args, "--fill", "mirror")
            mirrored = fill_share
    if result.returncode == 0:
        info = _dict_in(result.stdout)
        metrics["reframe"] = {**info, "flipped": flip, "fill": "mirror" if mirrored else "none"}
        if flip:
            flags.append("Flipped the photo so the subject faces left (it has no readable text).")
        if mirrored:
            flags.append(
                f"The left {mirrored:.0%} of the frame is a mirrored fill, under the opaque part of the "
                "veil. Check the left edge for repeated shapes."
            )
        # From the numbers: reframe.py prints its upscale warning only on the fill path, never otherwise.
        if float(info.get("upscale") or 0) > 1.6:
            flags.append(
                f"The reframed crop is upscaled {info.get('upscale')}x and may look soft. "
                "Regenerate with the subject smaller in the frame."
            )
        return out, info["subject_left"]
    if result.returncode != 2:
        _fail(result, "reframe.py")

    # Exit 2: the left side needs generative fill (LaMa isn't installed in the container).
    left = subject[0]
    metrics["reframe"] = {**_dict_in(result.stdout), "skipped": "generative fill needed"}
    if left >= MIN_SUBJECT_LEFT and _is_16_9(source):
        flags.append(
            f"The subject starts at {left:.0%} of the width instead of 62%. Moving it needs a generative "
            "fill, which isn't installed, so the photo was branded as it is. Regenerate for the "
            "standard layout with the subject further right."
        )
        return source, left
    flags.append(
        f"The subject starts at {left:.0%} of the width; the layout needs it in the right part of "
        "the frame and moving it needs a generative fill, which isn't installed. Regenerate with the "
        "subject further right."
    )
    return None


def _check_flags(check):
    flags = []
    if check["fade_strip_brightness"] < 150 or check["fade_strip_dark_share"] > 0.20:
        flags.append(
            "The strip just left of the subject is dark, so the veil's fade will show grey smudges "
            "next to the headline. Regenerate with a brighter scene there."
        )
    if check["left_detail"] > 6:
        flags.append(
            "The left side is busy; clutter will show through the veil near the headline. "
            "Regenerate with a calmer left side."
        )
    if check["subject_detail_ratio"] < 1.2:
        flags.append("The subject doesn't stand out from the left side (low detail ratio).")
    return flags


def _compose(photo, markup, subject_left, person, tmp, metrics, flags):
    out = tmp / "hero"
    args = [photo, markup, "-o", out, "--subject-left", f"{subject_left:.3f}"]
    if not person:
        args.append("--no-person")
    result = _run("hero_compose.py", *args)
    if result.returncode == 3:
        message = next((line for line in result.stdout.splitlines() if line.startswith("FLAG:")), "")
        return None, message.removeprefix("FLAG:").strip() or "The headline doesn't fit the hero."
    if result.returncode != 0:
        _fail(result, "hero_compose.py")
    fit = FIT_RE.search(result.stdout)
    if fit:
        lines, size, scale, ends, limit = fit.groups()
        metrics["headline_fit"] = {
            "lines": int(lines),
            "size_px": float(size),
            "scale_percent": int(scale),
            "ends_x": int(ends),
            "limit_x": int(limit),
        }
    contrast = dict(re.findall(r"(periwinkle|grey) ([\d.]+):1", result.stdout))
    metrics["contrast"] = {name: float(value) for name, value in contrast.items()}
    if "WARNING: headline contrast is low" in result.stdout:
        flags.append(
            "Headline contrast is low: a darker or busier part of the photo sits behind the text. "
            "Regenerate with a calmer, brighter left side."
        )
    # The skill's one-colour-per-line rule recolours a word that wrapped onto the other colour's line.
    if note := next((ln for ln in result.stdout.splitlines() if ln.startswith("NOTE: recoloured")), ""):
        flags.append(note.removeprefix("NOTE: ").strip())
    return out, ""


def to_16_9(data):
    """The photo centre-cropped to exactly 16:9 (image bytes in, PNG bytes out; unchanged when it already
    is). The image model returns 1440x816; reframe.py then can't fit a full-height subject in the width and
    leaves a flat grey stripe on the right. The vision check runs on the cropped photo, so the subject box
    it reports matches what is branded."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        if abs(width / height - 16 / 9) < 0.003:
            return data
        if width / height > 16 / 9:
            new_w = round(height * 16 / 9)
            box = ((width - new_w) // 2, 0, (width - new_w) // 2 + new_w, height)
        else:
            new_h = round(width * 9 / 16)
            box = (0, (height - new_h) // 2, width, (height - new_h) // 2 + new_h)
        out = io.BytesIO()
        image.convert("RGB").crop(box).save(out, format="PNG")
        return out.getvalue()


def brand(photo, markup, vision=None):
    """Brand `photo` (image bytes). `vision` is the vision check's dict, or None if it failed."""
    if missing := missing_assets():
        return HeroResult(
            flags=[
                f"Branding skipped: the brand assets aren't installed ({', '.join(missing)}). "
                "Copy them from the sds-hero-stock skill (docs/setup.md)."
            ]
        )
    flags, metrics = [], {"headline": markup}
    vision = vision or {}
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        source = tmp / "source.img"
        source.write_bytes(photo)
        if vision.get("subject"):
            framed = _reframe(source, tmp, vision, flags, metrics)
            if framed is None:
                return HeroResult(metrics=metrics, flags=flags, subject_too_far_left=True)
            photo_path, subject_left = framed
        else:
            flags.append(
                "The vision check didn't return a subject box, so the photo wasn't reframed and the "
                "layout assumes the subject starts at 62% of the width. Check the result yourself."
            )
            photo_path, subject_left = source, TARGET_SUBJECT_LEFT
        metrics["subject_left"] = subject_left

        result = _run("check_photo.py", photo_path, "--subject-left", f"{subject_left:.3f}")
        if result.returncode != 0:
            _fail(result, "check_photo.py")
        metrics["check"] = json.loads(result.stdout)
        flags += _check_flags(metrics["check"])

        person = vision.get("person_at_left_edge", True)
        out, headline_problem = _compose(photo_path, markup, subject_left, person, tmp, metrics, flags)
        if out is None:
            return HeroResult(metrics=metrics, flags=flags, headline_problem=headline_problem)
        return HeroResult(
            png=out.with_name(out.name + "@2x.png").read_bytes(),
            webp=out.with_suffix(".webp").read_bytes(),
            svg=_layered_svg(photo_path, markup, subject_left, person, tmp, flags),
            metrics=metrics,
            flags=flags,
        )


def _layered_svg(photo, markup, subject_left, person, tmp, flags):
    """The skill's step 5 SVG from the same reframed photo; a failure only loses the SVG (it's a flag)."""
    out = tmp / "hero.svg"
    args = [photo, "--headline", markup, "-o", out, "--subject-left", f"{subject_left:.3f}", "--photo"]
    if not person:
        args.append("--no-person")
    try:
        result = _run("svgify.py", *args)
    except (OSError, subprocess.SubprocessError) as error:
        result, detail = None, str(error)
    if result is not None and result.returncode == 0 and out.is_file():
        return out.read_bytes()
    if result is not None:
        lines = (result.stderr or result.stdout).strip().splitlines()
        detail = lines[-1] if lines else f"exit code {result.returncode}"
    flags.append(f"The layered SVG wasn't made ({detail}); the PNG and WebP are complete.")
    return None


def final_x(x, vision, metrics):
    """Where a horizontal position in the checked photo (a fraction of its width) lands in the branded
    frame: reframe.py flips, scales and shifts the photo, so the subject box's two edges give the map."""
    reframe, box = metrics.get("reframe") or {}, (vision or {}).get("subject")
    if not box or reframe.get("skipped") or "subject_left" not in reframe or box[2] <= box[0]:
        return x  # branded as it was
    left, right = box[0], box[2]
    if reframe.get("flipped"):
        x, left, right = 1 - x, 1 - right, 1 - left
    scale = (reframe["subject_right"] - reframe["subject_left"]) / (right - left)
    return reframe["subject_left"] + scale * (x - left)


def covered_by_veil(box, vision, metrics):
    """True when a text box from the vision check ends under the opaque part of the veil."""
    if not (isinstance(box, list | tuple) and len(box) == 4):
        return False
    return max(final_x(box[0], vision, metrics), final_x(box[2], vision, metrics)) <= VEIL_COVERS_UNTIL


# ---- Guest posts: the host's lead image, unbranded ----


def host_size(site_domain, note=""):
    """(width, height): a `Size: WxH` note first, then the platform's spec, then the skill's default."""
    if match := SIZE_RE.search(note or ""):
        return int(match.group(1)), int(match.group(2))
    host = re.sub(r"^https?://", "", (site_domain or "").lower()).split("/")[0].removeprefix("www.")
    for domain, size in HOST_SIZES.items():
        if host == domain or host.endswith("." + domain):
            return size
    return DEFAULT_HOST_SIZE


def for_host(photo, size, vision=None):
    """Crop the photo to the host's shape around the subject and resize it; no veil, logo or headline."""
    from PIL import Image

    width, height = size
    flags, metrics = [], {"host_size": [width, height]}
    with Image.open(io.BytesIO(photo)) as image:
        image = image.convert("RGB")
        src_w, src_h = image.size
        ratio = width / height
        crop_w, crop_h = (
            (src_w, round(src_w / ratio)) if src_w / src_h < ratio else (round(src_h * ratio), src_h)
        )
        crop_w, crop_h = min(crop_w, src_w), min(crop_h, src_h)
        box = (vision or {}).get("subject")
        centre_x = (box[0] + box[2]) / 2 * src_w if box else src_w / 2
        centre_y = (box[1] + box[3]) / 2 * src_h if box else src_h / 2
        x0 = round(min(max(centre_x - crop_w / 2, 0), src_w - crop_w))
        y0 = round(min(max(centre_y - crop_h / 2, 0), src_h - crop_h))
        if box and (box[0] * src_w < x0 or box[2] * src_w > x0 + crop_w):
            flags.append(
                f"The subject is wider than a {width}x{height} crop, so part of it is cut. Regenerate with "
                "the subject smaller in the frame."
            )
        upscale = round(max(width / crop_w, height / crop_h), 2)
        metrics["upscale"] = upscale
        if upscale > 1.6:
            flags.append(f"The crop is upscaled {upscale}x to {width}x{height} and may look soft.")
        out = io.BytesIO()
        image.crop((x0, y0, x0 + crop_w, y0 + crop_h)).resize(size, Image.LANCZOS).save(out, format="PNG")
    return HeroResult(png=out.getvalue(), metrics=metrics, flags=flags, for_host=True)


# ---- In-article ("inner") images ----

INNER_ASSETS = ("sds-manager-logo.png", "sds-manager-logo-negative.png")
INNER_FORMATS = {".png", ".jpg", ".jpeg", ".webp"}


def brand_inner(data, filename, corner="auto"):
    """Put the SDS Manager logo on an in-article image with the skill's inner_logo.py, which picks the
    corner and the regular or negative logo that clash least with the image. Returns (bytes, report);
    raises BrandingError when the image can't or shouldn't be branded (vector, animation, no assets).
    `corner` is "auto" (the skill's clash scoring) or tl, tr, bl, br to place the logo yourself."""
    suffix = Path(filename).suffix.lower()
    if suffix not in INNER_FORMATS:
        raise BrandingError(f"{suffix or 'This'} images aren't branded (vector or animated).")
    if missing := [name for name in INNER_ASSETS if not (VENDOR_DIR / "assets" / name).is_file()]:
        raise BrandingError(f"the logo files aren't installed ({', '.join(missing)}; docs/setup.md step 5)")
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / f"image{suffix}"
        source.write_bytes(data)
        out = Path(tmp) / "out"
        out.mkdir()
        corner = corner if corner in ("tl", "tr", "bl", "br") else "auto"
        result = _run("inner_logo.py", source, "--out-dir", out, "--corner", corner, timeout=120)
        if result.returncode != 0:
            _fail(result, "inner_logo.py")
        lines = [line for line in result.stdout.splitlines() if line.strip().startswith("{")]
        report = json.loads(lines[-1]) if lines else {}
        branded = out / source.name
        if not branded.is_file():
            raise BrandingError(report.get("skipped") or "the image already carries the SDS Manager logo")
        return branded.read_bytes(), report
