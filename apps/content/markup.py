"""Article Markdown -> sanitised HTML, and -> StreamField blocks for ArticlePage.

Model output is untrusted: Markdown is rendered, then only harmless tags survive (nh3). Raw HTML in
the output is escaped by Markdown's own rules and stripped again by nh3. The Markdown dialect
(underline, heading anchors, wagtail:// references, FAQ blocks) is defined in apps/content/dialect.py.
"""

import html
import re
from dataclasses import dataclass, field

import markdown as md
import nh3

from . import dialect

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
    "u",
    "s",
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
    "figure",
    "figcaption",
    "img",
    "section",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height", "loading"},
    "figure": {"data-embed", "data-decorative"},
    "section": {"data-block"},
    "h2": {"id"},
    "h3": {"id"},
    "h4": {"id"},
}
URL_SCHEMES = {"http", "https", "mailto", "tel"}
IMG_WITHOUT_SOURCE = re.compile(r"<img(?![^>]*\ssrc=)[^>]*>")
# Tags Wagtail's rich text (Draftail) keeps for the features ArticlePage enables.
RICH_TEXT_TAGS = {"p", "h4", "ul", "ol", "li", "b", "i", "a", "br", "code", "blockquote", "hr"}
# Sections that belong to the workflow, not the article.
WORKFLOW_SECTIONS = ("Metadata options", "Changelog", "Localisation notes", "Localization notes")
# Editors and Markdown serialisers may escape the brackets: \[VERIFY\].
VERIFY_RE = re.compile(r"\\?\[VERIFY\\?\]", re.IGNORECASE)


class WagtailResolver(dialect.Resolver):
    """Resolves wagtail:// references against the database (image renditions, page and document URLs).

    `base_url` makes the URLs absolute, for exports that leave the admin.
    """

    def __init__(self, base_url="", rendition="max-1200x1200"):
        self.base_url = base_url.rstrip("/")
        self.rendition = rendition

    def _absolute(self, url):
        return f"{self.base_url}{url}" if url and url.startswith("/") else url

    def images(self, ids):
        from wagtail.images import get_image_model

        found = {}
        for image in get_image_model().objects.filter(pk__in=ids):
            rendition = image.get_rendition(self.rendition)
            found[image.pk] = dialect.ResolvedImage(
                self._absolute(rendition.url), rendition.width, rendition.height
            )
        return found

    def pages(self, ids):
        from wagtail.models import Page

        return {page.pk: self._absolute(page.url) for page in Page.objects.filter(pk__in=ids) if page.url}

    def documents(self, ids):
        from wagtail.documents import get_document_model

        return {doc.pk: self._absolute(doc.url) for doc in get_document_model().objects.filter(pk__in=ids)}


def render(text, resolver=None, mode="html"):
    """(sanitised HTML, warnings). mode "html" resolves references; "stream" keeps wagtail:// refs."""
    state = dialect.RenderState(mode=mode, resolver=resolver)
    rendered = md.markdown(
        text or "",
        extensions=["tables", "sane_lists", dialect.DialectExtension(state)],
        output_format="html",
    )
    base_url = getattr(resolver, "base_url", "")

    def our_image(src):
        if mode == "stream" and src.startswith(f"{dialect.REFERENCE_SCHEME}://"):
            return True
        if src.startswith("/") and not src.startswith("//"):  # site-relative, not protocol-relative
            return True
        return bool(base_url) and src.startswith(f"{base_url}/")

    def only_our_images(tag, attribute, value):
        # Raw <img> written by a model must not load anything; only resolved references may.
        if tag == "img" and attribute == "src" and not our_image(value):
            return None
        return value

    cleaned = nh3.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        attribute_filter=only_our_images,
        url_schemes=URL_SCHEMES | ({dialect.REFERENCE_SCHEME} if mode == "stream" else set()),
        link_rel="noopener noreferrer nofollow" if mode == "html" else None,
    )
    return IMG_WITHOUT_SOURCE.sub("", cleaned), state.warnings


def markdown_to_html(text, resolver=None, mode="html"):
    return render(text, resolver, mode)[0]


REF_DESTINATION = re.compile(r"\((wagtail://[^)\s]+)")


def resolve_references(text, resolver):
    """The Markdown with wagtail:// destinations replaced by real URLs, for use outside the studio.

    Embeds become plain links to their URL. References that no longer resolve are left as they are.
    """
    refs = [dialect.parse_ref(url) for url in REF_DESTINATION.findall(text or "")]
    wanted = {"image": set(), "page": set(), "document": set()}
    for kind, params in filter(None, refs):
        if kind in wanted and params.get("id", "").isdigit():
            wanted[kind].add(int(params["id"]))
    found = {
        "image": {pk: image.url for pk, image in resolver.images(wanted["image"]).items()}
        if wanted["image"]
        else {},
        "page": resolver.pages(wanted["page"]) if wanted["page"] else {},
        "document": resolver.documents(wanted["document"]) if wanted["document"] else {},
    }

    def replace(match):
        kind, params = dialect.parse_ref(match.group(1)) or (None, {})
        if kind == "media":
            return f"({params.get('url', match.group(1))}"
        target = found.get(kind, {}).get(int(params["id"])) if params.get("id", "").isdigit() else None
        return f"({target}" if target else match.group(0)

    resolved = REF_DESTINATION.sub(replace, text or "")
    # An embed written as an image would show as a broken image elsewhere: make it a link.
    return re.sub(
        r"!\[([^\]]*)\]\((https?://(?:www\.)?(?:youtube\.com|youtu\.be|vimeo\.com)[^)]*)\)",
        r"[\1](\2)",
        resolved,
    )


