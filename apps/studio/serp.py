"""Search results step: what ranks for the brief's keyword in its locale, using free routes only.

1. Results: the first configured provider in settings.STUDIO_SERP_PROVIDERS. Serper (Google results,
   free starting credits), Brave Search (free monthly tier) and Google Programmable Search (100 free
   queries a day) take a country and language; Ollama web search reuses the Ollama Cloud key but can't be
   told a locale, so the locale is added to the query instead.
2. Related searches: Google's autocomplete, keyless, for the keyword and question forms of it.
3. Structure of the ranking pages: each top result is read politely (robots.txt, pacing, as the site
   crawl does) and measured: H1/H2/H3 outline, words, reading grade, tables, lists, images, FAQ.

The report is Markdown for the editor and for the research, outline and draft prompts; the numbers are
kept in the version's metrics. Keys are stored under Settings › AI providers like the model keys.
"""

import json
import re
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from django.conf import settings

from apps.ai.providers import get_providers
from apps.ai.types import ProviderError

from . import webfetch

# Brief region → (country, language) for Google-style parameters. The EU brief writes in English for
# EU readers; Ireland is the closest English-language Google market.
LOCALES = {
    "US": ("us", "en"),
    "UK": ("gb", "en"),
    "AU": ("au", "en"),
    "CA": ("ca", "en"),
    "NZ": ("nz", "en"),
    "EU": ("ie", "en"),
}
COUNTRY_NAMES = {
    "us": "United States",
    "gb": "UK",
    "au": "Australia",
    "ca": "Canada",
    "nz": "New Zealand",
    "ie": "EU",
}
QUESTION_WORDS = ["what", "how", "why", "when", "is", "does", "vs"]
STOPWORDS = set(
    "a an and are as at be by can do does for from how i in is it of on or should the to vs what when "
    "where which who why with you your".split()
)


class SerpError(Exception):
    """No search provider is configured, or every configured one failed."""


@dataclass
class Result:
    position: int
    title: str
    url: str
    snippet: str = ""


@dataclass
class SerpData:
    provider: str
    query: str
    country: str
    language: str
    results: list = field(default_factory=list)
    questions: list = field(default_factory=list)  # "People also ask"
    related: list = field(default_factory=list)  # related searches


def locale_for(region):
    return LOCALES.get(region or "US", ("us", "en"))


# ---- Providers ----


def _client():
    return httpx.Client(headers={"User-Agent": settings.AI_USER_AGENT}, timeout=20, follow_redirects=True)


def _serper(spec, query, country, language, num, client):
    response = client.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": spec.api_key, "Content-Type": "application/json"},
        content=json.dumps({"q": query, "gl": country, "hl": language, "num": num}),
    )
    response.raise_for_status()
    data = response.json()
    serp = SerpData("serper", query, country, language)
    serp.results = [
        Result(
            item.get("position") or i + 1,
            item.get("title", ""),
            item.get("link", ""),
            item.get("snippet", ""),
        )
        for i, item in enumerate(data.get("organic") or [])
    ]
    serp.questions = [q.get("question", "") for q in data.get("peopleAlsoAsk") or [] if q.get("question")]
    serp.related = [r.get("query", "") for r in data.get("relatedSearches") or [] if r.get("query")]
    return serp


def _brave(spec, query, country, language, num, client):
    response = client.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "country": country, "search_lang": language, "count": min(num, 20)},
        headers={"X-Subscription-Token": spec.api_key, "Accept": "application/json"},
    )
    response.raise_for_status()
    data = response.json()
    serp = SerpData("brave_search", query, country, language)
    serp.results = [
        Result(
            i + 1,
            item.get("title", ""),
            item.get("url", ""),
            re.sub(r"<[^>]+>", "", item.get("description", "")),
        )
        for i, item in enumerate((data.get("web") or {}).get("results") or [])
    ]
    serp.questions = [
        q.get("question", "") for q in (data.get("faq") or {}).get("results") or [] if q.get("question")
    ]
    return serp


def _google_cse(spec, query, country, language, num, client):
    response = client.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": spec.api_key,
            "cx": spec.account_id,
            "q": query,
            "gl": country,
            "hl": language,
            "num": min(num, 10),
        },
    )
    response.raise_for_status()
    serp = SerpData("google_cse", query, country, language)
    serp.results = [
        Result(i + 1, item.get("title", ""), item.get("link", ""), item.get("snippet", ""))
        for i, item in enumerate(response.json().get("items") or [])
    ]
    return serp


