"""Guest-post brief intake from a row of the "Guest Post Plan" sheet (the ehs-outbound-blog brief sheet).

The editor copies the row (with or without the header row above it) from Google Sheets or Excel and pastes it
into the wizard. Copied rows are tab-separated, and a cell with line breaks comes quoted, so the csv module
reads them. With the header row, columns are matched by name; without it, the sheet's column order is assumed.

The sheet is filled by hand, so the parser expects what it actually holds: several anchors in one cell (one
per line) with their URLs in the next cell separated by line breaks or spaces, URLs without `https://`,
placeholders such as `---`, and word counts written as `1400-1500` or `1755.0`. Nothing is dropped silently:
an anchor without a URL is kept as `text | ` so the form asks for it, and every guess is listed in `warnings`.
"""

import csv
import io
import re
from dataclasses import dataclass, field

# The sheet's columns in order (row 2 of the "Guest Post Plan" tab), as (key, header prefix).
COLUMNS = (
    ("number", "#"),
    ("website", "website"),
    ("type", "type"),
    ("status", "status"),
    ("published", "published url"),
    ("reference", "reference guest post"),
    ("title", "proposed article topic"),
    ("pkeyword", "primary target keyword"),
    ("volume", "est. vol"),
    ("skeywords", "supporting keyword"),
    ("anchor", "anchor text"),
    ("url", "backlink url"),
    ("wordcount", "rec. word count"),
    ("notes", "angle / notes"),
    ("blog_link", "blog link"),
)

PLACEHOLDER = re.compile(r"^[\s\-–—_.]*$|^(?:n/?a|tbd|tbc|none)$", re.IGNORECASE)
URL_TOKEN = re.compile(r"(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s,;]*)?", re.IGNORECASE)
REGION_HINTS = (
    ("UK", re.compile(r"\bbritish english\b|\bUK\b|sdsmanager\.com/uk\b|\.uk\b", re.IGNORECASE)),
    ("AU", re.compile(r"\baustralian english\b|sdsmanager\.com/au\b|\.au\b", re.IGNORECASE)),
    ("NZ", re.compile(r"sdsmanager\.com/nz\b|\.nz\b", re.IGNORECASE)),
    ("CA", re.compile(r"\bcanadian english\b|sdsmanager\.com/ca\b|\.ca\b", re.IGNORECASE)),
    ("US", re.compile(r"\bamerican english\b|\bUS English\b|sdsmanager\.com/us\b", re.IGNORECASE)),
)
ANCHOR_MAX_WORDS = 8  # longer "anchors" are instructions, not link text


@dataclass
class SheetRow:
    topic: str = ""
    pkeyword: str = ""
    skeywords: list = field(default_factory=list)
    site: str = ""
    site_domain: str = ""
    anchors: list = field(default_factory=list)  # [{"text", "url"}]; url may be "" (the form asks for it)
    wordcount: int | None = None
    region: str = ""
    notes: str = ""
    source_reference: str = ""
    warnings: list = field(default_factory=list)

    def initial(self):
        """Values for the brief form."""
        values = {
            "content_type": "outbound",
            "topic": self.topic,
            "pkeyword": self.pkeyword,
            "skeywords_text": "\n".join(self.skeywords),
            "site": self.site,
            "site_domain": self.site_domain,
            "anchors_text": "\n".join(f"{a['text']} | {a['url']}".rstrip() for a in self.anchors),
            "notes": self.notes,
            "source_reference": self.source_reference,
        }
        if self.wordcount:
            values["wordcount"] = self.wordcount
        if self.region:
            values["region"] = self.region
        return {key: value for key, value in values.items() if value not in ("", None)}


class SheetRowError(ValueError):
    pass


def _clean(value):
    value = (value or "").strip()
    return "" if PLACEHOLDER.match(value) else value


def _is_header(row):
    cells = [c.strip().lower() for c in row]
    return any(c.startswith("website") for c in cells) and any(c.startswith("primary target") for c in cells)


def _by_header(header, row):
    values = {}
    for index, name in enumerate(header):
        name = name.strip().lower()
        for key, prefix in COLUMNS:
            # "Anchor Text + Backlink URL" (an older layout) is one column: read it as the anchor cell.
            if name.startswith(prefix) and key not in values:
                values[key] = row[index] if index < len(row) else ""
                break
    return values


def _by_position(row):
    keys = [key for key, _ in COLUMNS]
    if row and not re.match(r"^\s*\d+\s*$", row[0] or "") and len(row) < len(keys):
        keys = keys[1:]  # copied without the "#" column
    return dict(zip(keys, row, strict=False))


def _url(token):
    token = token.strip().rstrip(".,;)")
    return token if re.match(r"(?i)^https?://", token) else f"https://{token}"


def _wordcount(raw, warnings):
    numbers = [int(float(n)) for n in re.findall(r"\d+(?:\.\d+)?", raw.replace(",", ""))]
    if not numbers:
        return None
    if len(numbers) > 1:
        warnings.append(f"Word count '{raw}' is a range; the brief uses {numbers[0]} as the baseline.")
    return numbers[0]


