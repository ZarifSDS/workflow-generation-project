"""Resolving [VERIFY] and [SRC:] markers by looking the claims up (apps/studio/verify.py). No network:
the search API, the page fetcher and the model are fakes."""

import pytest

from apps.studio import serp, verify, webfetch

ARTICLE = """# SDS Retention

Employers must keep exposure records for at least 30 years under OSHA's records rule [VERIFY]. A short line.

The label must show the signal word and pictograms [SRC: https://www.osha.gov/hazcom]. Supervisors check it.

Training must happen every 90 days for every worker [VERIFY: frequency].

## Frequently Asked Questions

### How long?

Thirty years.
"""


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
    monkeypatch.setattr(
        webfetch, "robots_for", lambda base, client: type("R", (), {"can_fetch": lambda *a: True})()
    )
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


def test_each_marker_is_found_with_its_own_sentence():
    claims = verify.find_claims(ARTICLE)
    assert [(c.kind, c.sentence) for c in claims] == [
        ("VERIFY", "Employers must keep exposure records for at least 30 years under OSHA's records rule"),
        ("SRC", "The label must show the signal word and pictograms"),
        ("VERIFY", "Training must happen every 90 days for every worker"),
    ]
    assert claims[1].url == "https://www.osha.gov/hazcom" and claims[2].marker == "[VERIFY: frequency]"


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


def test_the_passage_is_the_part_of_the_page_about_the_claim():
    page = (
        "Parking rules for visitors and staff.\nEmployers shall keep exposure records for thirty (30) years."
    )
    assert "thirty (30) years" in verify.best_passage(page, "keep exposure records for 30 years")


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


def test_supported_contradicted_and_not_found_are_resolved_as_they_should(fake_web):
    def model(prompt, context):
        assert prompt == "verify_claim"
        if "30 years" in context["claim"]:
            return "VERDICT: SUPPORTED\nSOURCE: 1\nCORRECTED: none\nWHY: The rule says thirty years."
        if "signal word" in context["claim"]:
            return "VERDICT: SUPPORTED\nSOURCE: 1\nCORRECTED: none\nWHY: Section 1910.1200(f)(1)."
        return (
            "VERDICT: CONTRADICTED\nSOURCE: 1\nCORRECTED: Training must happen at the first assignment and "
            "whenever a new hazard arrives\nWHY: No 90-day rule."
        )

    result = verify.resolve(ARTICLE, "US", model, client=None)
    assert "[VERIFY" not in result.text and "[SRC:" not in result.text
    assert "for at least 30 years under OSHA's records rule. A short line." in result.text
    assert "Training must happen at the first assignment and whenever a new hazard arrives." in result.text
    assert "every 90 days" not in result.text
    # New sources go to the References section at the end (the [SRC] page among them).
    refs = result.text.split("## References", 1)[1]
    assert "https://www.osha.gov/records" in refs and "https://www.osha.gov/training" in refs
    assert "Every marker was resolved." in result.summary()
    assert any(line.startswith("- Corrected") for line in result.notes())


def test_a_claim_no_source_settles_keeps_its_marker(fake_web):
    result = verify.resolve(
        ARTICLE, "US", lambda p, c: "VERDICT: NOT FOUND\nSOURCE: none\nCORRECTED: none\nWHY: Silent."
    )
    assert result.text.count("[VERIFY") == 2 and "[SRC: https://www.osha.gov/hazcom]" in result.text
    assert "stay for a person" in result.summary()


def test_a_model_failure_keeps_every_marker(fake_web):
    def broken(prompt, context):
        raise RuntimeError("provider down")

    result = verify.resolve(ARTICLE, "US", broken)
    assert result.text == ARTICLE and all(c.verdict == "NOT FOUND" for c in result.claims)