def _ollama_web(spec, query, country, language, num, client):
    # No locale parameter: name the market in the query so results lean towards it.
    located = f"{query} {COUNTRY_NAMES.get(country, '')}".strip() if country != "us" else query
    response = client.post(
        "https://ollama.com/api/web_search",
        headers={"Authorization": f"Bearer {spec.api_key}"},
        json={"query": located, "max_results": min(num, 10)},
    )
    response.raise_for_status()
    serp = SerpData("ollama_web", located, country, language)
    serp.results = [
        Result(i + 1, item.get("title", ""), item.get("url", ""), (item.get("content") or "")[:300])
        for i, item in enumerate(response.json().get("results") or [])
    ]
    return serp


DDG_REGIONS = {"us": "us-en", "gb": "uk-en", "au": "au-en", "ca": "ca-en", "nz": "nz-en", "ie": "ie-en"}
DDG_RESULT = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
DDG_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)


def _duckduckgo(spec, query, country, language, num, client):
    """Keyless default: DuckDuckGo's HTML results with its region setting. Best effort: when DuckDuckGo
    answers with a challenge instead of results, this returns nothing and the step says so."""
    from html import unescape
    from urllib.parse import parse_qs, unquote
    from urllib.parse import urlparse as parse

    response = client.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query, "kl": DDG_REGIONS.get(country, "wt-wt")},
        headers={"Accept": "text/html"},
    )
    response.raise_for_status()
    serp = SerpData("duckduckgo", query, country, language)
    snippets = DDG_SNIPPET.findall(response.text)
    for index, (href, title) in enumerate(DDG_RESULT.findall(response.text)):
        if "duckduckgo.com/y.js" in href:  # ads
            continue
        url = href
        if "uddg=" in href:
            url = unquote(
                parse_qs(parse(href if href.startswith("http") else "https:" + href).query)["uddg"][0]
            )
        clean = lambda value: unescape(re.sub(r"<[^>]+>", "", value)).strip()  # noqa: E731
        serp.results.append(
            Result(
                len(serp.results) + 1,
                clean(title),
                url,
                clean(snippets[index]) if index < len(snippets) else "",
            )
        )
        if len(serp.results) >= num:
            break
    return serp


# provider name in settings.AI_PROVIDERS → (search function, provider whose key it uses; None = keyless)
PROVIDERS = {
    "serper": (_serper, "serper"),
    "brave_search": (_brave, "brave_search"),
    "google_cse": (_google_cse, "google_cse"),
    "ollama_web": (_ollama_web, "ollama_cloud"),
    "duckduckgo": (_duckduckgo, None),
}


def configured_providers():
    specs = get_providers()
    names = []
    for name in settings.STUDIO_SERP_PROVIDERS:
        if name not in PROVIDERS:
            continue
        key_owner = PROVIDERS[name][1]
        if key_owner is None:
            names.append(name)
            continue
        spec = specs.get(key_owner)
        if spec is not None and spec.is_configured:
            names.append(name)
    return names


def search(query, region, num=10, client=None):
    """Top results from the first configured provider that answers. Raises SerpError otherwise."""
    country, language = locale_for(region)
    names = configured_providers()
    if not names:
        raise SerpError(
            "No search provider is set up. Add a free Serper or Brave Search key (or a Google Programmable "
            "Search key and engine ID) under Settings › Search data providers; an Ollama Cloud key "
            "also works."
        )
    specs, problems = get_providers(), []
    with client or _client() as http:
        for name in names:
            function, key_owner = PROVIDERS[name]
            try:
                serp = function(specs.get(key_owner), query, country, language, num, http)
            except (httpx.HTTPError, ValueError, ProviderError) as error:
                problems.append(f"{name}: {type(error).__name__} {str(error)[:120]}")
                continue
            if serp.results:
                return serp
            problems.append(f"{name}: no results")
    raise SerpError("Every search provider failed: " + "; ".join(problems))


