"""Polite reading of public web pages for the site crawl step (docs/workflow.md).

Rules: public pages only, robots.txt respected, an honest User-Agent, one page every few seconds,
a hard page cap. Each page is fetched directly first; if that's blocked or returns an empty shell,
a reader service is tried. A page that still fails is skipped and reported, never forced.
"""

import re
import time
import urllib.robotparser
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from django.conf import settings

READER_URL = "https://r.jina.ai/"
ARTICLE_HINTS = ("blog", "news", "article", "insight", "guide", "resource", "post", "learn")
SKIP_HINTS = (
    "login",
    "signin",
    "sign-in",
    "account",
    "cart",
    "checkout",
    "members",
    "wp-admin",
    "tag/",
    "category/",
    "author/",
    "privacy",
    "terms",
    "cookie",
    "contact",
)


@dataclass
class FetchedPage:
    url: str
    method: str  # "direct" | "reader" | "skipped"
    text: str = ""
    headings: list = field(default_factory=list)
    reason: str = ""


class _TextExtractor(HTMLParser):
    """Visible text and H2/H3 headings, ignoring scripts, styles, navigation and footers."""

    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"}

    def __init__(self):
        super().__init__()
        self.parts, self.headings, self.links = [], [], []
        self._skip_depth, self._heading = 0, None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag in ("h2", "h3") and not self._skip_depth:
            self._heading = []
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in ("p", "li", "h1", "h2", "h3", "h4", "br", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag in ("h2", "h3") and self._heading is not None:
            text = " ".join("".join(self._heading).split())
            if text:
                self.headings.append(text)
            self._heading = None

    def handle_data(self, data):
        if self._skip_depth:
            return
        self.parts.append(data)
        if self._heading is not None:
            self._heading.append(data)

    @property
    def text(self):
        return re.sub(r"\n\s*\n+", "\n\n", "".join(self.parts)).strip()


def _client():
    return httpx.Client(
        headers={"User-Agent": settings.AI_USER_AGENT, "Accept": "text/html"},
        timeout=20,
        follow_redirects=True,
    )


def robots_for(base_url, client):
    parser = urllib.robotparser.RobotFileParser()
    try:
        response = client.get(urljoin(base_url, "/robots.txt"))
        parser.parse(response.text.splitlines() if response.status_code == 200 else [])
    except httpx.HTTPError:
        parser.parse([])
    return parser


def _skip_url(url):
    return any(hint in url.lower() for hint in SKIP_HINTS)


def fetch_page(url, client, robots):
    if _skip_url(url):
        return FetchedPage(url, "skipped", reason="Looks like a login, account or listing page")
    if not robots.can_fetch(settings.AI_USER_AGENT, url):
        return FetchedPage(url, "skipped", reason="Disallowed by robots.txt")
    try:
        response = client.get(url)
        if response.status_code in (401, 403) and "login" in response.url.path.lower():
            return FetchedPage(url, "skipped", reason="Requires login")
        if response.status_code == 200 and "html" in response.headers.get("content-type", ""):
            extractor = _TextExtractor()
            extractor.feed(response.text)
            if len(extractor.text.split()) >= 250:
                page = FetchedPage(url, "direct", extractor.text, extractor.headings)
                page.links = extractor.links
                return page
    except httpx.HTTPError:
        pass
    try:  # reader service fallback for blocked or JavaScript-only pages
        reader = client.get(READER_URL + url, headers={"Accept": "text/plain"})
        if reader.status_code == 200 and len(reader.text.split()) >= 250:
            headings = re.findall(r"^#{2,3}\s+(.+)$", reader.text, re.M)
            return FetchedPage(url, "reader", reader.text, headings)
    except httpx.HTTPError:
        pass
    return FetchedPage(url, "skipped", reason="Could not be read (blocked or empty)")


def discover_articles(home_url, links, limit):
    host = urlparse(home_url).netloc
    seen, found = set(), []
    for href in links:
        url = urljoin(home_url, href).split("#")[0].rstrip("/")
        parsed = urlparse(url)
        if parsed.netloc != host or url in seen or _skip_url(url):
            continue
        seen.add(url)
        path = parsed.path.lower()
        if path.count("/") >= 2 and any(hint in path for hint in ARTICLE_HINTS):
            found.append(url)
    return found[:limit]


def crawl_site(home_url, extra_urls=(), max_pages=8, pace_seconds=5.0, sleep=time.sleep):
    """Read the home page plus up to max_pages-1 article pages. Returns [FetchedPage]."""
    pages = []
    with _client() as client:
        robots = robots_for(home_url, client)
        home = fetch_page(home_url, client, robots)
        pages.append(home)
        candidates = list(extra_urls) + discover_articles(home_url, getattr(home, "links", []), max_pages)
        for url in candidates:
            if len(pages) >= max_pages:
                break
            if any(p.url == url for p in pages):
                continue
            sleep(pace_seconds)
            pages.append(fetch_page(url, client, robots))
    return pages
