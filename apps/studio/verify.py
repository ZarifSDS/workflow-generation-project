"""Resolve the [VERIFY] and [SRC: url] markers in an edited article by looking the claims up.

The draft marks claims it couldn't confirm ([VERIFY…]) and the sources it used ([SRC: url]). Final cleanup
holds while any are left, which used to leave the work to a person. After the review-and-edit sequence,
each marked claim is now checked (at most MAX_CLAIMS):

1. Evidence: for [SRC: url], that page first; for every claim, the top results of the search API
   (apps.studio.serp, the brief's region) for the claim's own words, and the text of the best pages
   (apps.studio.webfetch, robots respected), cut to the passages that share the most words with the claim.
2. Judgement: the step's reasoning model reads the claim and the passages (prompts/verify_claim.md) and
   answers SUPPORTED, CONTRADICTED (with the corrected sentence) or NOT FOUND, naming the source.
3. Resolution: supported → the marker goes and the source joins the References; contradicted → the
   sentence is corrected, the marker goes and the source joins the References; not found → the marker
   stays for a person, with a note. Every decision is listed in the step's notes.

Never raises: a search or model failure leaves the marker in place and says so.
"""

import logging
import re
from dataclasses import dataclass, field

import httpx

from apps.quality import house

from . import serp, webfetch

logger = logging.getLogger(__name__)

MAX_CLAIMS = 12
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
    sentence: str  # the sentence it marks, without markers
    url: str = ""  # [SRC: url]
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

    @property
    def resolved(self):
        return [c for c in self.claims if c.verdict in ("SUPPORTED", "CONTRADICTED")]

    def summary(self):
        if not self.claims:
            return "No [VERIFY] or [SRC:] markers to check."
        counts = {}
        for claim in self.claims:
            counts[claim.verdict or "not checked"] = counts.get(claim.verdict or "not checked", 0) + 1
        text = ", ".join(f"{n} {verdict.lower()}" for verdict, n in counts.items())
        left = len(self.claims) - len(self.resolved) + self.skipped
        return f"Checked {len(self.claims)} marked claim(s) against search results: {text}. " + (
            f"{left} marker(s) stay for a person." if left else "Every marker was resolved."
        )

    def notes(self):
        lines = []
        for claim in self.claims:
            where = f" ({claim.source_title or claim.source_url})" if claim.source_url else ""
            if claim.verdict == "CONTRADICTED":
                lines.append(f"- Corrected{where}: “{claim.sentence}” → “{claim.corrected}”. {claim.why}")
            elif claim.verdict == "SUPPORTED":
                lines.append(f"- Confirmed{where}: “{claim.sentence[:160]}”. {claim.why}")
            else:
                reason = claim.why or "not checked"
                lines.append(f"- Still to check by hand: “{claim.sentence[:160]}” {claim.marker}. {reason}")
        if self.skipped:
            lines.append(f"- {self.skipped} more marked claim(s) weren't checked (limit {MAX_CLAIMS} a run).")
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
            if len(re.findall(r"[A-Za-z]{2,}", _plain(before[start:]))) < 6 and len(starts) > 1:
                start = starts[-2]
            sentence = _plain(before[start:])
            if len(sentence.split()) < 4:
                continue
            raw = match.group(1).strip()
            kind = "SRC" if raw.upper().startswith("SRC") else "VERIFY"
            url = raw.split(":", 1)[1].strip() if kind == "SRC" else ""
            context = _plain(paragraph)[:900]
            claims.append(Claim(kind, match.group(0).strip(), sentence, url=url, context=context))
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
    claims = claims[:MAX_CLAIMS]
    result.claims = claims
    references = []
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
    result.text = _add_references(result.text, references)
    return result


def _apply(text, claim):
    """Remove the claim's marker (and, when corrected, replace its sentence) in the article."""
    for paragraph in re.split(r"\n\s*\n", text):
        if claim.marker not in paragraph:
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


def _add_references(text, references):
    """Add each new source to the References section (created at the end, where the draft puts it)."""
    new = []
    for title, url in references:
        if url and url not in text and url not in [u for _, u in new]:
            new.append((title, url))
    if not new:
        return text
    match = re.search(r"(?im)^##\s+References\s*$", text)
    if match:
        nxt = re.search(r"(?m)^##\s+", text[match.end() :])
        end = match.end() + nxt.start() if nxt else len(text)
        numbers = [int(n) for n in re.findall(r"(?m)^(\d+)\.\s", text[match.end() : end])]
        if numbers:  # continue the section's own numbered style
            lines = "\n".join(
                f"{numbers[-1] + i}. [{(title or url).strip()}]({url})"
                for i, (title, url) in enumerate(new, 1)
            )
        else:
            lines = "\n".join(f"- [{(title or url).strip()}]({url})" for title, url in new)
        return text[:end].rstrip() + "\n" + lines + "\n\n" + text[end:].lstrip()
    lines = "\n".join(f"- [{(title or url).strip()}]({url})" for title, url in new)
    return text.rstrip() + f"\n\n## References\n\n{lines}\n"


def remaining(text):
    """Markers still in the text (for the step's summary)."""
    return house.find_markers(text)
