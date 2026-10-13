"""House reference data from the ehs-seo-blog-optimized skill, for the outline and draft prompts.

- The internal article index (`data/internal-article-links.md`): published sdsmanager.com articles by
  keyword and region. Its URLs count as seen, so the model may link them; no other URL may be invented.
- The product link registry (`data/product-link-registry.json`): the EHS product pages for internal links
  and the conclusion's CTA, with the deepest-relevant-page rule.

Both files are vendored unchanged in apps/quality/vendor/ehs_seo_blog/data (re-copy to update).
"""

import json
import re
from functools import cache

from apps.quality.scripts import VENDOR

DATA = VENDOR / "ehs_seo_blog" / "data"
REGION_SLUGS = {"US": "us", "UK": "uk", "AU": "au", "CA": "ca", "NZ": "nz", "EU": "us"}
STOPWORDS = set("a an and for how in is of on or the to what with your you are do does".split())


@cache
def _index_rows():
    rows = []
    for line in (DATA / "internal-article-links.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## Rows not live yet"):
            break  # planned slugs (404s) are never link targets
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[2].startswith("http"):
            rows.append({"keyword": cells[0], "region": cells[1], "url": cells[2]})
    return rows


@cache
def _registry():
    return json.loads((DATA / "product-link-registry.json").read_text(encoding="utf-8"))


def _terms(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOPWORDS and len(w) > 2}


def related_articles(brief, limit=12):
    """Index rows whose keyword shares terms with the brief, in the brief's region (or All)."""
    wanted = _terms(" ".join([brief.topic, brief.pkeyword, *(brief.skeywords or [])]))
    region = brief.region if brief.region in ("US", "UK", "AU", "CA") else "All"
    scored = []
    for row in _index_rows():
        overlap = len(wanted & _terms(row["keyword"]))
        if overlap and row["region"] in ("All", region):
            scored.append((overlap, row["region"] == region, row))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    rows, seen = [], set()
    for _, _, row in scored:
        if row["keyword"] not in seen:
            seen.add(row["keyword"])
            rows.append(row)
    return rows[:limit]


def related_articles_block(brief):
    rows = related_articles(brief)
    if not rows:
        return "(no published sdsmanager.com article matches this topic in the internal index)"
    lines = ["| Keyword | Region | URL |", "|---|---|---|"]
    lines += [f"| {r['keyword']} | {r['region']} | {r['url']} |" for r in rows]
    return "\n".join(lines)


def product_pages_block(region):
    registry = _registry()
    slug = REGION_SLUGS.get(region or "US", "us")
    lines = [f"Selection rule: {registry['selection_rule']}", "", "| Page | URL | Covers |", "|---|---|---|"]
    for page in registry["pages"]:
        url = page["url"].replace("/us/", f"/{slug}/", 1)
        lines.append(f"| {page['name']} | {url} | {page['covers']} |")
    return "\n".join(lines)
