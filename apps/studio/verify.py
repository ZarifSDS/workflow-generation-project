"""Resolve every marker in an edited article: no marker and no References section survives review.

The draft marks claims it couldn't confirm ([VERIFY…]), the sources it used ([SRC: url]) and image ideas
([VISUAL: …]), and ends with a References section. Those are notes on where the facts came from, never
part of the publication (owner's rule, 2026-10-15). After the review-and-edit sequence, each marked claim
is checked (at most MAX_CLAIMS):

1. Evidence: for [SRC: url], that page first; for every claim, the top results of the search API
   (apps.studio.serp, the brief's region) for the claim's own words, and the text of the best pages
   (apps.studio.webfetch, robots respected), cut to the passages that share the most words with the claim.
2. Judgement: the step's reasoning model reads the claim and the passages (prompts/verify_claim.md) and
   answers SUPPORTED, CONTRADICTED (with the corrected sentence) or NOT FOUND, naming the source.
3. Resolution: supported → the marker goes; contradicted → the sentence is corrected and the marker
   goes; not found (or not checked) → the sentence is taken out, since an unconfirmed claim isn't
   published. Every decision is listed in the step's notes, so a person can put a sentence back.
4. Finalising (`finalise`): the References section, the [SRC:] links and the [VISUAL:] cues leave the
   article for the step's source list (version metrics and notes), and the image planner's cues.

Never raises: a search or model failure counts as not found.
"""

import logging
import re
from dataclasses import dataclass, field

import httpx
from django.conf import settings

from apps.quality import house

from . import serp, webfetch

logger = logging.getLogger(__name__)

MAX_CLAIMS = 20
RESULTS_PER_CLAIM = 5
PAGES_PER_CLAIM = 2
PASSAGE_CHARS = 1400
MARKER = re.compile(r"[ \t]*\[\s*(VERIFY\b[^\]]*|SRC\s*:\s*[^\]]*)\]", re.I)
STOPWORDS = set(
    "a an and are as at be by can do does for from has have how i in is it its of on or should that the "
    "their this to was were what when which who will with you your must may any each every".split()
)


@dataclass
class Claim:
    kind: str  # "VERIFY" or "SRC"
    marker: str  # the marker as written
    sentence: str  # the sentence it marks, without markers (with the one before when it is short)
    url: str = ""  # [SRC: url]
    own: str = ""  # the marked sentence alone: what is taken out when no source confirms it
    context: str = ""  # the paragraph around it, so "These requirements" has its referent
    verdict: str = ""  # SUPPORTED, CONTRADICTED, NOT FOUND, or "" (not checked)
    source_url: str = ""
    source_title: str = ""
    corrected: str = ""
    why: str = ""


@dataclass
class Verification:
    text: str
    claims: list = field(default_factory=list)
    skipped: int = 0  # past MAX_CLAIMS
    problems: list = field(default_factory=list)
    sources: list = field(default_factory=list)  # [(title, url)]: the References and every [SRC:], kept apart
    visual_cues: list = field(default_factory=list)  # [(section, cue)] for the image planner

    @property
    def resolved(self):
        return [c for c in self.claims if c.verdict in ("SUPPORTED", "CONTRADICTED")]

    def summary(self):
        if not self.claims:
            return "No [VERIFY] or [SRC:] markers to check."
        counts = {}
        for claim in self.claims:
            counts[claim.verdict or "not checked"] = counts.get(claim.verdict or "not checked", 0) + 1
        names = {"SUPPORTED": "confirmed", "CONTRADICTED": "corrected", "NOT FOUND": "not confirmed"}
        text = ", ".join(f"{n} {names.get(verdict, verdict.lower())}" for verdict, n in counts.items())
        out = sum(c.verdict == "NOT FOUND" for c in self.claims) + self.skipped
        return (
            f"Checked {len(self.claims)} marked claim(s) against search results: {text}. "
            + (f"{out} unconfirmed sentence(s) taken out (listed in the notes). " if out else "")
            + "No markers are left; the sources are kept apart from the article."
        )

    def notes(self):
        lines = []
        for claim in self.claims:
            where = f" ({claim.source_title or claim.source_url})" if claim.source_url else ""
            if claim.verdict == "CONTRADICTED":
                lines.append(f"- Corrected{where}: “{claim.sentence}” → “{claim.corrected}”. {claim.why}")
            elif claim.verdict == "SUPPORTED":
                lines.append(f"- Confirmed{where}: “{claim.sentence[:160]}”. {claim.why}")
            elif claim.verdict == "":
                lines.append(f"- Not checked ({claim.why}), marker removed: “{claim.own or claim.sentence}”.")
            else:
                reason = claim.why or "not checked"
                lines.append(
                    f"- Taken out, no source confirmed it: “{claim.own or claim.sentence}”. {reason}"
                )
        if self.skipped:
            lines.append(
                f"- {self.skipped} more marked sentence(s) taken out unchecked (limit {MAX_CLAIMS})."
            )
        return lines


