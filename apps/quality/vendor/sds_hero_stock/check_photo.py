"""Check a reframed 16:9 photo against the hero photo rules before branding it.

  python check_photo.py photo.png [--subject-left 0.62]

Measures the strip just left of the subject, where the veil clears (subject_left - 12% to the
subject's edge). In the reference hero that strip is bright, so the fade reads as haze. Dark
objects there show up as grey smudges next to the headline. Also checks that the left 55% is
calm, so mirrored fill or clutter under the 88% veil does not show through.
Thresholds are advisory; the visual check in SKILL.md decides.
"""
import argparse
import json

import numpy as np
from PIL import Image
from scipy import ndimage as nd

ap = argparse.ArgumentParser()
ap.add_argument("photo")
ap.add_argument("--subject-left", type=float, default=0.62)
a = ap.parse_args()
g = np.asarray(Image.open(a.photo).convert("L").resize((720, 405))).astype(float)
sl = int(a.subject_left * 720)
strip = g[:, max(sl - 86, 0):sl]
detail = np.abs(g - nd.gaussian_filter(g, 2))
m = {
    "fade_strip_brightness": round(float(strip.mean()), 1),          # want >= 150
    "fade_strip_dark_share": round(float((strip < 90).mean()), 3),   # want <= 0.20
    "left_detail": round(float(detail[:, :396].mean()), 2),          # want <= 6 (calm under the veil)
    "subject_detail_ratio": round(float(detail[:, sl:].mean() / max(detail[:, :396].mean(), 1e-3)), 2),  # want >= 1.2
}
m["ok"] = (m["fade_strip_brightness"] >= 150 and m["fade_strip_dark_share"] <= 0.20
           and m["left_detail"] <= 6 and m["subject_detail_ratio"] >= 1.2)
print(json.dumps(m))