def parse(text):
    """Read one pasted sheet row (optionally under its header row). Raises SheetRowError if it can't."""
    rows = [row for row in csv.reader(io.StringIO((text or "").strip("\n")), delimiter="\t") if any(row)]
    if not rows:
        raise SheetRowError("Paste a row from the Guest Post Plan sheet first.")
    header = next((row for row in rows if _is_header(row)), None)
    data = [row for row in rows if row is not header and _clean(" ".join(row))]
    if not data:
        raise SheetRowError("Only the header row was pasted. Copy the article's row too.")
    if len(data) > 1:
        raise SheetRowError("Paste one article's row at a time.")
    row = data[0]
    if len(row) < 8 and not header:
        raise SheetRowError(
            "That doesn't look like a sheet row (the cells should be tab-separated). Copy the whole row "
            "from the sheet, or the header row and the article's row together."
        )
    values = _by_header(header, row) if header else _by_position(row)
    cell = {key: _clean(values.get(key, "")) for key, _ in COLUMNS}
    result = SheetRow()
    warnings = result.warnings

    result.topic = " ".join(cell["title"].split())
    result.pkeyword = " ".join(cell["pkeyword"].split())
    if not result.topic:
        warnings.append("The row has no article title; fill in the topic.")
    if not result.pkeyword:
        warnings.append("The row has no primary target keyword; fill it in.")

    keywords = [_clean(k) for k in re.split(r"[\n,;]", cell["skeywords"])]
    # A stray "Yes"/"No" from a neighbouring checkbox column sometimes lands at the start of the cell.
    stray = [k for k in keywords if k.lower() in ("yes", "no")]
    result.skeywords = [k for k in keywords if k and k not in stray]
    if stray:
        warnings.append("Ignored a stray 'Yes'/'No' in the supporting keywords.")

    website = cell["website"]
    if website:
        match = URL_TOKEN.search(website)
        result.site = re.sub(r"(?i)^https?://", "", match.group(0)).rstrip("/") if match else website
        result.site_domain = _url(match.group(0)) if match else ""
        if result.site_domain and "/" not in result.site_domain.split("://", 1)[1]:
            result.site_domain += "/"
    if not result.site_domain:
        warnings.append("The row has no website; add the target site's URL for the site crawl.")

    # Anchors: one per line in the anchor cell; URLs in the URL cell (or after the text, older layout).
    anchor_lines = [line.strip() for line in cell["anchor"].splitlines() if _clean(line)]
    urls = [_url(m.group(0)) for m in URL_TOKEN.finditer(cell["url"])]
    texts, link_rules = [], []
    for line in anchor_lines:
        inline = URL_TOKEN.search(line) if re.search(r"https?://|\.com|/", line) else None
        if inline and not cell["url"]:
            urls.append(_url(inline.group(0)))
            line = (line[: inline.start()] + line[inline.end() :]).strip(" |:-–—")
        # Some hosts allow no product link, and the cell then holds their rule instead of anchors
        # ("no link will be provided but will cite SDS Manager in the author bio").
        if len(line.split()) > ANCHOR_MAX_WORDS:
            link_rules.append(line)
        elif line:
            texts.append(line)
    if link_rules:
        warnings.append("The anchor cell holds the host's linking rule, not anchors; it is in the notes.")
    if any(not re.match(r"(?i)^https?://", m.group(0)) for m in URL_TOKEN.finditer(cell["url"])):
        warnings.append("Added https:// to a backlink URL written without it; check it opens.")
    for index, anchor in enumerate(texts):
        result.anchors.append({"text": anchor, "url": urls[index] if index < len(urls) else ""})
    if len(texts) > len(urls):
        missing = ", ".join(f"'{a}'" for a in texts[len(urls) :])
        warnings.append(
            f"No backlink URL for {missing}; add it (the sheet's Link Targets tab lists each product's URL)."
        )
    elif len(urls) > len(texts):
        warnings.append(f"{len(urls) - len(texts)} backlink URL(s) had no anchor text and were left out.")
    if len({a["url"] for a in result.anchors if a["url"]}) < len([a for a in result.anchors if a["url"]]):
        warnings.append("Two anchors point at the same URL; each should be a different product page.")

    if cell["wordcount"]:
        result.wordcount = _wordcount(cell["wordcount"], warnings)

    hints = " ".join([cell["notes"], cell["url"], website])
    for region, pattern in REGION_HINTS:
        if pattern.search(hints):
            result.region = region
            break

    notes = []
    if cell["notes"]:
        notes.append("Host requirements (sheet): " + " ".join(cell["notes"].split()))
    if link_rules:
        notes.append("Host linking rule (sheet): " + " ".join(" ".join(link_rules).split()))
    if cell["type"] or cell["status"]:
        notes.append("Placement: " + ", ".join(v for v in (cell["type"], cell["status"]) if v) + ".")
    if cell["volume"]:
        notes.append(f"Primary keyword volume: {cell['volume']} a month (US).")
    if cell["wordcount"] and not re.fullmatch(r"\d+(?:\.0)?", cell["wordcount"]):
        notes.append(f"Recommended word count: {cell['wordcount']}.")
    if cell["reference"]:
        notes.append("Reference guest post(s) to read first: " + " ".join(cell["reference"].split()))
    result.notes = "\n".join(notes)
    number = cell["number"].split(".")[0] if cell["number"] else ""
    result.source_reference = f"Guest Post Plan sheet, entry #{number}" if number else "Guest Post Plan sheet"
    return result
