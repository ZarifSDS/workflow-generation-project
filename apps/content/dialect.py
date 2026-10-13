"""The studio's Markdown dialect (ADR 0007): CommonMark + GFM tables, plus a few extensions shared by
the editor, the prompts and every server-side renderer.

| Construct        | Syntax                                                                 |
|------------------|------------------------------------------------------------------------|
| Heading anchor   | `## Safety data sheets {#sds}`; without `{#…}` the id comes from slugify() |
| Underline/strike | `++text++` / `~~text~~`                                                |
| Internal links   | `[text](wagtail://page?id=12)`, `[text](wagtail://document?id=7)`      |
| Image            | `![Alt](wagtail://image?id=42 "Caption")`; `&decorative=1` for decorative |
| Embed            | `![Title](wagtail://media?url=https%3A%2F%2Fyoutu.be%2Fx)` on its own   |
| FAQ              | `:::faq`, then `### Question?` + answer paragraphs per item, then `:::` |

The `wagtail://` references are the format Wagtail 8 uses for rich text in Markdown
(wagtail.admin.rich_text.converters.markdown_db), so they stay compatible with Wagtail's tooling.

Rendering modes:
- "html": references are resolved through a resolver (image renditions, page and document URLs).
  Unresolvable references degrade to plain text and are reported in `warnings`.
- "stream": references are kept as `wagtail://` URLs for apps.content.markup.to_stream.
"""

import html
import re
import unicodedata
import xml.etree.ElementTree as etree
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from markdown import util
from markdown.blockprocessors import BlockProcessor
from markdown.extensions import Extension
from markdown.inlinepatterns import SimpleTagInlineProcessor
from markdown.treeprocessors import Treeprocessor

REFERENCE_SCHEME = "wagtail"
ANCHOR_RE = re.compile(r"\s*\{#([A-Za-z0-9][A-Za-z0-9_-]*)\}\s*$")
FAQ_OPEN, FAQ_CLOSE = ":::faq", ":::"
TITLE_ESCAPE_RE = re.compile(r"\\([\\\"'])")


def slugify(text):
    """Heading id rule shared with the editor (frontend/src/slug.js): ASCII, lowercase, hyphens."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "section"


def parse_ref(url):
    """("page", {"id": "12"}) for a wagtail:// URL, else None."""
    if not url or not url.startswith(f"{REFERENCE_SCHEME}://"):
        return None
    parts = urlsplit(url)
    params = {key: values[0] for key, values in parse_qs(parts.query).items()}
    return parts.netloc, params


@dataclass
class ResolvedImage:
    url: str
    width: int | None = None
    height: int | None = None


@dataclass
class Resolver:
    """Looks up referenced objects in batches. Subclass for real data (see markup.WagtailResolver)."""

    def images(self, ids):
        return {}

    def pages(self, ids):
        return {}

    def documents(self, ids):
        return {}


@dataclass
class RenderState:
    mode: str = "html"
    resolver: Resolver | None = None
    warnings: list = field(default_factory=list)


# ---- Block: :::faq ... ::: ----


class FAQBlockProcessor(BlockProcessor):
    def __init__(self, parser, state):
        super().__init__(parser)
        self.state = state

    def test(self, parent, block):
        return block.strip().split("\n", 1)[0].strip() == FAQ_OPEN

    def run(self, parent, blocks):
        first = blocks.pop(0)
        inner = first.strip().split("\n", 1)[1:]  # text after ":::faq" in the same block
        collected = list(inner)
        closed = False
        while blocks:
            block = blocks.pop(0)
            lines = block.rstrip().split("\n")
            if lines[-1].strip() == FAQ_CLOSE:
                if len(lines) > 1:
                    collected.append("\n".join(lines[:-1]))
                closed = True
                break
            collected.append(block)
        section = etree.SubElement(parent, "section")
        section.set("data-block", "faq")
        self.parser.parseBlocks(section, [chunk for chunk in collected if chunk.strip()])
        if not closed:
            self.state.warnings.append("An FAQ block (:::faq) has no closing ::: line.")
        return True


# ---- Tree: heading ids, references ----


class HeadingIdProcessor(Treeprocessor):
    def run(self, root):
        used = set()
        for heading in root.iter():
            if heading.tag not in ("h2", "h3", "h4"):
                continue
            explicit = self._take_anchor(heading)
            base = explicit or slugify(self._plain_text(heading))
            anchor, number = base, 2
            while anchor in used:
                anchor, number = f"{base}-{number}", number + 1
            used.add(anchor)
            heading.set("id", anchor)

    def _plain_text(self, heading):
        """The heading's text as a reader sees it. Entities such as &amp; are stashed by Python-Markdown
        and show up as placeholders here; put them back and decode them, as the editor's slug does."""
        blocks = self.md.htmlStash.rawHtmlBlocks

        def stashed(match):
            index = int(match.group(1))
            return str(blocks[index]) if index < len(blocks) else ""

        text = util.HTML_PLACEHOLDER_RE.sub(stashed, "".join(heading.itertext()))
        return html.unescape(re.sub(r"<[^>]*>", "", text.replace(util.AMP_SUBSTITUTE, "&")))

    @staticmethod
    def _take_anchor(heading):
        """Strip a trailing {#id} from the heading's last text and return the id."""
        children = list(heading)
        holder, attr = (children[-1], "tail") if children and children[-1].tail else (heading, "text")
        text = getattr(holder, attr) or ""
        match = ANCHOR_RE.search(text)
        if not match:
            return None
        setattr(holder, attr, text[: match.start()])
        return match.group(1)


