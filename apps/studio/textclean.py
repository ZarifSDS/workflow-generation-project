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


def split_metadata(markdown):
    """Separate a draft's '## Metadata options' section; return (article, {kind: [options]})."""
    match = re.search(r"^##\s+Metadata options\s*$", markdown, re.M | re.I)
    if not match:
        return markdown.strip(), {}
    article, meta = markdown[: match.start()].strip(), markdown[match.end() :]
    found = {"title": [], "meta": [], "slug": [], "tags": [], "excerpt": []}
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
