"""The vendored skill files and their provenance (apps/quality/vendor/MANIFEST.json).

Each file copied from a Claude Code skill is listed with its source path in the skills folder and its
SHA-256. `tests/test_vendor.py` fails when a vendored file changes without the manifest being updated (an
edit here instead of in the skill), and, on a machine with the skills installed, when the skill moved on and
the copy is stale (the audit found hero_compose.py and svgify.py two versions behind). Intentional forks are
marked `"fork": "why"` and only have their own hash checked.

    python -m apps.quality.vendor_manifest            # report drift against ~/.claude/skills
    python -m apps.quality.vendor_manifest --write    # record the current hashes
"""

import hashlib
import json
import sys
from pathlib import Path

VENDOR = Path(__file__).parent / "vendor"
MANIFEST = VENDOR / "MANIFEST.json"
SKILLS = Path.home() / ".claude" / "skills"

# vendored folder -> skill folder (scripts and data keep their names; hero scripts sit flat in the vendor)
SOURCES = {
    "deslop/scripts": "deslop/scripts",
    "clarity_review/scripts": "clarity-review/scripts",
    "clean_user_facing_text/scripts": "clean-user-facing-text/scripts",
    "ehs_seo_blog/scripts": "ehs-seo-blog-optimized/scripts",
    "ehs_seo_blog/data": "ehs-seo-blog-optimized/data",
    "sds_hero_stock": "sds-hero-stock/scripts",
}
FORKS = {
    "sds_hero_stock/lama.py": "CUDA support added for the container (studio change)",
    "ehs_seo_blog/data/internal-article-links.md": (
        "published rows only: the skill's planned and not-live slugs are removed (public repository)"
    ),
}
SKIP = {"__pycache__", "assets"}


def sha256(path):
    """Of the content with LF line endings: git normalises CRLF on commit, so a Windows copy and CI's
    checkout of the same file must hash alike."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def vendored_files():
    for folder in SOURCES:
        base = VENDOR / folder
        for path in sorted(base.iterdir()) if base.is_dir() else []:
            if path.is_file() and path.name not in SKIP and path.suffix in (".py", ".json", ".tsv", ".md"):
                yield f"{folder}/{path.name}", path


def build():
    entries = {}
    for key, path in vendored_files():
        folder = key.rsplit("/", 1)[0]
        entry = {"source": f"{SOURCES[folder]}/{path.name}", "sha256": sha256(path)}
        if key in FORKS:
            entry["fork"] = FORKS[key]
        entries[key] = entry
    return entries


def load():
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


def drift(skills=SKILLS):
    """[(vendored path, reason)] for copies that differ from the skill (forks excepted)."""
    problems = []
    for key, entry in load().items():
        if entry.get("fork"):
            continue
        source = skills / entry["source"]
        if not source.exists():
            problems.append((key, f"no longer in the skill ({entry['source']})"))
        elif sha256(source) != sha256(VENDOR / key):
            problems.append((key, f"the skill's {entry['source']} has changed: copy it again"))
    return problems


if __name__ == "__main__":
    if "--write" in sys.argv:
        MANIFEST.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {MANIFEST}")
    else:
        for key, reason in drift():
            print(f"{key}: {reason}")