# ---- Finding the claims ----


def _plain(text):
    text = MARKER.sub("", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links to their anchor text
    return re.sub(r"[*_`]", "", text).strip()


def find_claims(text):
    """Each marker with the sentence it belongs to (a marker sits inside or right after its sentence)."""
    claims = []
    for paragraph in re.split(r"\n\s*\n", text):
        for match in MARKER.finditer(paragraph):
            before = paragraph[: match.start()].rstrip()
            # The sentence ends at the marker; it starts after the previous sentence's end. A "sentence"
            # that is only a citation ("(29 CFR 1910.119(l))") or a few words takes in the one before it.
            body = before[:-1] if before.endswith((".", "!", "?")) else before
            starts = [0] + [
                m.end() for m in re.finditer(r"[.!?][\"')\]]*\s+|^\s*(?:[-*]|\d+[.)])\s+|\n", body)
            ]
            starts = sorted(set(s for s in starts if s < len(body)))
            start = starts[-1]
            own = _plain(before[start:])
            if len(re.findall(r"[A-Za-z]{2,}", _plain(before[start:]))) < 6 and len(starts) > 1:
                start = starts[-2]
            sentence = _plain(before[start:])
            raw = match.group(1).strip()
            kind = "SRC" if raw.upper().startswith("SRC") else "VERIFY"
            url = raw.split(":", 1)[1].strip() if kind == "SRC" else ""
            context = _plain(paragraph)[:900]
            claims.append(Claim(kind, match.group(0).strip(), sentence, url=url, context=context, own=own))
    return claims


# ---- Evidence ----


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 1}


def best_passage(page_text, claim, limit=PASSAGE_CHARS):
    """The part of a page that shares the most words with the claim (numbers count double)."""
    target = _words(claim)
    numbers = {w for w in target if any(c.isdigit() for c in w)}
    # A cited subsection ("1910.119(l)") points at its own paragraph, which starts "(l)" on the page.
    labels = {m for cite in re.findall(r"\d{3,4}\.\d+((?:\([0-9a-zA-Z]{1,4}\))+)", claim)
              for m in re.findall(r"\([0-9a-zA-Z]{1,4}\)", cite)[:1]}  # fmt: skip
    paragraphs = [p.strip() for p in re.split(r"\n+", page_text or "") if len(p.split()) >= 6]
    if not paragraphs:
        return ""

    def score(index):
        window = " ".join(paragraphs[index : index + 3])
        found = _words(window)
        cited = sum(
            5 for label in labels if paragraphs[index].lstrip().startswith(label) or label in window[:80]
        )
        return len(found & target) + len(found & numbers) + cited

    best = max(range(len(paragraphs)), key=score)
    return " ".join(paragraphs[best : best + 3])[:limit]


def query_for(claim, topic=""):
    """The article's topic, then the claim's own words: no markers, links or filler, at most 16 words. The
    topic keeps a vague claim ("check each rule separately") on the article's subject."""
    words = [w for w in re.findall(r"[\w./()%-]+", _plain(claim)) if w.lower() not in STOPWORDS]
    lead = [w for w in topic.split() if w.lower() not in {x.lower() for x in words}]
    return " ".join((lead + words)[:16])