def strip_dialect(text):
    """The Markdown without dialect syntax, for word counts and keyword checks (headings are kept)."""
    text = re.sub(r"!\[([^\]]*)\]\(wagtail://[^)]*\)", r"\1", text or "")
    text = re.sub(r"\[([^\]]*)\]\(wagtail://[^)]*\)", r"\1", text)
    text = re.sub(r"[ \t]*\{#[A-Za-z0-9][A-Za-z0-9_-]*\}[ \t]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^:::(?:faq)?[ \t]*$", "", text, flags=re.MULTILINE)
    return re.sub(r"\+\+(.+?)\+\+", r"\1", text)


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


def _db_links(element, warnings):
    """wagtail:// links -> Wagtail's database link format; inline images can't live in rich text."""
    for link in element.iter("a"):
        ref = dialect.parse_ref(link.get("href"))
        if ref and ref[0] in ("page", "document") and ref[1].get("id", "").isdigit():
            link.attrib.pop("href", None)
            link.attrib.pop("rel", None)
            link.set("linktype", ref[0])
            link.set("id", ref[1]["id"])
    for img in list(element.iter("img")):
        warnings.append("An image inside a paragraph was left out; put images on their own line.")
        img.drop_tree()


def _rich_text(fragment, warnings):
    """Rich text in Wagtail's database format, checked against ArticlePage's rich text features."""
    from wagtail.api.rich_text import APIRichText

    from .blocks import RICH_TEXT_FEATURES

    fragment = re.sub(r"<(/?)strong>", r"<\1b>", fragment)
    fragment = re.sub(r"<(/?)em>", r"<\1i>", fragment)
    fragment = re.sub(r"</?pre>", "", fragment)
    cleaned, removals = APIRichText.sanitize_db_html(fragment, features=RICH_TEXT_FEATURES)
    warnings.extend(f"Rich text: {removal}" for removal in removals)
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


def _figure_block(element, warnings):
    from wagtail.images import get_image_model

    if element.get("data-embed"):
        return {"type": "embed", "value": element.get("data-embed")}
    img = element.find(".//img")
    ref = dialect.parse_ref(img.get("src")) if img is not None else None
    if not ref or ref[0] != "image" or not ref[1].get("id", "").isdigit():
        warnings.append("An image without a library reference was left out.")
        return None
    image_id = int(ref[1]["id"])
    if not get_image_model().objects.filter(pk=image_id).exists():
        warnings.append(f"Image {image_id} no longer exists; it was left out.")
        return None
    caption = element.find("figcaption")
    decorative = element.get("data-decorative") == "1"
    return {
        "type": "figure",
        "value": {
            "image": {"image": image_id, "decorative": decorative, "alt_text": img.get("alt", "")},
            "caption": caption.text_content().strip() if caption is not None else "",
        },
    }


def _faq_block(element, warnings):
    from lxml import html as lxml_html

    items, current, answer = [], None, []

    def close():
        if current:
            items.append({"question": current, "answer": _rich_text("".join(answer), warnings)})

    for child in element:
        if child.tag in ("h2", "h3", "h4"):
            close()
            current, answer = child.text_content().strip(), []
        else:
            _db_links(child, warnings)
            answer.append(lxml_html.tostring(child, encoding="unicode"))
    close()
    return {"type": "faq", "value": {"items": items}} if items else None


@dataclass
class ArticleBody:
    blocks: list
    intro: str = ""
    warnings: list = field(default_factory=list)


def build_article(text, take_intro=True):
    """StreamField data for ArticlePage.body, the intro and anything that couldn't be carried over.

    H2/H3 become heading blocks (with their anchors), images and embeds on their own line become
    figure/embed blocks, Markdown tables become table blocks, :::faq becomes an FAQ block, and the rest
    becomes rich text. With `take_intro`, a single paragraph before the first heading becomes the intro.
    """
    from lxml import html as lxml_html

    rendered, warnings = render(text, mode="stream")
    if not rendered.strip():
        return ArticleBody([], "", warnings)
    elements = [e for e in lxml_html.fragments_fromstring(rendered) if not isinstance(e, str)]

    intro = ""
    first_heading = next((i for i, e in enumerate(elements) if e.tag in ("h2", "h3")), len(elements))
    if take_intro and first_heading == 1 and elements[0].tag == "p" and elements[0].find(".//img") is None:
        intro = elements.pop(0).text_content().strip()

    blocks, buffer = [], []

    def flush():
        if buffer:
            for element in buffer:
                _db_links(element, warnings)
            value = _rich_text("".join(lxml_html.tostring(e, encoding="unicode") for e in buffer), warnings)
            if value:
                blocks.append({"type": "paragraph", "value": value})
            buffer.clear()

    for element in elements:
        block = None
        if element.tag in ("h2", "h3"):
            block = {
                "type": "heading",
                "value": {
                    "text": element.text_content().strip(),
                    "level": element.tag,
                    "anchor": element.get("id", ""),
                },
            }
        elif element.tag == "table":
            block = {"type": "table", "value": _table(lxml_html.tostring(element, encoding="unicode"))}
        elif element.tag == "figure":
            block = _figure_block(element, warnings)
        elif element.tag == "section" and element.get("data-block") == "faq":
            block = _faq_block(element, warnings)
        else:
            buffer.append(element)
            continue
        flush()
        if block:
            blocks.append(block)
    flush()
    return ArticleBody(blocks, intro, warnings)


def to_stream(text):
    """StreamField data for ArticlePage.body (the whole text, intro included)."""
    return build_article(text, take_intro=False).blocks


def verify_markers(text):
    return len(VERIFY_RE.findall(text or ""))
