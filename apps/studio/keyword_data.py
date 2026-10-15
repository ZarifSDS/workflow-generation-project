"""Keyword metrics and filtration for the Search results step (Settings › Keyword data providers).

Candidates come from the brief (primary and secondary keywords) and the search data (autocomplete, People
also ask, related searches). The first ready keyword source (apps.ai.models.KeywordSource, by order) is
asked for each candidate's monthly volume, difficulty, intent and CPC in the brief's region; then every
candidate is kept or dropped by plain rules (apps.ai.models.KeywordRules), each with its reason, so the
research targets only keywords worth targeting. Without a source the filter still runs on relevance,
near-duplicates and excluded terms, and says the volumes are unknown.

Readers, from each platform's own documentation (checked 2026-10-15):
- Semrush: GET https://api.semrush.com/?type=phrase_these (up to 100 phrases, ";"-separated), CSV with
  ";" separators; columns Ph, Nq (volume), Cp (CPC), Co (competition), Kd (difficulty), In (intent:
  0 commercial, 1 informational, 2 navigational, 3 transactional). 10 API units per line.
- DataForSEO: POST https://api.dataforseo.com/v3/dataforseo_labs/google/keyword_overview/live, HTTP basic
  login:password, [{"keywords", "location_name", "language_name"}] (up to 700); items[i].keyword_info
  (search_volume, cpc, competition), keyword_properties.keyword_difficulty, search_intent_info.main_intent.
- Keywords Everywhere: POST https://api.keywordseverywhere.com/v1/get_keyword_data, Bearer key, form
  dataSource=gkp, country, currency, kw[] (up to 100); data[i]: keyword, vol, cpc.value, competition.
"""

import base64
import csv
import io
import logging
import re
from dataclasses import dataclass, field

import httpx
from django.conf import settings

from apps.ai import secrets
from apps.ai.redact import redact

logger = logging.getLogger(__name__)
TIMEOUT = httpx.Timeout(30, connect=10)

# Brief region → each platform's market: Semrush database, DataForSEO location name, Keywords Everywhere
# country. EU briefs use Ireland, as the search step does (serp.LOCALES).
MARKETS = {
    "US": ("us", "United States", "us"),
    "UK": ("uk", "United Kingdom", "uk"),
    "AU": ("au", "Australia", "au"),
    "CA": ("ca", "Canada", "ca"),
    "NZ": ("nz", "New Zealand", "nz"),
    "EU": ("ie", "Ireland", "ie"),
}
SEMRUSH_INTENT = {"0": "commercial", "1": "informational", "2": "navigational", "3": "transactional"}
STOPWORDS = set(
    "a an and are as at be by can do does for from how i in is it of on or should the to vs what when where "
    "which who why with you your my our".split()
)


class KeywordDataError(Exception):
    """The source couldn't be read; the message says why (credentials never appear in it)."""


@dataclass
class Metric:
    keyword: str
    volume: int | None = None
    difficulty: float | None = None
    intent: str = ""
    cpc: float | None = None
    competition: float | None = None


@dataclass
class Candidate:
    keyword: str
    origin: str  # primary, secondary, question, autocomplete, related
    metric: Metric | None = None
    kept: bool = True
    reason: str = ""


@dataclass
class KeywordData:
    source: str = ""  # label of the source that answered, "" when none
    candidates: list = field(default_factory=list)
    note: str = ""

    @property
    def kept(self):
        return [c for c in self.candidates if c.kept]

    @property
    def dropped(self):
        return [c for c in self.candidates if not c.kept]


def market(region):
    return MARKETS.get(region or "US", MARKETS["US"])


def _number(value):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


# ---- Readers ----


