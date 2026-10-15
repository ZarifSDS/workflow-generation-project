"""Resolving every marker after review and edit (apps/studio/verify.py): no marker and no References
section is left in the article; the sources are kept apart. No network: the search API, the page fetcher
and the model are fakes."""

import pytest

from apps.studio import serp, verify, webfetch

ARTICLE = """# SDS Retention

Employers must keep exposure records for at least 30 years under OSHA's records rule [VERIFY]. A short line.

The label must show the signal word and pictograms [SRC: https://www.osha.gov/hazcom]. Supervisors check it.

Training must happen every 90 days for every worker [VERIFY: frequency].

[VISUAL: chart, retention periods by record type]

## Frequently Asked Questions

### How long?

Thirty years.

## References

1. OSHA, [Access to exposure records](https://www.osha.gov/records), 29 CFR 1910.1020.
2. ANSI Z400.1 (no link).
"""


@pytest.fixture(autouse=True)
def lookups_on(settings):
    settings.STUDIO_VERIFY_LOOKUPS = True


@pytest.fixture
def fake_web(monkeypatch):
    pages = {
        "https://www.osha.gov/records": "Records rule. Each employer shall preserve exposure records for at "
        "least thirty (30) years after the employee leaves.\nUnrelated paragraph about parking spaces here.",
        "https://www.osha.gov/hazcom": "Labels shall include a signal word, pictograms and hazard statements "
        "for each hazard class, as section 1910.1200(f)(1) requires of every label.",
        "https://www.osha.gov/training": "Employers shall provide training at the time of initial assignment "
        "and whenever a new hazard is introduced into the work area.",
    }
    robots = type("R", (), {"can_fetch": lambda *a: True})()
    monkeypatch.setattr(webfetch, "robots_for", lambda base, client: robots)
    monkeypatch.setattr(
        webfetch,
        "fetch_page",
        lambda url, client, robots: webfetch.FetchedPage(url, "direct", pages.get(url, "")),
    )

    def search(query, region, num=10, client=None):
        url = "https://www.osha.gov/records" if "years" in query else "https://www.osha.gov/training"
        return serp.SerpData(
            "serper", query, "us", "en", results=[serp.Result(1, "OSHA page", url, "snippet")]
        )

    monkeypatch.setattr(serp, "search", search)
    return pages


def _no_markers(text):
    return not any(tag in text for tag in ("[VERIFY", "[SRC", "[VISUAL", "## References"))


def test_each_marker_is_found_with_its_own_sentence():
    claims = verify.find_claims(ARTICLE)
    assert [(c.kind, c.own) for c in claims] == [
        ("VERIFY", "Employers must keep exposure records for at least 30 years under OSHA's records rule"),
        ("SRC", "The label must show the signal word and pictograms"),
        ("VERIFY", "Training must happen every 90 days for every worker"),
    ]
    assert claims[1].url == "https://www.osha.gov/hazcom" and claims[2].marker == "[VERIFY: frequency]"


def test_a_citation_only_sentence_takes_in_the_one_before():
    text = "OSHA uses MOC for certain changes to covered processes. (29 CFR 1910.119(l)) [VERIFY]\n"
    (claim,) = verify.find_claims(text)
    assert claim.own == "(29 CFR 1910.119(l))" and claim.sentence.startswith("OSHA uses MOC")


def test_a_cited_subsection_points_at_its_own_paragraph():
    page = (
        "(d) Process safety information. The employer shall compile written information on the process.\n"
        "(l) Management of change. The employer shall establish written procedures to manage changes.\n"
    )
    passage = verify.best_passage(page, "These requirements appear under 29 CFR 1910.119(l)", limit=60)
    assert passage.startswith("(l) Management of change")


def test_official_sources_are_recognised_and_rule_claims_need_one():
    assert verify.official("https://www.osha.gov/laws-regs") and verify.official(
        "https://www.hse.gov.uk/coshh"
    )
    assert verify.official("https://iso.org/standard/1") and not verify.official(
        "https://mitti.com/topics/moc"
    )
    assert verify.RULE_CLAIM.search("as 29 CFR 1910.119(l) says") and verify.RULE_CLAIM.search(
        "OSHA requires"
    )
    assert not verify.RULE_CLAIM.search("Teams reach a decision and act on it to a high standard.")