class ReferenceProcessor(Treeprocessor):
    def __init__(self, md, state):
        super().__init__(md)
        self.state = state

    def run(self, root):
        parents = {child: parent for parent in root.iter() for child in parent}
        images, links = [], []
        for element in root.iter():
            if element.tag == "img" and parse_ref(element.get("src")):
                images.append(element)
            elif element.tag == "a" and parse_ref(element.get("href")):
                links.append(element)
        for img in images:
            self._figure(img, parents)
        if self.state.mode == "html":
            self._resolve(root, parents)

    def _figure(self, img, parents):
        """An image or embed alone in its paragraph becomes a <figure> (with a caption from the title)."""
        kind, params = parse_ref(img.get("src"))
        paragraph = parents.get(img)
        alone = (
            paragraph is not None
            and paragraph.tag == "p"
            and len(paragraph) == 1
            and not (paragraph.text or "").strip()
            and not (img.tail or "").strip()
        )
        if not alone:
            return
        paragraph.tag = "figure"
        paragraph.text = None
        img.tail = None
        if kind == "media":
            paragraph.set("data-embed", params.get("url", ""))
        # Python-Markdown leaves backslash escapes in titles; CommonMark (and the editor) removes them.
        caption = TITLE_ESCAPE_RE.sub(r"\1", img.attrib.pop("title", ""))
        if caption and kind == "image":
            figcaption = etree.SubElement(paragraph, "figcaption")
            figcaption.text = caption
        if kind == "image" and params.get("decorative") == "1":
            img.set("alt", "")
            paragraph.set("data-decorative", "1")
        elif kind == "image" and not img.get("alt", "").strip():
            self.state.warnings.append(f"Image {params.get('id', '?')} has no alt text.")

    def _resolve(self, root, parents):
        resolver = self.state.resolver or Resolver()
        refs = {"image": set(), "page": set(), "document": set()}
        for element in root.iter():
            ref = parse_ref(element.get("src") or element.get("href"))
            if ref and ref[0] in refs and ref[1].get("id", "").isdigit():
                refs[ref[0]].add(int(ref[1]["id"]))
        found = {
            "image": resolver.images(refs["image"]) if refs["image"] else {},
            "page": resolver.pages(refs["page"]) if refs["page"] else {},
            "document": resolver.documents(refs["document"]) if refs["document"] else {},
        }
        for element in list(root.iter()):
            if element.tag == "img":
                self._resolve_img(element, parents, found["image"])
            elif element.tag == "a":
                self._resolve_link(element, parents, found)

    def _resolve_img(self, img, parents, images):
        ref = parse_ref(img.get("src"))
        if not ref:
            return
        kind, params = ref
        if kind == "media":
            url = params.get("url", "")
            link = etree.Element("a", {"href": url})
            link.text = img.get("alt") or url
            self._replace(img, link, parents)
            return
        image = images.get(int(params["id"])) if params.get("id", "").isdigit() else None
        if image is None:
            self.state.warnings.append(f"Image {params.get('id', '?')} no longer exists; it was left out.")
            parent = parents.get(img)
            if parent is not None and parent.tag == "figure":
                self._replace(parent, None, parents)  # drop the whole figure, caption included
            else:
                self._replace(img, None, parents)
            return
        img.set("src", image.url)
        img.set("loading", "lazy")
        for name in ("width", "height"):
            value = getattr(image, name)
            if value:
                img.set(name, str(value))

    def _resolve_link(self, link, parents, found):
        ref = parse_ref(link.get("href"))
        if not ref:
            return  # an ordinary link
        kind, params = ref
        target = found.get(kind, {}).get(int(params["id"])) if params.get("id", "").isdigit() else None
        if target:
            link.set("href", target)
            return
        self.state.warnings.append(f"A link to {kind} {params.get('id', '?')} no longer resolves.")
        self._unwrap(link, parents)

    @staticmethod
    def _replace(old, new, parents):
        parent = parents.get(old)
        if parent is None:
            return
        index = list(parent).index(old)
        parent.remove(old)
        if new is not None:
            new.tail = old.tail
            parent.insert(index, new)
            parents[new] = parent
        elif old.tail:
            ReferenceProcessor._append_text(parent, index, old.tail)

    @staticmethod
    def _unwrap(link, parents):
        parent = parents.get(link)
        if parent is None:
            return
        index = list(parent).index(link)
        text = "".join(link.itertext()) + (link.tail or "")
        parent.remove(link)
        ReferenceProcessor._append_text(parent, index, text)

    @staticmethod
    def _append_text(parent, index, text):
        if index == 0:
            parent.text = (parent.text or "") + text
        else:
            previous = list(parent)[index - 1]
            previous.tail = (previous.tail or "") + text


class DialectExtension(Extension):
    def __init__(self, state, **kwargs):
        self.state = state
        super().__init__(**kwargs)

    def extendMarkdown(self, md):  # noqa: N802 - Python-Markdown API name
        # \~ and \+ escape the dialect's own markers (the visual editor writes \~ for a literal tilde).
        md.ESCAPED_CHARS.extend(char for char in "~+" if char not in md.ESCAPED_CHARS)
        md.inlinePatterns.register(SimpleTagInlineProcessor(r"(\+\+)(.+?)\+\+", "u"), "underline", 65)
        md.inlinePatterns.register(SimpleTagInlineProcessor(r"(~~)(.+?)~~", "s"), "strike", 64)
        md.parser.blockprocessors.register(FAQBlockProcessor(md.parser, self.state), "faq", 105)
        md.treeprocessors.register(HeadingIdProcessor(md), "heading_ids", 5)
        md.treeprocessors.register(ReferenceProcessor(md, self.state), "references", 4)