def autocomplete(query, region, client=None, pace=0.3, sleep=time.sleep):
    """Google autocomplete suggestions for the keyword and its question forms (keyless, best effort)."""
    country, language = locale_for(region)
    seen, suggestions = {query.lower()}, []
    with client or _client() as http:
        for prefix in ["", *QUESTION_WORDS]:
            text = f"{prefix} {query}".strip() if prefix != "vs" else f"{query} vs"
            try:
                response = http.get(
                    "https://suggestqueries.google.com/complete/search",
                    params={"client": "firefox", "q": text, "hl": language, "gl": country},
                )
                items = response.json()[1] if response.status_code == 200 else []
            except (httpx.HTTPError, ValueError, IndexError):
                items = []
            for item in items:
                if isinstance(item, str) and item.lower() not in seen:
                    seen.add(item.lower())
                    suggestions.append(item)
            if prefix != QUESTION_WORDS[-1]:
                sleep(pace)
    return suggestions


# ---- Structure of ranking pages ----


class _StructureParser(HTMLParser):
    """Outline (H1–H3), title tag, date, counts of tables, lists, images, videos and forms, FAQ markup,
    and the main text."""

    SKIP = {"script", "style", "noscript", "nav", "footer", "form", "svg"}

    def __init__(self):
        super().__init__()
        self.outline, self.parts = [], []
        self.tables = self.lists = self.images = self.videos = self.forms = 0
        self.faq_schema = False
        self.title_tag, self.date, self._in_title = "", "", False
        self._skip, self._heading, self._level, self._ld = 0, None, 0, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and "ld+json" in (attrs.get("type") or ""):
            self._ld = []
        if tag == "title":
            self._in_title = True
        if tag == "meta" and (attrs.get("property") or attrs.get("name") or "") in (
            "article:modified_time",
            "article:published_time",
            "date",
        ):
            self.date = self.date or (attrs.get("content") or "")[:10]
        if tag == "time" and attrs.get("datetime") and not self.date:
            self.date = attrs["datetime"][:10]
        if tag == "form" and not self._skip:
            self.forms += 1
        if tag == "video" or (tag == "iframe" and re.search(r"youtube|vimeo|wistia", attrs.get("src") or "")):
            self.videos += 1
        if tag in self.SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in ("h1", "h2", "h3"):
            self._heading, self._level = [], int(tag[1])
        elif tag == "table":
            self.tables += 1
        elif tag in ("ul", "ol"):
            self.lists += 1
        elif tag == "img":
            self.images += 1
        if tag in ("p", "li", "h1", "h2", "h3", "h4", "br", "div", "td"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._ld is not None:
            if "FAQPage" in "".join(self._ld):
                self.faq_schema = True
            self._ld = None
        if tag in self.SKIP and self._skip:
            self._skip -= 1
            return
        if tag in ("h1", "h2", "h3") and self._heading is not None:
            text = " ".join("".join(self._heading).split())
            if text:
                self.outline.append((self._level, text[:160]))
            self._heading = None

    def handle_data(self, data):
        if self._in_title:
            self.title_tag += data
        if self._ld is not None:
            self._ld.append(data)
        if self._skip:
            return
        self.parts.append(data)
        if self._heading is not None:
            self._heading.append(data)

    @property
    def text(self):
        return re.sub(r"\n\s*\n+", "\n\n", "".join(self.parts)).strip()


@dataclass
class PageStructure:
    position: int
    url: str
    title: str
    status: str = "read"  # "read" | "skipped"
    reason: str = ""
    outline: list = field(default_factory=list)  # [(level, text)]
    words: int = 0
    grade: float | None = None
    tables: int = 0
    lists: int = 0
    images: int = 0
    videos: int = 0
    forms: int = 0
    faq: bool = False
    title_tag: str = ""
    date: str = ""

    @property
    def h2(self):
        return [text for level, text in self.outline if level == 2]

    @property
    def h3_count(self):
        return sum(1 for level, _ in self.outline if level == 3)

    @property
    def question_h2(self):
        return sum(1 for text in self.h2 if text.rstrip().endswith("?"))


def parse_structure(html):
    parser = _StructureParser()
    parser.feed(html)
    return parser


def read_page(result, client, grade=None):
    """Fetch one ranking page and measure its structure. Never raises."""
    page = PageStructure(result.position, result.url, result.title)
    robots = webfetch.robots_for(f"{urlparse(result.url).scheme}://{urlparse(result.url).netloc}", client)
    if not robots.can_fetch(settings.AI_USER_AGENT, result.url):
        page.status, page.reason = "skipped", "Disallowed by robots.txt"
        return page
    try:
        response = client.get(result.url, headers={"Accept": "text/html"})
    except httpx.HTTPError as error:
        page.status, page.reason = "skipped", f"Could not be fetched ({type(error).__name__})"
        return page
    if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
        page.status, page.reason = "skipped", f"HTTP {response.status_code}"
        return page
    parsed = parse_structure(response.text)
    page.outline = parsed.outline
    page.words = len(parsed.text.split())
    page.tables, page.lists, page.images = parsed.tables, parsed.lists, parsed.images
    page.videos, page.forms, page.date = parsed.videos, parsed.forms, parsed.date
    page.title_tag = " ".join(parsed.title_tag.split())[:160]
    headings = " ".join(text.lower() for _, text in parsed.outline)
    page.faq = parsed.faq_schema or "faq" in headings or "frequently asked" in headings
    if page.words < 200:
        page.status, page.reason = "skipped", "Too little text (JavaScript-only or blocked)"
        return page
    page.grade = grade(parsed.text) if grade else None
    return page


def read_pages(results, limit, client=None, pace=2.0, sleep=time.sleep, grade=None):
    pages = []
    with client or _client() as http:
        for index, result in enumerate(results[:limit]):
            if index:
                sleep(pace)
            pages.append(read_page(result, http, grade=grade))
    return pages


def _terms(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 2}


def analyse(pages, keyword):
    """What the ranking pages have in common: length, depth, formats and recurring H2 themes."""
    read = [p for p in pages if p.status == "read"]
    if not read:
        return {"pages_read": 0}
    keyword_terms = _terms(keyword)
    theme_pages = Counter()
    examples = {}
    for page in read:
        seen = set()
        for heading in page.h2:
            for term in _terms(heading) - keyword_terms:
                if term not in seen:
                    seen.add(term)
                    theme_pages[term] += 1
                    examples.setdefault(term, heading)
    common = [
        {"term": term, "pages": count, "example": examples[term]}
        for term, count in theme_pages.most_common(15)
        if count >= max(2, round(len(read) * 0.3))
    ]
    grades = [p.grade for p in read if p.grade is not None]
    return {
        "pages_read": len(read),
        "median_words": round(statistics.median(p.words for p in read)),
        "word_range": [min(p.words for p in read), max(p.words for p in read)],
        "median_h2": round(statistics.median(len(p.h2) for p in read)),
        "median_h3": round(statistics.median(p.h3_count for p in read)),
        "median_grade": round(statistics.median(grades), 1) if grades else None,
        "with_faq": sum(p.faq for p in read),
        "with_tables": sum(1 for p in read if p.tables),
        "with_video": sum(1 for p in read if p.videos),
        "with_forms": sum(1 for p in read if p.forms),
        "question_h2_share": round(
            sum(p.question_h2 for p in read) / max(1, sum(len(p.h2) for p in read)) * 100
        ),
        "themes": common,
    }


# ---- Report ----


def report(serp, suggestions, pages, summary, keyword, region, own_domain=""):
    country, language = locale_for(region)
    lines = [f"# Search results: {keyword}", ""]
    if serp:
        lines.append(
            f"Top results from **{serp.provider}** for “{serp.query}” "
            f"(country {country}, language {language})."
        )
    else:
        lines.append(f"No search results (see the note). Locale: country {country}, language {language}.")
    lines.append("")

    if summary.get("pages_read"):
        lines += [
            "## What the ranking pages have in common",
            "",
            f"- **Length:** median {summary['median_words']} words "
            f"(range {summary['word_range'][0]}–{summary['word_range'][1]}), "
            f"from {summary['pages_read']} pages read.",
            f"- **Depth:** median {summary['median_h2']} H2 sections "
            f"and {summary['median_h3']} H3 subsections.",
            f"- **Reading grade:** median FKGL {summary['median_grade']}."
            if summary.get("median_grade")
            else "- **Reading grade:** not measured.",
            f"- **Formats:** {summary['with_faq']} of {summary['pages_read']} have an FAQ; "
            f"{summary['with_tables']} use tables, {summary.get('with_video', 0)} embed video, "
            f"{summary.get('with_forms', 0)} have a form or calculator; "
            f"{summary.get('question_h2_share', 0)}% of their H2s are questions.",
        ]
        if summary["themes"]:
            lines += [
                "",
                "### Recurring H2 themes",
                "",
                "| Theme | Pages | Example heading |",
                "|---|---|---|",
            ]
            lines += [f"| {t['term']} | {t['pages']} | {t['example']} |" for t in summary["themes"]]
        lines.append("")

    if serp and serp.results:
        lines += [
            "## Top results",
            "",
            "| # | Page | Words | H2/H3 | Grade | FAQ | Tables |",
            "|---|---|---|---|---|---|---|",
        ]
        by_url = {p.url: p for p in pages}
        for result in serp.results:
            page = by_url.get(result.url)
            mine = " (yours)" if own_domain and own_domain in urlparse(result.url).netloc else ""
            if page and page.status == "read":
                faq, grade = ("yes" if page.faq else "no"), page.grade or "–"
                cells = f"{page.words} | {len(page.h2)}/{page.h3_count} | {grade} | {faq} | {page.tables}"
            elif page:
                cells = f"– | – | – | – | – ({page.reason})"
            else:
                cells = "not read | – | – | – | –"
            lines.append(
                f"| {result.position} | [{result.title or result.url}]({result.url}){mine} | {cells} |"
            )
        lines.append("")

    read = [p for p in pages if p.status == "read"]
    if read:
        lines += ["## Outlines of the top pages", ""]
        for page in read:
            lines.append(f"### {page.position}. {page.title or page.url}")
            lines.append("")
            facts = [
                f"Title tag: “{page.title_tag}”" if page.title_tag else "",
                f"dated {page.date}" if page.date else "",
            ]
            if any(facts):
                lines += [" · ".join(f for f in facts if f), ""]
            lines += [f"{'  ' * (level - 1)}- H{level}: {text}" for level, text in page.outline[:40]] or [
                "- (no headings)"
            ]
            lines.append("")

    questions = list(
        dict.fromkeys(
            (serp.questions if serp else [])
            + [s for s in suggestions if s.split()[0].lower() in QUESTION_WORDS]
        )
    )
    paa_note = _source_note(serp, country, "questions")
    if questions or paa_note:
        lines += ["## Questions searchers ask", ""]
        lines += [paa_note, ""] if paa_note else []
        lines += [f"- {q}" for q in questions[:20]] + [""] if questions else ["- None found.", ""]
    related = list(
        dict.fromkeys((serp.related if serp else []) + [s for s in suggestions if s not in questions])
    )
    related_note = _source_note(serp, country, "related")
    if related or related_note:
        lines += ["## Related searches", ""]
        lines += [related_note, ""] if related_note else []
        lines += [f"- {r}" for r in related[:25]] + [""] if related else ["- None found.", ""]
    return "\n".join(lines).strip() + "\n"


PROVIDER_NAMES = {
    "serper": "Serper",
    "brave_search": "Brave Search",
    "google_cse": "Google Programmable Search",
    "duckduckgo": "DuckDuckGo",
    "ollama_web": "Ollama web search",
}


def _source_note(serp, country, kind):
    """Where the questions (Google's "People also ask") or related searches came from, said plainly when
    the search provider sent none, so the research knows they are only autocomplete suggestions: what
    people type, not the questions Google answers on the results page. Serper sends both for US searches
    and usually neither elsewhere (checked live 2026-10-15)."""
    if not serp:
        return ""
    sent = serp.questions if kind == "questions" else serp.related
    what = '"People also ask" questions' if kind == "questions" else "related searches"
    name = PROVIDER_NAMES.get(serp.provider, serp.provider)
    market = COUNTRY_NAMES.get(country, country)
    if sent:
        return f"*Source: {what} from {name} for {market}, plus Google autocomplete for {market}.*"
    usually = (
        " (outside the US it usually sends none)" if serp.provider == "serper" and country != "us" else ""
    )
    meaning = (
        "what people type, not the questions Google answers on the results page"
        if kind == "questions"
        else "what people type after the keyword, not Google's own related searches"
    )
    return (
        f"*Source: Google autocomplete for {market} only. {name} sent no {what} for this search{usually}, "
        f"so these are {meaning}.*"
    )