def _semrush(source, keywords, region, client):
    database = market(region)[0]
    metrics = []
    for batch in _batches(keywords, 100):
        response = client.get(
            source.base_url or "https://api.semrush.com/",
            params={
                "type": "phrase_these",
                "key": secrets.decrypt(source.api_key_encrypted),
                "phrase": ";".join(batch),
                "database": database,
                "export_columns": "Ph,Nq,Cp,Co,Kd,In",
            },
        )
        text = response.text.strip()
        if text.startswith("ERROR"):
            if "NOTHING FOUND" in text:
                continue
            raise KeywordDataError(f"Semrush answered {text[:120]}")
        response.raise_for_status()
        rows = list(csv.reader(io.StringIO(text), delimiter=";"))
        for row in rows[1:]:
            if len(row) < 6:
                continue
            intents = [SEMRUSH_INTENT.get(code.strip(), "") for code in row[5].split(",")]
            metrics.append(
                Metric(
                    keyword=row[0].strip().lower(),
                    volume=int(_number(row[1]) or 0),
                    cpc=_number(row[2]),
                    competition=_number(row[3]),
                    difficulty=_number(row[4]),
                    intent=", ".join(i for i in intents if i),
                )
            )
    return metrics


def basic_token_parts(value):
    """(login, password) when `value` is DataForSEO's ready-made base64 "login:password" token (its
    dashboard shows one), else None."""
    import binascii

    value = (value or "").strip().removeprefix("Basic ").strip()
    if not value or "@" in value or ":" in value:
        return None
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    login, sep, password = decoded.partition(":")
    return (login, password) if sep and "@" in login and password else None


def dataforseo_credentials(source):
    """(login, password) from what was stored, accepting the base64 token in either field."""
    login = secrets.decrypt(source.login_encrypted) if source.login_encrypted else ""
    password = secrets.decrypt(source.api_key_encrypted) if source.api_key_encrypted else ""
    for value in (login, password):
        if parts := basic_token_parts(value):
            return parts
    return login, password


def _dataforseo(source, keywords, region, client):
    login, password = dataforseo_credentials(source)
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    url = (source.base_url or "https://api.dataforseo.com").rstrip("/")
    response = client.post(
        f"{url}/v3/dataforseo_labs/google/keyword_overview/live",
        headers={"Authorization": f"Basic {token}"},
        json=[{"keywords": keywords[:700], "location_name": market(region)[1], "language_name": "English"}],
    )
    if response.status_code == 401:
        raise KeywordDataError("DataForSEO refused the login and password")
    response.raise_for_status()
    data = response.json()
    tasks = data.get("tasks") or []
    if not tasks or tasks[0].get("status_code") not in (20000, None):
        message = (tasks[0].get("status_message") if tasks else data.get("status_message")) or "no result"
        raise KeywordDataError(f"DataForSEO answered: {message}")
    items = ((tasks[0].get("result") or [{}])[0] or {}).get("items") or []
    metrics = []
    for item in items:
        info = item.get("keyword_info") or {}
        metrics.append(
            Metric(
                keyword=str(item.get("keyword", "")).lower(),
                volume=info.get("search_volume"),
                cpc=info.get("cpc"),
                competition=info.get("competition"),
                difficulty=(item.get("keyword_properties") or {}).get("keyword_difficulty"),
                intent=str((item.get("search_intent_info") or {}).get("main_intent") or ""),
            )
        )
    return metrics


def _keywords_everywhere(source, keywords, region, client):
    metrics = []
    for batch in _batches(keywords, 100):
        response = client.post(
            (source.base_url or "https://api.keywordseverywhere.com").rstrip("/") + "/v1/get_keyword_data",
            headers={
                "Authorization": f"Bearer {secrets.decrypt(source.api_key_encrypted)}",
                "Accept": "application/json",
            },
            data={"dataSource": "gkp", "country": market(region)[2], "currency": "usd", "kw[]": batch},
        )
        if response.status_code in (401, 403):
            raise KeywordDataError("Keywords Everywhere refused the key")
        response.raise_for_status()
        for item in response.json().get("data") or []:
            cpc = item.get("cpc")
            metrics.append(
                Metric(
                    keyword=str(item.get("keyword", "")).lower(),
                    volume=item.get("vol"),
                    cpc=_number(cpc.get("value")) if isinstance(cpc, dict) else _number(cpc),
                    competition=_number(item.get("competition")),
                )
            )
    return metrics


READERS = {"semrush": _semrush, "dataforseo": _dataforseo, "keywords_everywhere": _keywords_everywhere}


def _batches(items, size):
    return [items[i : i + size] for i in range(0, len(items), size)]


def sources():
    """Keyword sources that can be asked now, in order."""
    from django.db import DatabaseError

    from apps.ai.models import KeywordSource

    try:
        return [s for s in KeywordSource.objects.order_by("order", "label") if s.ready]
    except DatabaseError:
        return []


