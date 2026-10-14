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

# Tolerant of spacing and case: run 20's model wrote "[ SRC: url ]", which a strict pattern let through to
# publishing. `mechanical_fix` also normalises them to the canonical form.
MARKER_PATTERNS = {
    "VERIFY": re.compile(r"\[\s*VERIFY\s*(?::[^\]]*)?\]", re.I),
    "SRC": re.compile(r"\[\s*SRC\s*:[^\]]*\]", re.I),
    "VISUAL": re.compile(r"\[\s*VISUAL\s*:[^\]]*\]", re.I),
}
LOOSE_MARKER = re.compile(r"\[\s*(VERIFY|SRC|VISUAL|HERO)\s*(?::\s*([^\]]*?))?\s*\]", re.I)


def normalise_markers(text):
    """`[ SRC: url ]`, `[verify]` and the like become `[SRC: url]`, `[VERIFY]`. Returns (text, count)."""

    def canonical(match):
        kind, value = match.group(1).upper(), match.group(2)
        if (kind == "VERIFY") == (value is not None):
            return match.group(0)  # "[VERIFY: note]" or a bare "[SRC]": not a shape to guess at
        return "[VERIFY]" if kind == "VERIFY" else f"[{kind}: {value.strip()}]"

    count = 0

    def replace(match):
        nonlocal count
        new = canonical(match)
        count += new != match.group(0)
        return new

    return LOOSE_MARKER.sub(replace, text), count


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
    text, n = normalise_markers(text)
    if n:
        counts["markers normalised"] = n
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
    # ...or as [text][https://url], a reference-style shape that doesn't link either (run 20).
    text = count("broken links", r"\[([^\]\n]+)\]\[((?:https?|wagtail)://[^\]\s]+)\]", r"[\1](\2)", text)
    # A link whose target is only [VERIFY] links nowhere: keep the words and the marker.
    text = count("links to [VERIFY]", r"\[([^\]\n]+)\]\(\s*\[VERIFY\]\s*\)", r"\1 [VERIFY]", text)
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
    text = re.sub(r"[ \t]*" + MARKER_PATTERNS["SRC"].pattern, "", normalise_markers(text)[0], flags=re.I)
    return re.sub(r" +([,.;:!?])", r"\1", text)


def describe_markers(markers, limit=8):
    counts = {}
    for marker in markers:
        counts[marker["kind"]] = counts.get(marker["kind"], 0) + 1
    summary = ", ".join(f"{n} {kind}" for kind, n in counts.items())
    where = "; ".join(f"{m['text'][:60]} in “{m['section']}”" for m in markers[:limit])
    return f"{summary}: {where}" + (" …" if len(markers) > limit else "")
