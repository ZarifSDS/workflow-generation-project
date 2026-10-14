"""Search results step, audience profiles, per-section reading-grade tuning and the suggestions chat."""

import json
from types import SimpleNamespace

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.quality import review
from apps.studio import assistant, executors, prompting, serp, services
from apps.studio.models import AudienceProfile, ChatMessage, ContentBrief, StepRun

pytestmark = pytest.mark.django_db

SEARCH_KEYS = [
    "SERPER_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "GOOGLE_CSE_API_KEY",
    "GOOGLE_CSE_CX",
    "OLLAMA_CLOUD_API_KEY",
]

RANKING_HTML = """<html><head><script type="application/ld+json">{"@type": "FAQPage"}</script></head><body>
<nav><h2>Menu</h2></nav>
<h1>How long to keep safety data sheets</h1>
<h2>What OSHA requires</h2><p>{text}</p>
<h3>Exposure records</h3><p>{text}</p>
<h2>How to store SDS records</h2><ul><li>Digital</li></ul><table><tr><td>a</td></tr></table>
<h2>Frequently asked questions</h2><p>{text}</p><img src="x.png">
</body></html>""".replace("{text}", "Employers keep each safety data sheet for thirty years. " * 30)

LONG_ARTICLE = (
    "# Title\n\nIntro sentence that is short.\n\n"
    "## Big section\n\n" + "Opening words for the section. " * 40 + "\n\n"
    # Long, stacked sentences (about 30 words): above the vocabulary floor, so tuning has syntax to unpack.
    "### First part\n\n" + "Notwithstanding the aforementioned considerations, organisational accountability "
    "necessitates comprehensive documentation procedures, which employers implement whenever operational "
    "circumstances change, because regulatory authorities scrutinise organisational documentation. "
    * 5
    + "\n\n"
    "### Second part\n\n" + "Keep it simple. Short words help. " * 15 + "\n\n"
    "## Small section\n\n" + "A few plain words here for the reader to see. " * 3 + "\n"
)


VARIED = (
    "Keep good records. Write down what you did, why you did it and who checked the result before the job "
    "closed. Store them where the crew can reach them. "
)


@pytest.fixture
def no_search_keys(monkeypatch):
    for name in SEARCH_KEYS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def brief(admin_user):
    return ContentBrief.objects.create(
        topic="How long to keep SDS",
        pkeyword="sds retention",
        content_type="seo_blog",
        region="UK",
        fkgl=8,
        created_by=admin_user,
    )


def _ready(step, text):
    services.add_version(step, text, provider="ollama_cloud", model="gpt-oss:120b")
    step.status = StepRun.Status.READY
    step.save()
    return step


def _fake_call(text_for):
    def call(step, messages, max_tokens=None, task=None):
        return SimpleNamespace(
            text=text_for(messages, task), provider="ollama_cloud", model="gpt-oss:120b", stats={}
        )

    return call


# ---- Search results ----


def test_structure_parser_reads_outline_formats_and_faq_schema():
    parsed = serp.parse_structure(RANKING_HTML)
    assert parsed.outline[0] == (1, "How long to keep safety data sheets")
    assert (2, "Menu") not in parsed.outline  # navigation is ignored
    assert (3, "Exposure records") in parsed.outline
    assert parsed.tables == 1 and parsed.lists == 1 and parsed.images == 1 and parsed.faq_schema