def measure(keywords, region, client=None):
    """(source label, {keyword: Metric}, problems) from the first ready source that answers."""
    problems = []
    with client or httpx.Client(headers={"User-Agent": settings.AI_USER_AGENT}, timeout=TIMEOUT) as http:
        for source in sources():
            try:
                found = READERS[source.platform](source, keywords, region, http)
            except (httpx.HTTPError, ValueError, KeywordDataError, secrets.SecretsUnavailable) as error:
                problems.append(redact(f"{source.label}: {error}")[:200])
                continue
            return source.label, {m.keyword: m for m in found}, problems
    return "", {}, problems


# ---- Filtration ----


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS}


def _stem(word):
    """Plural to singular, enough to treat "templates" and "template" as the same keyword."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def collect(brief, serp_data=None, suggestions=()):
    """Candidates in a stable order, each once (case and spacing ignored)."""
    from .serp import QUESTION_WORDS

    found, seen = [], set()

    def add(keyword, origin):
        key = " ".join(str(keyword).lower().replace("’", "'").replace("‘", "'").split())
        if key and key not in seen:
            seen.add(key)
            found.append(Candidate(key, origin))

    add(brief.pkeyword or brief.topic, "primary")
    for keyword in brief.skeywords or []:
        add(keyword, "secondary")
    for question in getattr(serp_data, "questions", []) or []:
        add(question, "question")
    for suggestion in suggestions:
        add(suggestion, "question" if suggestion.split()[0].lower() in QUESTION_WORDS else "autocomplete")
    for related in getattr(serp_data, "related", []) or []:
        add(related, "related")
    return found


# Places and regulators that tie a keyword to one market. A keyword naming another market than the brief's
# (and none of its own) is for other readers: "risk assessment template qld" in a UK brief. OTHER lists
# markets the studio never writes for.
MARKET_TERMS = {
    "US": ["usa", "united states", "osha", "american"],
    "UK": [
        "uk",
        "united kingdom",
        "britain",
        "british",
        "england",
        "scotland",
        "wales",
        "hse",
        "coshh",
        "riddor",
    ],
    "AU": [
        "australia",
        "australian",
        "qld",
        "queensland",
        "nsw",
        "new south wales",
        "victoria",
        "tasmania",
        "safe work australia",
        "safework",
        "worksafe",
        "whs",
    ],  # fmt: skip
    "CA": ["canada", "canadian", "ontario", "alberta", "british columbia", "quebec", "whmis", "ccohs"],
    "NZ": ["nz", "new zealand", "worksafe nz", "aotearoa"],
    "EU": ["ireland", "irish", "hsa", "eu", "europe", "european"],
    "OTHER": [
        "singapore",
        "india",
        "malaysia",
        "philippines",
        "south africa",
        "uae",
        "dubai",
        "nigeria",
        "kenya",
        "pakistan",
        "hong kong",
        "saudi",
        "qatar",
    ],  # fmt: skip
}


def _markets_named(keyword):
    found = set()
    for region, terms in MARKET_TERMS.items():
        if any(re.search(rf"\b{re.escape(term)}\b", keyword) for term in terms):
            found.add(region)
    return found


def apply_rules(candidates, metrics, rules, topic="", region="", measured=None):
    """Keep or drop each candidate, with the reason. The brief's own keywords are always kept (the writer
    chose them); a question is kept without a volume (it may still be the FAQ's best question). With a
    region, a keyword naming only other markets is dropped. `measured` (default: any metrics at all) means
    a source answered, so a non-question it has no volume for is dropped: nobody searches for it."""
    measured = bool(metrics) if measured is None else measured
    primary = next((c for c in candidates if c.origin == "primary"), None)
    core = {_stem(w) for w in _words(primary.keyword if primary else "")} | {_stem(w) for w in _words(topic)}
    excluded = rules.excluded()
    kept_shapes = set()
    for candidate in candidates:
        candidate.metric = metrics.get(candidate.keyword)
        m = candidate.metric
        words = {_stem(w) for w in _words(candidate.keyword)}
        shape = frozenset(words)
        if candidate.origin in ("primary", "secondary"):
            candidate.kept, candidate.reason = True, "in the brief"
        elif any(term in candidate.keyword for term in excluded):
            candidate.kept, candidate.reason = False, "contains an excluded term"
        elif core and not words & core:
            candidate.kept, candidate.reason = False, "off topic (shares no word with the primary keyword)"
        elif shape in kept_shapes and candidate.origin != "question":
            # A question that rephrases a kept keyword stays: it's a heading or FAQ candidate.
            candidate.kept, candidate.reason = False, "same words as a kept keyword"
        elif region and (named := _markets_named(candidate.keyword)) and region not in named:
            others = ", ".join(sorted(named - {"OTHER"})) or "another country"
            candidate.kept, candidate.reason = False, f"for another market ({others}), not {region}"
        elif measured and candidate.origin != "question" and (m is None or m.volume is None):
            candidate.kept, candidate.reason = False, "no search volume measured"
        elif m and rules.drop_navigational and m.intent.split(",")[0].strip() == "navigational":
            candidate.kept, candidate.reason = False, "navigational: people looking for one site"
        elif m and m.volume is not None and m.volume < rules.min_volume and candidate.origin != "question":
            candidate.kept, candidate.reason = False, f"under {rules.min_volume} searches a month"
        elif m and m.difficulty is not None and m.difficulty > rules.max_difficulty:
            candidate.kept, candidate.reason = (
                False,
                f"difficulty {m.difficulty:g} over {rules.max_difficulty}",
            )
        else:
            candidate.kept = True
            candidate.reason = "measured" if m else "not measured"
        if candidate.kept and candidate.origin != "question":
            kept_shapes.add(shape)
    # Most-searched first after the brief's own; anything past the cap is dropped with that reason.
    kept = [c for c in candidates if c.kept and c.origin not in ("primary", "secondary")]
    kept.sort(key=lambda c: -((c.metric.volume or 0) if c.metric else -1))
    for candidate in kept[
        max(0, rules.max_keywords - sum(c.origin in ("primary", "secondary") for c in candidates)) :
    ]:
        candidate.kept, candidate.reason = False, f"past the {rules.max_keywords}-keyword limit"
    return candidates


def gather(brief, serp_data=None, suggestions=(), client=None):
    """The whole pass for the Search results step: collect, measure, filter. Never raises."""
    from apps.ai.models import KeywordRules

    data = KeywordData()
    try:
        data.candidates = collect(brief, serp_data, suggestions)
        source, metrics, problems = ("", {}, [])
        if data.candidates:
            source, metrics, problems = measure([c.keyword for c in data.candidates], brief.region, client)
        data.source = source
        apply_rules(
            data.candidates, metrics, KeywordRules.current(), brief.topic, brief.region, measured=bool(source)
        )
        if not source:
            data.note = (
                "No keyword source answered"
                + (
                    f" ({'; '.join(problems)})"
                    if problems
                    else " (none is set up under Settings › Keyword data providers)"
                )
                + ": volumes and difficulty are unknown, so only relevance, duplicates and excluded terms "
                "were checked."
            )
        elif problems:
            data.note = "Skipped: " + "; ".join(problems)
    except Exception as error:  # noqa: BLE001 - keyword data is an extra: never fail the search step
        logger.exception("Keyword data failed")
        data.note = redact(f"Keyword data couldn't be collected: {error!r}")[:300]
    return data


def report(data, region):
    """The "Keyword data" section of the Search results report."""
    if not data.candidates:
        return ""
    lines = ["## Keyword data", ""]
    if data.source:
        lines.append(
            f"*Measured by {data.source} for {market(region)[1]}. Target the kept keywords; the dropped "
            "ones are listed with why, so the research doesn't bring them back.*"
        )
    if data.note:
        lines.append(f"*{data.note}*")
    lines += [
        "",
        "| Keyword | From | Monthly searches | Difficulty | Intent | CPC | Kept |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in data.kept + data.dropped:
        m = c.metric
        cells = [
            c.keyword,
            c.origin,
            f"{m.volume:,}" if m and m.volume is not None else "–",
            f"{m.difficulty:g}" if m and m.difficulty is not None else "–",
            (m.intent if m else "") or "–",
            f"${m.cpc:.2f}" if m and m.cpc is not None else "–",
            "yes" if c.kept else f"no: {c.reason}",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