# Official sources: regulators, legislation and standards bodies. They are read first, and a claim about a
# rule is settled (confirmed or corrected) only by one of them.
# Government domains end in one of these; the others are named bodies (their host or a subdomain).
OFFICIAL_SUFFIXES = (".gov", ".gov.uk", ".gov.au", ".govt.nz", ".gc.ca", ".gov.ie", ".europa.eu")
OFFICIAL_DOMAINS = (
    "canada.ca", "hsa.ie", "ccohs.ca", "iso.org", "ansi.org", "nfpa.org", "who.int", "ilo.org", "unece.org",
)  # fmt: skip
# A claim about a rule: a citation, a regulation word, or a regulator's or rule's name.
RULE_CLAIM = re.compile(
    r"(?i:\b(?:CFR|U\.S\.C|regulations?|subsections?|paragraph \(|directive)\b)|\b\d{3,4}\.\d+"
    r"|\b(?:OSHA|HSE|EPA|WHS|COSHH|REACH|CLP|WHMIS|RIDDOR|GHS|PSM)\b"
)


def official(url):
    """A government, regulator or standards-body page."""
    host = re.sub(r"^https?://", "", url or "").split("/")[0].lower().split(":")[0]
    return host.endswith(OFFICIAL_SUFFIXES) or any(
        host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS
    )


def evidence(claim, region, client, topic=""):
    """[(title, url, passage)] for one claim: its [SRC] page first, then the search results, official
    sources first."""
    found, seen = [], set()

    def add_page(url, title):
        if url in seen or len(found) >= PAGES_PER_CLAIM + 1:
            return
        seen.add(url)
        root = re.match(r"^https?://[^/]+", url)
        if not root:
            return
        page = webfetch.fetch_page(url, client, webfetch.robots_for(root.group(0), client))
        passage = best_passage(page.text, claim.sentence) if page.text else ""
        if passage:
            found.append((title or url, url, passage))

    if claim.url.startswith("http"):
        add_page(claim.url, "")
    try:
        results = serp.search(query_for(claim.sentence, topic), region, num=RESULTS_PER_CLAIM).results
        results = sorted(results, key=lambda r: (not official(r.url), r.position))
    except serp.SerpError as error:
        results = []
        logger.info("Search for a claim failed: %s", error)
    for result in results[:RESULTS_PER_CLAIM]:
        if len(found) >= PAGES_PER_CLAIM + (1 if claim.url else 0):
            break
        add_page(result.url, result.title)
    if not found:  # pages blocked or empty: the snippets are still evidence, if thin
        found = [(r.title, r.url, r.snippet) for r in results[:3] if r.snippet]
    return found


# ---- Judging and resolving ----


def parse_answer(reply):
    def field_of(name):
        match = re.search(rf"(?im)^\s*\**{name}\**\s*:\s*(.+)$", reply or "")
        return match.group(1).strip() if match else ""

    verdict = field_of("VERDICT").upper().replace("_", " ")
    verdict = next((v for v in ("CONTRADICTED", "SUPPORTED", "NOT FOUND") if v in verdict), "NOT FOUND")
    number = re.search(r"\d+", field_of("SOURCE"))
    corrected = field_of("CORRECTED")
    if corrected.lower().strip(". ") in ("", "none", "n/a"):
        corrected = ""
    return verdict, int(number.group(0)) if number else None, corrected, field_of("WHY")


def _accept_correction(original, corrected):
    """A correction is used only if it is a sentence of similar length with no markers or links."""
    if not corrected or MARKER.search(corrected) or "](" in corrected or "\n" in corrected:
        return False
    return 0.5 <= len(corrected) / max(1, len(original)) <= 2.0


def _new_facts(original, corrected):
    """Numbers and section references the correction adds."""
    pattern = r"\d[\d.,]*(?:\([0-9a-zA-Z]+\))*"
    return set(re.findall(pattern, corrected)) - set(re.findall(pattern, original))


