"""Deterministic metrics for evaluation outputs. Hints for the human scorer, never verdicts."""

import re

from apps.quality import readability

# (US, UK) spelling pairs swept by region. Kept to unambiguous words.
SPELLING_PAIRS = [
    ("labeling", "labelling"),
    ("labeled", "labelled"),
    ("organization", "organisation"),
    ("organizations", "organisations"),
    ("organize", "organise"),
    ("organized", "organised"),
    ("analyze", "analyse"),
    ("color", "colour"),
    ("center", "centre"),
    ("behavior", "behaviour"),
    ("defense", "defence"),
    ("utilize", "utilise"),
    ("recognize", "recognise"),
    ("minimize", "minimise"),
    ("prioritize", "prioritise"),
    ("standardize", "standardise"),
    ("catalog", "catalogue"),
]
UK_SPELLING_REGIONS = {"UK", "GB", "AU", "NZ", "IE"}

META_NARRATION = [
    r"\bin this (article|post|guide|blog)\b",
    r"\blet'?s (dive|explore|take a (closer )?look)\b",
    r"\bas (mentioned|discussed|noted) (above|earlier|previously)\b",
    r"\bwe will (explore|discuss|cover|look at)\b",
    r"\bwithout further ado\b",
]


def plain_text(markdown):
    text = re.sub(r"```.*?```", " ", markdown, flags=re.S)
    text = re.sub(r"^\s*\|?\s*:?-{3,}.*$", " ", text, flags=re.M)  # table separator rows
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_`|]", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def words(text):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", text)


def headings(markdown):
    return [(len(m.group(1)), m.group(2).strip()) for m in re.finditer(r"^(#{1,6})\s+(.+)$", markdown, re.M)]


def sections(markdown):
    """Split into (H2 heading, body) pairs; text before the first H2 is the intro."""
    parts = re.split(r"^##\s+(.+)$", markdown, flags=re.M)
    result = [("(intro)", parts[0])] if parts[0].strip() else []
    result += [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    return result


def fkgl(text):
    """The studio's one reading-grade counting (apps/quality/readability.py)."""
    return readability.fkgl(plain_text(text))


def count(pattern, text):
    return len(re.findall(pattern, text, flags=re.I))


def compute(markdown, brief):
    plain = plain_text(markdown)
    word_list = words(plain)
    heads = headings(markdown)
    pkeyword = brief["pkeyword"].lower()
    h1 = next((text for level, text in heads if level == 1), "")
    first_100 = " ".join(word_list[:100]).lower()

    region = brief.get("region", "US").upper()
    expects_uk = region in UK_SPELLING_REGIONS
    wrong_variant = {}
    for us, uk in SPELLING_PAIRS:
        wrong = us if expects_uk else uk
        hits = count(rf"\b{wrong}\b", plain)
        if hits:
            wrong_variant[wrong] = hits

    checks = brief.get("checks", {})
    word_count = len(word_list)
    pkeyword_count = plain.lower().count(pkeyword)
    return {
        "word_count": word_count,
        "wordcount_target": brief.get("wordcount"),
        "wordcount_ratio": round(word_count / brief["wordcount"], 2) if brief.get("wordcount") else None,
        "fkgl": fkgl(markdown),
        "fkgl_target": brief.get("fkgl"),
        "section_fkgl": [
            {"heading": heading, "words": len(words(plain_text(body))), "fkgl": fkgl(body)}
            for heading, body in sections(markdown)
        ],
        "h1": h1,
        "h2_count": sum(1 for level, _ in heads if level == 2),
        "h3_count": sum(1 for level, _ in heads if level == 3),
        "pkeyword": {
            "in_h1": pkeyword in h1.lower(),
            "in_first_100_words": pkeyword in first_100,
            "in_headings": sum(1 for _, text in heads if pkeyword in text.lower()),
            "count": pkeyword_count,
            "density_pct": round(100 * pkeyword_count * len(pkeyword.split()) / word_count, 2)
            if word_count
            else 0,
        },
        "skeywords": {kw: plain.lower().count(kw.lower()) for kw in brief.get("skeywords", [])},
        "spelling_expected": "UK" if expects_uk else "US",
        "wrong_spelling_variant": wrong_variant,
        "accuracy_hints": {
            "good": {pattern: count(pattern, plain) for pattern in checks.get("good", [])},
            "red_flags": {pattern: count(pattern, plain) for pattern in checks.get("red_flags", [])},
        },
        "meta_narration": sum(count(pattern, plain) for pattern in META_NARRATION),
        "verify_markers": markdown.count("[VERIFY]"),
    }