def test_answers_are_parsed_and_bad_corrections_refused():
    reply = (
        "VERDICT: CONTRADICTED\nSOURCE: 2\nCORRECTED: Training happens at the first assignment.\nWHY: says so"
    )
    assert verify.parse_answer(reply) == (
        "CONTRADICTED",
        2,
        "Training happens at the first assignment.",
        "says so",
    )
    assert verify.parse_answer("garbage")[0] == "NOT FOUND"
    assert not verify._accept_correction("A short claim here.", "x")
    assert not verify._accept_correction("A short claim here.", "A claim [VERIFY] here.")


def test_confirmed_and_corrected_claims_stay_and_the_sources_leave_the_article(fake_web):
    def model(prompt, context):
        assert prompt == "verify_claim" and context["context"]
        if "30 years" in context["claim"]:
            return "VERDICT: SUPPORTED\nSOURCE: 1\nCORRECTED: none\nWHY: The rule says thirty years."
        if "signal word" in context["claim"]:
            return "VERDICT: SUPPORTED\nSOURCE: 1\nCORRECTED: none\nWHY: Section 1910.1200(f)(1)."
        return (
            "VERDICT: CONTRADICTED\nSOURCE: 1\nCORRECTED: Training must happen at the first assignment and "
            "whenever a new hazard arrives\nWHY: No 90-day rule."
        )

    result = verify.resolve(ARTICLE, "US", model)
    assert _no_markers(result.text)
    assert "for at least 30 years under OSHA's records rule. A short line." in result.text
    assert "Training must happen at the first assignment and whenever a new hazard arrives." in result.text
    assert "every 90 days" not in result.text and "## Frequently Asked Questions" in result.text
    urls = [url for _, url in result.sources]
    assert "https://www.osha.gov/records" in urls and "https://www.osha.gov/hazcom" in urls
    assert "https://www.osha.gov/training" in urls and ("ANSI Z400.1 (no link).", "") in result.sources
    assert result.visual_cues == [("(intro)", "chart, retention periods by record type")]
    assert "No markers are left" in result.summary()


def test_an_unconfirmed_claim_is_taken_out_not_left_marked(fake_web):
    result = verify.resolve(
        ARTICLE, "US", lambda p, c: "VERDICT: NOT FOUND\nSOURCE: none\nCORRECTED: none\nWHY: Silent."
    )
    assert _no_markers(result.text)
    assert "30 years" not in result.text and "every 90 days" not in result.text
    assert "A short line." in result.text and "Supervisors check it." in result.text  # the rest stays
    assert any(line.startswith("- Taken out, no source confirmed it") for line in result.notes())
    assert "3 unconfirmed sentence(s) taken out" in result.summary()


def test_a_model_failure_still_leaves_no_markers(fake_web):
    def broken(prompt, context):
        raise RuntimeError("provider down")

    result = verify.resolve(ARTICLE, "US", broken)
    assert _no_markers(result.text) and all(c.verdict == "NOT FOUND" for c in result.claims)


def test_with_lookups_off_markers_still_go_but_sentences_stay(settings):
    settings.STUDIO_VERIFY_LOOKUPS = False
    result = verify.resolve(ARTICLE, "US", lambda p, c: pytest.fail("no model call with lookups off"))
    assert _no_markers(result.text) and "every 90 days" in result.text and "30 years" in result.text
    assert all(line.startswith("- Not checked") for line in result.notes())


def test_finalise_removes_leftover_markers_and_the_references():
    text, sources, cues = verify.finalise(
        "Intro [VISUAL: photo of drums]. A fact [SRC: https://a.gov/x].\n\n## References\n\n- [A](https://a.gov/x)\n"
    )
    assert (
        text == "Intro. A fact.\n"
        and sources == [("A", "https://a.gov/x")]
        and cues == [("(intro)", "photo of drums")]
    )