def resolve(text, region, call, client=None, topic=""):
    """Check every marked claim and resolve what the sources settle. `call(prompt_name, context)` returns
    the model's reply. Returns a Verification; its `text` is the article with the resolutions applied."""
    result = Verification(text=text)
    try:
        claims = find_claims(text)
    except Exception:  # noqa: BLE001
        logger.exception("Finding marked claims failed")
        return result
    result.skipped = max(0, len(claims) - MAX_CLAIMS)
    extra = claims[MAX_CLAIMS:]
    claims = claims[:MAX_CLAIMS]
    result.claims = claims
    references = []
    if not getattr(settings, "STUDIO_VERIFY_LOOKUPS", True):
        # Lookups off (tests, or no search API wanted): markers still go, sentences stay, the notes say so.
        result.skipped = 0
        for claim in claims + extra:
            claim.verdict, claim.why = "", "lookups are switched off"
            result.text = _apply(result.text, claim)
        result.claims = claims + extra
        result.text, found, result.visual_cues = finalise(result.text)
        result.sources = _unique(found + [(c.url, c.url) for c in claims + extra if c.url])
        return result
    with client or webfetch._client() as http:
        for claim in claims:
            try:
                found = evidence(claim, region, http, topic)
                if not found:
                    claim.verdict, claim.why = "NOT FOUND", "the search found no readable source"
                    continue
                sources = "\n\n".join(
                    f"{i}. {title} ({url})\n{passage}" for i, (title, url, passage) in enumerate(found, 1)
                )
                reply = call(
                    "verify_claim",
                    {
                        "claim": claim.sentence,
                        "context": claim.context,
                        "marker": claim.marker,
                        "sources": sources,
                    },
                )
                verdict, number, corrected, why = parse_answer(reply)
                claim.verdict, claim.why = verdict, why
                if number and 1 <= number <= len(found):
                    claim.source_title, claim.source_url = found[number - 1][0], found[number - 1][1]
                if verdict in ("SUPPORTED", "CONTRADICTED") and not claim.source_url:
                    claim.verdict, claim.why = "NOT FOUND", f"no source named ({why})"
                if claim.verdict == "CONTRADICTED" and not _accept_correction(claim.sentence, corrected):
                    claim.verdict, claim.why = "NOT FOUND", f"the correction wasn't usable ({why})"
                passage = found[number - 1][2] if number and 1 <= number <= len(found) else ""
                if claim.verdict == "CONTRADICTED" and any(
                    fact not in passage for fact in _new_facts(claim.sentence, corrected)
                ):
                    claim.verdict = "NOT FOUND"
                    claim.why = f"the correction adds a figure or reference the source doesn't show ({why})"
                rule = RULE_CLAIM.search(claim.sentence)
                if claim.verdict in ("SUPPORTED", "CONTRADICTED") and rule and not official(claim.source_url):
                    claim.verdict = "NOT FOUND"
                    claim.why = (
                        f"a claim about a rule needs an official source, not {claim.source_url} ({why})"
                    )
                claim.corrected = corrected if claim.verdict == "CONTRADICTED" else ""
            except (httpx.HTTPError, serp.SerpError) as error:
                claim.verdict, claim.why = "NOT FOUND", f"search failed ({type(error).__name__})"
            except Exception as error:  # noqa: BLE001 - a model or parsing failure keeps the marker
                logger.exception("Verifying a claim failed")
                claim.verdict, claim.why = "NOT FOUND", f"check failed ({type(error).__name__})"
                result.problems.append(str(error)[:200])
            if claim.verdict in ("SUPPORTED", "CONTRADICTED"):
                result.text = _apply(result.text, claim)
                references.append((claim.source_title, claim.source_url))
            else:
                result.text = _remove(result.text, claim)
    for claim in extra:
        result.text = _remove(result.text, claim)
    result.text, found, result.visual_cues = finalise(result.text)
    # Every [SRC:] the draft gave is a source, even where its sentence went: a record of what was read.
    cited = [(c.url, c.url) for c in claims + extra if c.url]
    result.sources = _unique(found + references + cited)
    return result


def _owns(paragraph, claim):
    """The paragraph holds this claim's marker and its sentence (the same marker can appear many times)."""
    return claim.marker in paragraph and _words(claim.own) <= _words(_plain(paragraph))


