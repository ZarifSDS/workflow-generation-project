"""Brand overlay: translucent white veil + bottom-left periwinkle glow + right-edge tint.

Three separate layers, stacked in this order over the photo:
  veil   white #FCFCFC, fully opaque at the left edge and turning gradually more
         translucent toward the right: opacity = 1 - (x / end) ** 5, clear at `end`
         (user-approved 2026-10-11). The end follows the subject: 1% of the width past
         the subject's left edge when the fade meets a person, 5% past it for a scene
         with no person at the fade (e.g. shelving), within 50-70% of the width.
  glow   periwinkle #626DF9 at full measured strength, independent of the veil, so a
         more translucent veil doesn't wash it out (corner about #ACB0F9 over white)
  tint   periwinkle band down the right edge, ~0.42 at the top-right corner

    fade=(start, end)  `end` is where the veil turns clear (start is kept for older callers)
    fade=None          subject_fade(0.62)
    fade="average"     the measured 44-hero average overlay (assets/overlay_A.png, 96%)
"""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as nd

HERE = Path(__file__).parent
OVERLAY = HERE / "assets" / "overlay_A.png"
VEIL_COLOR = HERE / "assets" / "veil_color.png"  # measured white -> periwinkle field; the glow comes from it
PERI = np.array([0x62, 0x6D, 0xF9], float)
VEIL = np.array([0xFC, 0xFC, 0xFC], float)
AMAX = 1.0
POWER = 5          # curve shape: higher = stays opaque longer, then fades faster
PAST_PERSON = 0.01
PAST_SCENE = 0.05
W, H = 720, 405  # built at this size, then upscaled; the overlay has no fine detail
SUBJECT_LEFT = 0.62  # standard: people only in the right 38%


def ss(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def subject_fade(subject_left=SUBJECT_LEFT, person=True):
    """Where the veil ends: just past a person's edge, or further for a scene without one."""
    end = subject_left + (PAST_PERSON if person else PAST_SCENE)
    end = float(min(max(end, 0.50), 0.70))
    return 0.0, end


def veil_curve(x, end, amax=None):
    amax = AMAX if amax is None else amax
    return amax * (1 - np.clip(x / end, 0, 1) ** POWER)


def veil_alpha(fade, amax=None):
    end = fade[1]
    ys, xs = np.mgrid[0:H, 0:W].astype(float)
    rng = np.random.default_rng(7)  # mist: soft, slightly uneven, reproducible
    wobble = nd.gaussian_filter1d(rng.standard_normal(H), 18)
    wobble = 0.008 * wobble / np.abs(wobble).max()
    a = veil_curve(xs / W, end + wobble[:, None], amax)
    haze = nd.gaussian_filter(rng.standard_normal((H, W)), 22)
    haze = 0.02 * haze / np.abs(haze).max()
    return np.clip(a + haze * (a > 0.05) * (a < 0.95), 0, 1)


def glow_alpha():
    c = np.asarray(Image.open(VEIL_COLOR).convert("RGB").resize((W, H), Image.BICUBIC)).astype(float)
    g = ((255 - c[..., 0]) / (255 - PERI[0]) + (255 - c[..., 1]) / (255 - PERI[1])) / 2
    return np.clip(g, 0, 1)


def band_alpha():
    ys, xs = np.mgrid[0:H, 0:W].astype(float)
    return 0.42 * np.exp(-(W - 1 - xs) / 110) * np.exp(-np.maximum(0, ys - 60) / 300) * (1 - ss(330, 405, ys))


def stack(layers):
    """Porter-Duff 'over' for (color, alpha) layers, bottom first; returns RGBA uint8."""
    A = np.zeros((H, W))
    C = np.zeros((H, W, 3))
    for color, a in layers:
        a = a[..., None] if a.ndim == 2 else a
        A_new = a[..., 0] + A * (1 - a[..., 0])
        C = (color * a + C * (A * (1 - a[..., 0]))[..., None]) / np.maximum(A_new[..., None], 1e-6)
        A = A_new
    return np.dstack([C, A * 255]).clip(0, 255).astype(np.uint8)


def make(size=(1440, 810), fade=None, amax=None):
    if fade == "average":
        return Image.open(OVERLAY).convert("RGBA").resize(size, Image.BICUBIC)
    fade = fade or subject_fade()
    rgba = stack([(VEIL, veil_alpha(fade, amax)), (PERI, glow_alpha()), (PERI, band_alpha())])
    return Image.fromarray(rgba, "RGBA").resize(size, Image.BICUBIC)


def veil_stops(fade=None, amax=None, n=14):
    """Veil opacity stops across the width, for the SVG linear gradient."""
    if fade == "average":
        return [(0, .96), (.35, .96), (.40, .92), (.45, .77), (.50, .55),
                (.55, .31), (.60, .12), (.66, .03), (.70, 0)]
    end = (fade or subject_fade())[1]
    xs = [end * (i / n) ** 0.5 for i in range(n + 1)]  # denser stops where the curve bends
    return [(round(x, 4), round(float(veil_curve(np.array(x), end, amax)), 3)) for x in xs]