def test_serper_results_use_the_brief_locale(monkeypatch, no_search_keys, settings):
    monkeypatch.setenv("SERPER_API_KEY", "test-serper-key-123")
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "organic": [{"title": "SDS retention", "link": "https://example.com/a", "position": 1}],
                "peopleAlsoAsk": [{"question": "How long must SDS be kept in the UK?"}],
                "relatedSearches": [{"query": "coshh records retention"}],
            },
        )

    data = serp.search("sds retention", "UK", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen["body"]["gl"] == "gb" and seen["body"]["hl"] == "en"
    assert data.provider == "serper" and data.results[0].url == "https://example.com/a"
    assert data.questions == ["How long must SDS be kept in the UK?"]


def test_search_without_any_provider_explains_how_to_set_one_up(no_search_keys, settings):
    settings.STUDIO_SERP_PROVIDERS = ["serper", "brave_search", "google_cse", "ollama_web"]
    with pytest.raises(serp.SerpError, match="Settings › Search data providers"):
        serp.search("sds retention", "US")


def test_autocomplete_collects_question_forms():
    def handler(request):
        q = request.url.params["q"]
        return httpx.Response(200, json=[q, [f"{q} uk", "sds retention"]])

    found = serp.autocomplete(
        "sds retention", "UK", client=httpx.Client(transport=httpx.MockTransport(handler)), pace=0
    )
    assert "how sds retention uk" in found and "sds retention" not in found


def test_analysis_finds_recurring_themes_and_report_lists_outlines():
    def page(position, h2s, words):
        return serp.PageStructure(
            position,
            f"https://site{position}.com",
            f"Page {position}",
            outline=[(2, h) for h in h2s],
            words=words,
            grade=9.0,
            faq=position == 1,
        )

    pages = [
        page(1, ["OSHA retention rules", "Digital storage"], 1500),
        page(2, ["Retention rules by state", "Storage options"], 1900),
        page(3, ["Who needs SDS", "Digital storage tips"], 1200),
    ]
    summary = serp.analyse(pages, "sds retention")
    assert summary["median_words"] == 1500 and summary["with_faq"] == 1
    assert {"rules", "storage", "digital"} <= {t["term"] for t in summary["themes"]}
    data = serp.SerpData(
        "serper", "sds retention", "gb", "en", results=[serp.Result(1, "Page 1", "https://site1.com")]
    )
    text = serp.report(data, ["how sds retention works"], pages, summary, "sds retention", "UK", "site1.com")
    assert "median 1500 words" in text and "(yours)" in text and "H2: Digital storage" in text


@pytest.mark.search_step
def test_search_step_feeds_research(monkeypatch, brief):
    run = services.create_run(brief, {})
    step = run.steps.get(key="search_results")
    assert step.status == StepRun.Status.QUEUED and not step.gate
    data = serp.SerpData(
        "serper", "sds retention", "gb", "en", results=[serp.Result(1, "A", "https://a.com")]
    )
    monkeypatch.setattr(serp, "search", lambda *a, **k: data)
    monkeypatch.setattr(serp, "autocomplete", lambda *a, **k: ["what is sds retention"])
    monkeypatch.setattr(
        serp,
        "read_pages",
        lambda *a, **k: [serp.PageStructure(1, "https://a.com", "A", outline=[(2, "Rules")], words=900)],
    )

    from apps.studio.tasks import execute_step

    execute_step(step.pk)
    step.refresh_from_db()
    assert step.status == StepRun.Status.APPROVED  # continues on its own
    assert run.steps.get(key="research").status == StepRun.Status.QUEUED
    research = run.steps.get(key="research")
    user_prompt = prompting.render("research", prompting.context_for(research))[1]["content"]
    assert "What currently ranks" in user_prompt and "what is sds retention" in user_prompt


# ---- Audience profiles ----


def test_seeded_audience_profiles_reach_the_prompts(brief):
    assert set(AudienceProfile.objects.values_list("region", flat=True)) == {
        "US",
        "UK",
        "AU",
        "CA",
        "NZ",
        "EU",
    }
    run = services.create_run(brief, {})
    outline = run.steps.get(key="outline")
    user_prompt = prompting.render("outline", prompting.context_for(outline))[1]["content"]
    assert "Audience for UK" in user_prompt and "UK spelling" in user_prompt


def test_wizard_prefills_audience_from_profiles(admin_client):
    html = admin_client.get(reverse("studio:brief_new")).content.decode()
    assert 'id="studio-audiences"' in html and "EHS managers, safety coordinators" in html


# ---- Section units and tuning ----


def test_long_h2_sections_are_split_at_their_h3s():
    units = review.section_units(LONG_ARTICLE)
    names = [review.heading_name(h) for h, _ in units]
    assert names == ["(intro)", "Big section", "First part", "Second part", "Small section"]
    assert review.join_sections(units) == LONG_ARTICLE
    rows = review.unit_rows(LONG_ARTICLE, 8)
    first_part = next(r for r in rows if r["name"] == "First part")
    assert first_part["level"] == 3 and first_part["over"]


def test_tune_unit_rewrites_only_that_section():
    index = [review.heading_name(h) for h, _ in review.section_units(LONG_ARTICLE)].index("First part")
    simple = "### First part\n\n" + VARIED * 4

    text, before, after = review.tune_unit(LONG_ARTICLE, index, 8, "UK", lambda name, ctx: simple)
    assert after < before
    assert "Keep good records" in text and "Notwithstanding" not in text
    assert "Keep it simple. Short words help." in text and text.count("### Second part") == 1


def test_word_level_pass_uses_the_brief_target_not_grade_13():
    calls = []

    def call(name, ctx):
        if name == "review_wordlevel":
            calls.append(ctx["section"].splitlines()[0])
            return ctx["section"]
        return ctx.get("article", "")

    review.run_sequence(LONG_ARTICLE, {"fkgl": 8}, call)
    assert "### First part" in calls  # an H3 inside a long section is tuned on its own


# ---- Suggestions chat and Tune ----


def test_chat_suggest_apply_and_tune(monkeypatch, brief, admin_user):
    run = services.create_run(brief, {})
    step = _ready(run.steps.get(key="draft"), LONG_ARTICLE)

    def answers(messages, task):
        system = messages[0]["content"]
        if "Return the complete revised" in messages[-1]["content"]:
            return LONG_ARTICLE.replace("Intro sentence that is short.", "A clearer intro.")
        if task == "section_tune":
            return "### First part\n\n" + VARIED * 4
        assert "concrete suggestions" in system
        return "1. Shorten the First part section."

    monkeypatch.setattr(executors, "_call_text", _fake_call(answers))

    reply = assistant.ask(step, admin_user, "What should I fix first?")
    assert reply.status == ChatMessage.Status.PENDING
    with pytest.raises(ValueError, match="Wait for the current reply"):
        assistant.ask(step, admin_user, "Another one")
    assistant.answer(reply.pk)
    reply.refresh_from_db()
    assert reply.status == ChatMessage.Status.DONE and "Shorten the First part" in reply.content

    applied = assistant.ask(step, admin_user, "Make the intro clearer", ChatMessage.Action.APPLY)
    assistant.answer(applied.pk)
    applied.refresh_from_db()
    assert applied.version_number == 2 and "A clearer intro." in step.latest_version.content

    index = next(
        r["index"] for r in review.unit_rows(step.latest_version.content) if r["name"] == "First part"
    )
    tuned = assistant.tune_request(step, admin_user, index, 8)
    assistant.answer(tuned.pk)
    tuned.refresh_from_db()
    assert tuned.status == ChatMessage.Status.DONE and tuned.version_number == 3
    assert "First part" in tuned.content and "→" in tuned.content
    step.refresh_from_db()
    assert step.status == StepRun.Status.READY  # still waiting for your review


def test_chat_apply_that_drops_headings_is_refused(monkeypatch, brief, admin_user):
    run = services.create_run(brief, {})
    step = _ready(run.steps.get(key="outline"), LONG_ARTICLE)
    monkeypatch.setattr(executors, "_call_text", _fake_call(lambda m, t: "Just one line."))
    reply = assistant.ask(step, admin_user, "Rewrite it", ChatMessage.Action.APPLY)
    assistant.answer(reply.pk)
    reply.refresh_from_db()
    assert reply.status == ChatMessage.Status.FAILED and "wasn't saved" in reply.content
    assert step.versions.count() == 1


def test_workspace_shows_grades_tune_and_chat(admin_client, brief):
    run = services.create_run(brief, {})
    _ready(run.steps.get(key="draft"), LONG_ARTICLE)
    url = reverse("studio:run", args=[run.pk]) + "?step=draft"
    html = admin_client.get(url).content.decode()
    assert "Reading grade" in html and "Whole article: FKGL" in html and 'value="tune"' in html
    assert "Ask for suggestions" in html and "Apply as new version" in html

    response = admin_client.post(url, {"step": "draft", "action": "chat_suggest", "message": "Ideas?"})
    assert response.status_code == 302
    assert ChatMessage.objects.filter(step__run=run, role="assistant", status="pending").exists()
    data = admin_client.get(reverse("studio:run_status", args=[run.pk])).json()
    assert data["active"] is True  # the page keeps polling until the reply arrives


def test_writers_cannot_chat_on_editing_steps(client, brief):
    writer = get_user_model().objects.create_user("writer", password="unused-test-password")
    writer.groups.add(Group.objects.get(name="Writers"))
    client.force_login(writer)
    run = services.create_run(brief, {})
    _ready(run.steps.get(key="review_edit"), LONG_ARTICLE)
    client.post(
        reverse("studio:run", args=[run.pk]),
        {"step": "review_edit", "action": "chat_suggest", "message": "Ideas?"},
    )
    assert not ChatMessage.objects.exists()
