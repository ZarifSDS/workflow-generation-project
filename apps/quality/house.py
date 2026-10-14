"""House-style mechanics and publishing markers (ehs-seo-blog-optimized, "The mechanical sweep blocks").

- `mechanical_fix` repairs what the sweep blocks and a machine can fix safely: em/en dashes, curly
  quotes, emoji, thematic breaks, escaped punctuation and spacing around punctuation. Invisible Unicode is
  handled by clean-user-facing-text before it.
- `find_markers` lists the working markers that must be resolved by a person before publishing:
  `[VERIFY]` (a claim to check), `[SRC: url]` (a source annotation, stripped after sign-off) and
  `[VISUAL: …]` (a visual to place). `[HERO: …]` cues are removed by Final cleanup, because the Hero
  image step makes the hero.
"""

import re

from .review import heading_name, split_sections

MARKER_PATTERNS = {
    "VERIFY": re.compile(r"\[VERIFY\]"),
    "SRC": re.compile(r"\[SRC:[^\]]*\]"),
    "VISUAL": re.compile(r"\[VISUAL:[^\]]*\]"),
}
HERO_LINE = re.compile(r"(?m)^[ \t]*\[HERO:[^\]]*\][ \t]*\n?")
EMOJI = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff️]")
THEMATIC_BREAK = re.compile(r"(?m)^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*\n?")
QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "‚": "'"})


def mechanical_fix(text):
    """Returns (fixed_text, {fix: count})."""
    counts = {}

    def count(name, pattern, replacement, value, flags=0):
        new, n = re.subn(pattern, replacement, value, flags=flags)
        if n:
            counts[name] = counts.get(name, 0) + n
        return new

    # Dashes: number ranges take a hyphen; elsewhere a comma (the house style allows a comma, colon,
    # parentheses or a new sentence; a comma is the safe mechanical choice).
    text = count("dashes", r"(\d)\s*[–—]\s*(\d)", r"\1-\2", text)
    # In a heading or a one-line title a dash separates a topic from its qualifier: a colon reads right.
    text = count("dashes", r"(?m)^(#{1,6}\s+[^\n–—]+?)\s*[–—]\s*", r"\1: ", text)
    if "\n" not in text.strip():
        text = count("dashes", r"\s*[–—]\s*", ": ", text)
    text = count("dashes", r"\s*[–—]\s*", ", ", text)
    # Typographic hyphens (U+2010, the non-breaking U+2011 some models use in "5‑minute") become plain ones.
    text = count("typographic hyphens", "[‐‑]", "-", text)
    before = text
    text = text.translate(QUOTES)
    if text != before:
        counts["curly quotes"] = sum(1 for a, b in zip(before, text, strict=True) if a != b)
    text = count("emoji", EMOJI, "", text)
    text = count("thematic breaks", THEMATIC_BREAK, "", text)
    text = count("escaped punctuation", r"\\([.,:;!?()])", r"\1", text)
    text = count("space before punctuation", r"(?<=\w) +([,.;:!?])(?=\s|$)", r"\1", text, re.M)
    text = count("missing space after comma", r",(?=[A-Za-z])", ", ", text)
    text = count("double spaces", r"(?<=\S)  +(?=\S)", " ", text)
    text = count("hero cues", HERO_LINE, "", text)
    # Models sometimes bold a link as **[text]**(url), which Markdown doesn't read as a link at all.
    text = count("broken bold links", r"\*\*\[([^\]\n]+)\]\*\*\(", r"[**\1**](", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return text, counts


def find_markers(text):
    """[{kind, text, section}] for every unresolved marker, in reading order."""
    found = []
    for heading, body in split_sections(text):
        for kind, pattern in MARKER_PATTERNS.items():
            for match in pattern.finditer(heading + body):
                found.append({"kind": kind, "text": match.group(0), "section": heading_name(heading)})
    return found


def strip_sources(text):
    """Remove `[SRC: url]` markers (after the sources were checked) without leaving stray spaces."""
    text = re.sub(r"[ \t]*\[SRC:[^\]]*\]", "", text)
    return re.sub(r" +([,.;:!?])", r"\1", text)


def describe_markers(markers, limit=8):
    counts = {}
    for marker in markers:
        counts[marker["kind"]] = counts.get(marker["kind"], 0) + 1
    summary = ", ".join(f"{n} {kind}" for kind, n in counts.items())
    where = "; ".join(f"{m['text'][:60]} in “{m['section']}”" for m in markers[:limit])
    return f"{summary}: {where}" + (" …" if len(markers) > limit else "")