def _apply(text, claim):
    """Remove the claim's marker (and, when corrected, replace its sentence) in the article."""
    for paragraph in re.split(r"\n\s*\n", text):
        if not _owns(paragraph, claim):
            continue
        new = (
            paragraph.replace(" " + claim.marker, "", 1)
            if (" " + claim.marker) in paragraph
            else paragraph.replace(claim.marker, "", 1)
        )
        if claim.corrected:
            new = _replace_sentence(new, claim.sentence, claim.corrected)
        new = re.sub(r" +([,.;:!?])", r"\1", new)
        return text.replace(paragraph, new, 1)
    return text


def _replace_sentence(paragraph, sentence, corrected):
    """Swap the claim's sentence for the corrected one, matching on its plain words."""
    if sentence in paragraph:
        return paragraph.replace(sentence, corrected.rstrip("."), 1)
    pattern = r"\W+".join(re.escape(w) for w in re.findall(r"\w+", sentence))
    match = re.search(pattern, paragraph)
    return (
        paragraph[: match.start()] + corrected.rstrip(".") + paragraph[match.end() :] if match else paragraph
    )


def _remove(text, claim):
    """Take an unconfirmed claim's sentence (and its marker) out of the article."""
    for paragraph in re.split(r"\n\s*\n", text):
        if not _owns(paragraph, claim):
            continue
        new = paragraph.replace(claim.marker, "", 1)
        own = claim.own.strip()
        if own:
            pattern = r"\W+".join(re.escape(w) for w in re.findall(r"\w+", own))
            match = re.search(pattern + r"[^.!?\n]*[.!?]?[\"')\]]*", new)
            if match:
                new = new[: match.start()] + new[match.end() :]
        new = re.sub(r"[ \t]{2,}", " ", re.sub(r" +([,.;:!?])", r"\1", new))
        new = re.sub(r"(?m)^\s*(?:[-*]|\d+[.)])\s*$\n?", "", new).strip()
        return (
            text.replace(paragraph, new, 1)
            if new
            else text.replace(paragraph + "\n\n", "", 1).replace(paragraph, "", 1)
        )
    return text


def _unique(sources):
    seen, found = set(), []
    for title, url in sources:
        key = url or title
        if key and key not in seen:
            seen.add(key)
            found.append((title, url))
    return found


ANY_MARKER = re.compile(r"[ \t]*\[\s*(VERIFY\b[^\]]*|SRC\s*:\s*[^\]]*|VISUAL\s*:\s*[^\]]*)\]", re.I)
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def finalise(text):
    """(article, sources, visual cues): the References section, [SRC:] links and [VISUAL:] cues taken out,
    and any marker left over removed. Sources are [(title, url)], cues [(section, cue)]."""
    sources, cues = [], []
    match = re.search(r"(?im)^##\s+(?:References|Sources)\s*$", text)
    if match:
        nxt = re.search(r"(?m)^##\s+", text[match.end() :])
        end = match.end() + nxt.start() if nxt else len(text)
        for line in text[match.end() : end].splitlines():
            line = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            if not line:
                continue
            links = LINK.findall(line)
            urls = re.findall(r"https?://[^\s)\]]+", line)
            if links:
                sources += [(title, url) for title, url in links]
            elif urls:
                sources.append((line.split("http")[0].strip(" ,:-") or urls[0], urls[0]))
            else:
                sources.append((line, ""))
        text = (text[: match.start()].rstrip() + "\n\n" + text[end:].lstrip()).strip() + "\n"
    section = "(intro)"
    lines = []
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            section = heading.group(1).strip("* ")
        for marker in ANY_MARKER.finditer(line):
            raw = marker.group(1)
            if raw.upper().startswith("SRC"):
                url = raw.split(":", 1)[1].strip()
                sources.append((url, url))
            elif raw.upper().startswith("VISUAL"):
                cues.append((section, " ".join(raw.split(":", 1)[1].split())))
        lines.append(re.sub(r" +([,.;:!?])", r"\1", ANY_MARKER.sub("", line)))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
    return text, _unique(sources), cues


def remaining(text):
    """Markers still in the text (for the step's summary)."""
    return house.find_markers(text)
