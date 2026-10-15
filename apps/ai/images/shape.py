"""Small helpers the image adapters share: file type, aspect ratio and resolution tier."""

# The hero photo's size (apps.ai.catalog: FLUX.2 klein), asked for when a call names no size.
DEFAULT_SIZE = {"width": 1440, "height": 816}
# Resolution tiers as the image APIs name them, with the longest side they give.
TIERS = {"512": 512, "768": 768, "1K": 1024, "1.5K": 1536, "2K": 2048, "4K": 4096}


def mime_type(data):
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _ratio(text):
    try:
        width, height = (float(part) for part in text.split(":"))
    except ValueError:
        return None
    return width / height if height else None


def nearest_ratio(width, height, allowed):
    """The allowed "w:h" closest to width/height ("auto" and malformed values are skipped)."""
    wanted = width / height
    usable = [(abs(_ratio(text) - wanted), text) for text in allowed if _ratio(text)]
    return min(usable)[1] if usable else None


def resolution_for(longest_side, allowed):
    """The smallest allowed tier at least `longest_side` wide (the largest when none is), so the photo is
    never upscaled for a hero yet costs no more than it needs."""
    known = sorted((TIERS[tier], tier) for tier in allowed if tier in TIERS)
    if not known:
        return None
    return next((tier for side, tier in known if side >= longest_side), known[-1][1])
