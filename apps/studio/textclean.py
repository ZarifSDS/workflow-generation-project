"""Deterministic cleanup for the Final cleanup step.

M5 replaces this with the clean-user-facing-text scripts.
"""

import re
import unicodedata

# Zero-width, bidirectional control and other invisible format characters.
INVISIBLE = re.compile("[​‌‍⁠﻿­‪-‮⁦-⁩\U000e0000-\U000e007f]")
EXOTIC_SPACES = re.compile("[  -   　]")


def clean(text):
    """Return (cleaned_text, report dict)."""
    invisible = len(INVISIBLE.findall(text))
    spaces = len(EXOTIC_SPACES.findall(text))
    cleaned = INVISIBLE.sub("", text)
    cleaned = EXOTIC_SPACES.sub(" ", cleaned)
    cleaned = unicodedata.normalize("NFC", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"
    return cleaned, {"invisible_removed": invisible, "spaces_normalised": spaces}


METADATA_LABEL_LINE = re.compile(
    r"^[ \t]*(?:[-*][ \t]+)?\**(meta[ \t]+title|meta[ \t]+description|slug|tags?|excerpt)\**[ \t]*:\**"
    r"[ \t]*(.*?)[ \t]*$",
    re.I,
)
LABEL_KIND = {
    "meta title": "title",
    "meta description": "meta",
    "slug": "slug",
    "tag": "tags",
    "tags": "tags",
}


def strip_metadata_lines(article):
    """Metadata a model wrote into the article's head ("Tags: …", "Excerpt: …" under the H1) would publish as
    intro text. Lines before the first `## ` heading that are only such a label are taken out.
    Returns (article, {kind: [values]})."""
    head, sep, body = article.partition("\n## ")
    found, kept = {}, []
    for line in head.splitlines():
        match = METADATA_LABEL_LINE.match(line)
        if match and match.group(2):
            label = " ".join(match.group(1).lower().split())
            found.setdefault(LABEL_KIND.get(label, "excerpt"), []).append(match.group(2).strip().strip('"'))
        else:
            kept.append(line)
    if not found:
        return article, {}
    head = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return head + sep + body, found


def split_metadata(markdown):
    """Separate a draft's '## Metadata options' section; return (article, {kind: [options]})."""
    # "## Metadata Options:", "## SEO Metadata", "## Metadata": the block's heading as models write it.
    match = re.search(r"^##\s+(?:seo\s+)?metadata(?:\s+options)?\s*:?\s*$", markdown, re.M | re.I)
    if not match:
        article, stray = strip_metadata_lines(markdown.strip())
        return article, {kind: items[:5] for kind, items in stray.items()}
    article, meta = markdown[: match.start()].strip(), markdown[match.end() :]
    article, stray = strip_metadata_lines(article)
    found = {"title": [], "meta": [], "slug": [], "tags": [], "excerpt": []}
    for kind, items in stray.items():
        found[kind].extend(items)
    section = None
    for line in meta.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            section = next(
                (
                    kind
                    for kind, word in (
                        ("excerpt", "excerpt"),
                        ("tags", "tag"),
                        ("title", "title"),
                        ("meta", "meta"),
                        ("slug", "slug"),
                    )
                    if word in heading
                ),
                None,
            )
            continue
        if section is None:
            continue
        item = re.sub(r"^(?:[-*]|\d+[.)])\s*", "", stripped)
        item = re.sub(r"\s*\(\d+\s*(?:chars?|characters)\)$", "", item, flags=re.I)  # "(54 characters)"
        item = item.strip().strip('"').strip("`").strip()
        if item:
            found[section].append(item)
    return article, {kind: items[:5] for kind, items in found.items() if items}
