"""Article Markdown -> sanitised HTML, and -> StreamField blocks for ArticlePage.

Model output is untrusted: Markdown is rendered, then only harmless tags survive (nh3). Raw HTML in
the output is escaped by Markdown's own rules and stripped again by nh3.
"""

import html
import re

import markdown as md
import nh3

ALLOWED_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "code",
    "pre",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "hr",
    "br",
    "a",
}
# Tags Wagtail's rich text (Draftail) keeps for the features ArticlePage enables.
RICH_TEXT_TAGS = {"p", "h4", "ul", "ol", "li", "b", "i", "a", "br", "code", "blockquote", "hr"}
# Sections that belong to the workflow, not the article.
WORKFLOW_SECTIONS = ("Metadata options", "Changelog", "Localisation notes", "Localization notes")
VERIFY_RE = re.compile(r"\[VERIFY\]", re.IGNORECASE)


def markdown_to_html(text):
    rendered = md.markdown(text or "", extensions=["tables", "sane_lists"], output_format="html")
    return nh3.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes={"a": {"href", "title"}},
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer nofollow",
    )


def strip_workflow_sections(text):
    """Drop trailing "## Changelog"-style sections a model may have left in the article."""
    names = "|".join(re.escape(name) for name in WORKFLOW_SECTIONS)
    match = re.search(rf"^#{{2,3}}\s+(?:{names})\s*$", text or "", re.MULTILINE | re.IGNORECASE)
    return (text[: match.start()] if match else text or "").strip()


def split_h1(text):
    """(H1 text, the article without its H1). The H1 becomes the page title."""
    text = strip_workflow_sections(text)
    match = re.search(r"^#\s+(.+?)\s*#*\s*$", text, re.MULTILINE)
    if not match:
        return "", text
    return match.group(1).strip(), (text[: match.start()] + text[match.end() :]).strip()


def _plain(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _rich_text(fragment):
    """Sanitised HTML in Wagtail's rich text storage format (<b>/<i>, no headings above h4)."""
    fragment = re.sub(r"<(/?)strong>", r"<\1b>", fragment)
    fragment = re.sub(r"<(/?)em>", r"<\1i>", fragment)
    fragment = re.sub(r"</?pre>", "", fragment)
    cleaned = nh3.clean(
        fragment,
        tags=RICH_TEXT_TAGS,
        attributes={"a": {"href"}},
        url_schemes={"http", "https", "mailto"},
        link_rel=None,
    )
    return cleaned.strip()


def _table(fragment):
    rows = []
    for row in re.findall(r"<tr>(.*?)</tr>", fragment, re.DOTALL):
        rows.append([_plain(cell) for cell in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)])
    width = max((len(row) for row in rows), default=0)
    rows = [row + [""] * (width - len(row)) for row in rows]
    return {
        "data": rows,
        "first_row_is_table_header": "<th" in fragment,
        "first_col_is_header": False,
        "table_caption": "",
    }


SPLIT_RE = re.compile(r"<h([23])>(.*?)</h\1>|<table>.*?</table>", re.DOTALL)


def to_stream(text):
    """StreamField data for ArticlePage.body: [{"type": ..., "value": ...}, ...].

    H2 and H3 become heading blocks (so the page outline stays editable), Markdown tables become
    table blocks, and everything in between becomes rich text.
    """
    rendered = markdown_to_html(text)
    blocks, position = [], 0

    def add_rich(fragment):
        value = _rich_text(fragment)
        if value:
            blocks.append({"type": "paragraph", "value": value})

    for match in SPLIT_RE.finditer(rendered):
        add_rich(rendered[position : match.start()])
        if match.group(1):
            blocks.append(
                {"type": "heading", "value": {"text": _plain(match.group(2)), "level": f"h{match.group(1)}"}}
            )
        else:
            blocks.append({"type": "table", "value": _table(match.group(0))})
        position = match.end()
    add_rich(rendered[position:])
    return blocks


def verify_markers(text):
    return len(VERIFY_RE.findall(text or ""))
