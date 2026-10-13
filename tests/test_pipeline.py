"""M4: step execution with fake providers (no real API calls)."""

import json

import httpx
import pytest
import respx
from django.urls import reverse

from apps.ai.types import GenerationResult, ImageResult, ProviderError
from apps.quality import hero
from apps.studio import executors, services, textclean, webfetch
from apps.studio.models import ContentBrief, MetadataOption, StepRun
from apps.studio.tasks import execute_step

pytestmark = pytest.mark.django_db

DRAFT_TEXT = """# SDS Retention Requirements Explained

SDS retention requirements come from OSHA's records standard. Keep a record for 30 years [VERIFY].

## How long to keep safety data sheets

Keep the current SDS on every shift.

## Metadata options
### Titles
- SDS Retention Requirements: How Long to Keep SDSs (49 characters)
- How Long to Keep Safety Data Sheets
### Meta descriptions
- OSHA treats SDSs as exposure records. Learn the retention rules and the 30-year record option for your site.
### Slug
- `sds-retention-requirements`
"""


class FakeLLM:
    """Records calls and answers by step template."""

    def __init__(self, fail_first=None):
        self.calls, self.fail_first = [], fail_first

    def __call__(self, provider, model, messages, options):
        self.calls.append((provider, model, messages))
        if self.fail_first and len(self.calls) == 1:
            raise ProviderError(self.fail_first, "quota hit", 429)
        user = messages[-1]["content"]
        if isinstance(user, list):  # the hero vision check sends text plus the image
            text = json.dumps(
                {
                    "subject": [0.64, 0.1, 0.92, 1.0],
                    "person_at_left_edge": True,
                    "facing": "left",
                    "readable_text": ["drum label, right edge"],
                    "safety_issues": ["no gloves while handling drums"],
                    "scene": "chemical store",
                }
            )
        elif "Write the full piece" in user:
            text = DRAFT_TEXT
        elif "image prompt" in user.lower():
            text = "A clean records room with binders, soft daylight, no text."
        elif "Edit this draft" in user:
            text = "# Edited article\n\nShorter sentences.\n\n## Changelog\n- Removed filler."
        else:
            text = f"# Output from {model}\n\nSDS retention requirements notes."
        return GenerationResult(provider=provider, model=model, text=text, output_tokens=120, total_time=0.1)


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(executors, "generate", fake)
    return fake


@pytest.fixture
def brief(admin_user):
    return ContentBrief.objects.create(
        topic="How long to keep SDSs",
        pkeyword="SDS retention requirements",
        skeywords=["how long to keep safety data sheets"],
        wordcount=1200,
        fkgl=9,
        region="US",
        content_type="seo_blog",
        created_by=admin_user,
    )


def approve(step, user):
    step.refresh_from_db()
    services.approve_step(step, user)


def test_research_runs_and_waits_for_review(brief, fake_llm):
    run = services.create_run(brief, {})
    research = run.steps.get(key="research")
    execute_step(research.pk)
    research.refresh_from_db()
    assert research.status == StepRun.Status.READY
    assert research.latest_version.content.startswith("# Output from")
    run.refresh_from_db()
    assert run.status == "needs_review"


def test_outline_receives_approved_research(brief, fake_llm, admin_user):
    run = services.create_run(brief, {})
    execute_step(run.steps.get(key="research").pk)
    approve(run.steps.get(key="research"), admin_user)
    execute_step(run.steps.get(key="outline").pk)
    outline_prompt = fake_llm.calls[-1][2][-1]["content"]
    assert "Approved research notes" in outline_prompt and "Output from" in outline_prompt


def test_draft_creates_title_meta_and_slug_options(brief, fake_llm, admin_user):
    run = services.create_run(brief, {})
    for key in ("research", "outline"):
        execute_step(run.steps.get(key=key).pk)
        approve(run.steps.get(key=key), admin_user)
    draft = run.steps.get(key="draft")
    execute_step(draft.pk)
    draft.refresh_from_db()
    assert "## Metadata options" not in draft.latest_version.content
    titles = list(run.metadata_options.filter(kind="title").values_list("text", "selected"))
    assert titles[0] == ("SDS Retention Requirements: How Long to Keep SDSs", True)
    assert run.metadata_options.get(kind="slug").text == "sds-retention-requirements"


def test_ungated_cleanup_continues_automatically(brief, fake_llm, admin_user):
    run = services.create_run(brief, {})
    for key in ("research", "outline", "draft", "review_edit"):
        execute_step(run.steps.get(key=key).pk)
        approve(run.steps.get(key=key), admin_user)
    review = run.steps.get(key="review_edit")
    assert "## Review sequence" in review.latest_version.note
    cleanup = run.steps.get(key="cleanup")
    assert cleanup.status == StepRun.Status.QUEUED
    execute_step(cleanup.pk)
    cleanup.refresh_from_db()
    assert cleanup.status == StepRun.Status.APPROVED
    assert run.steps.get(key="hero_image").status == StepRun.Status.QUEUED


def test_fallback_model_is_used_and_noted(brief, monkeypatch):
    fake = FakeLLM(fail_first="rate_limited")
    monkeypatch.setattr(executors, "generate", fake)
    run = services.create_run(brief, {})
    research = run.steps.get(key="research")
    execute_step(research.pk)
    research.refresh_from_db()
    assert research.status == StepRun.Status.READY
    assert "fallback" in research.latest_version.note
    assert fake.calls[1][0] != fake.calls[0][0] or fake.calls[1][1] != fake.calls[0][1]


def test_failure_is_explained_and_retryable(brief, monkeypatch, settings):
    def broken(*args, **kwargs):
        raise ProviderError("not_free", "402 payment required", 402)

    monkeypatch.setattr(executors, "generate", broken)
    run = services.create_run(brief, {})
    research = run.steps.get(key="research")
    execute_step(research.pk)
    research.refresh_from_db()
    assert research.status == StepRun.Status.FAILED
    assert "free plan" in research.error
    services.retry_step(research)
    research.refresh_from_db()
    assert research.status == StepRun.Status.QUEUED


@pytest.fixture
def fake_images(monkeypatch):
    calls = {"generate": 0, "brand": [], "prompts": [], "too_far_left": 0}

    def generate_image(provider, model, prompt, options):
        calls["generate"] += 1
        calls["prompts"].append(prompt)
        return ImageResult(provider=provider, model=model, data=_tiny_png(), mime_type="image/png")

    def brand(photo, markup, vision):
        calls["brand"].append((markup, vision))
        if calls["too_far_left"]:
            calls["too_far_left"] -= 1
            return hero.HeroResult(
                metrics={"headline": markup}, flags=["too far left"], subject_too_far_left=True
            )
        if "too long" in markup:
            return hero.HeroResult(
                metrics={"headline": markup}, headline_problem="Shorten it to about 60 characters"
            )
        fit = {"lines": 2, "size_px": 26.5, "scale_percent": 100, "ends_x": 300, "limit_x": 331}
        return hero.HeroResult(
            png=_tiny_png(), webp=b"webp", metrics={"headline": markup, "headline_fit": fit}
        )

    monkeypatch.setattr(executors, "generate_image", generate_image)
    monkeypatch.setattr(hero, "brand", brand)
    return calls


def _run_hero(brief, note=""):
    run = services.create_run(brief, {})
    step = run.steps.get(key="hero_image")
    step.status, step.regenerate_note = StepRun.Status.QUEUED, note
    step.save()
    execute_step(step.pk)
    step.refresh_from_db()
    return step


def test_hero_image_is_checked_branded_and_saved(brief, fake_llm, fake_images):
    step = _run_hero(brief)
    assert step.status == StepRun.Status.READY, step.error
    version = step.latest_version
    hero_metrics = version.metrics["hero"]
    assert version.image.title.startswith("Hero: ")
    assert hero_metrics["branded"] is True
    assert hero_metrics["photo_image_id"] != version.image.pk
    markup, vision = fake_images["brand"][0]
    assert markup == brief.topic  # no colon and no primary keyword in it: nothing in periwinkle
    assert vision["subject"] == [0.64, 0.1, 0.92, 1.0]
    assert "Safety: no gloves while handling drums" in hero_metrics["flags"]
    assert "Readable text or logo in the photo: drum label, right edge" in version.note
    assert "Headline fit: 2 lines" in version.note
    assert "Vision check: " in version.note
    assert "Image prompt" in version.note


def test_hero_checks_panel_replaces_text_checks(brief, fake_llm, fake_images, admin_client):
    step = _run_hero(brief)
    response = admin_client.get(reverse("studio:run", args=[step.run.pk]) + "?step=hero_image")
    assert "Hero checks" in response.text
    assert "Unbranded photo" in response.text
    assert "Primary keyword in title" not in response.text


def test_headline_note_rebrands_the_same_photo(brief, fake_llm, fake_images):
    step = _run_hero(brief)
    photo_id = step.latest_version.metrics["hero"]["photo_image_id"]
    services.request_regenerate(step, f"{step.provider}::{step.model}", "Headline: **SDS Rules:** | Short")
    execute_step(step.pk)
    step.refresh_from_db()
    assert fake_images["generate"] == 1
    assert fake_images["brand"][-1][0] == "**SDS Rules:** | Short"
    assert step.latest_version.metrics["hero"]["photo_image_id"] == photo_id


def test_headline_too_long_keeps_the_photo_and_explains(brief, fake_llm, fake_images):
    step = _run_hero(brief, note="Headline: way too long headline")
    version = step.latest_version
    assert step.status == StepRun.Status.READY
    assert version.metrics["hero"]["branded"] is False
    assert version.image.title.startswith("Hero photo (unbranded)")
    assert "too long for the hero" in version.note


def test_vision_failure_is_reported_not_fatal(brief, fake_llm, fake_images, monkeypatch):
    def no_vision(provider, model, messages, options):
        if isinstance(messages[-1]["content"], list):
            raise ProviderError("bad_request", "no images", 400)
        return fake_llm(provider, model, messages, options)

    monkeypatch.setattr(executors, "generate", no_vision)
    step = _run_hero(brief)
    assert step.status == StepRun.Status.READY, step.error
    assert fake_images["brand"][0][1] is None
    assert "vision check failed" in step.latest_version.note


def _tiny_png():
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "teal").save(buffer, "PNG")
    return buffer.getvalue()


def test_site_crawl_builds_profile_and_lists_pages(brief, fake_llm, monkeypatch):
    brief.content_type, brief.site_domain = "outbound", "https://blog.example.com/"
    brief.save()
    text = "word " * 400
    monkeypatch.setattr(
        webfetch,
        "crawl_site",
        lambda *a, **k: [
            webfetch.FetchedPage("https://blog.example.com/", "direct", text, ["Intro"]),
            webfetch.FetchedPage("https://blog.example.com/blog/a", "reader", text, ["How to"]),
            webfetch.FetchedPage("https://blog.example.com/members/x", "skipped", reason="Requires login"),
        ],
    )
    run = services.create_run(brief, {})
    crawl = run.steps.get(key="site_crawl")
    execute_step(crawl.pk)
    crawl.refresh_from_db()
    content = crawl.latest_version.content
    assert "## Pages read" in content and "Reader service" in content and "Requires login" in content


def test_site_crawl_fails_clearly_when_site_unreadable(brief, fake_llm, monkeypatch):
    brief.content_type, brief.site_domain = "outbound", "https://blocked.example.com/"
    brief.save()
    monkeypatch.setattr(
        webfetch,
        "crawl_site",
        lambda *a, **k: [
            webfetch.FetchedPage("https://blocked.example.com/", "skipped", reason="Disallowed by robots.txt")
        ],
    )
    run = services.create_run(brief, {})
    crawl = run.steps.get(key="site_crawl")
    execute_step(crawl.pk)
    crawl.refresh_from_db()
    assert crawl.status == StepRun.Status.FAILED and "public pages" in crawl.error


def test_queued_step_runs_through_the_task_queue(
    brief, fake_llm, settings, django_capture_on_commit_callbacks
):
    settings.STUDIO_EXECUTE_STEPS = True  # tasks use the inline ImmediateBackend in tests
    with django_capture_on_commit_callbacks(execute=True):
        run = services.create_run(brief, {})
    assert run.steps.get(key="research").status == StepRun.Status.READY


# ---- Notifications and live status ----


def test_ready_step_is_announced_once(admin_client, brief, fake_llm):
    run = services.create_run(brief, {})
    execute_step(run.steps.get(key="research").pk)
    first = admin_client.get(reverse("wagtailadmin_home"))
    assert b"is ready for review" in first.content
    second = admin_client.get(reverse("wagtailadmin_home"))
    assert b"is ready for review" not in second.content


def test_status_endpoint_reports_activity(admin_client, brief):
    run = services.create_run(brief, {})
    data = admin_client.get(reverse("studio:run_status", args=[run.pk])).json()
    assert data["active"] is True and data["steps"][0] == {
        "key": "research",
        "status": "queued",
        "started_at": None,
    }


# ---- Text helpers and polite fetching ----


def test_cleanup_removes_hidden_characters():
    cleaned, report = textclean.clean("Safe​text here‮.\n\n\n\nEnd")
    assert cleaned == "Safetext here.\n\nEnd\n"
    assert report == {"invisible_removed": 2, "spaces_normalised": 1}


def test_split_metadata_without_section_returns_article():
    article, options = textclean.split_metadata("# Title\n\nBody")
    assert article == "# Title\n\nBody" and options == {}


@respx.mock
def test_fetch_respects_robots_and_skips_login_pages(settings):
    respx.get("https://site.example/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private/")
    )
    with webfetch._client() as client:
        robots = webfetch.robots_for("https://site.example/", client)
        blocked = webfetch.fetch_page("https://site.example/private/report", client, robots)
        login = webfetch.fetch_page("https://site.example/account/login", client, robots)
    assert blocked.method == "skipped" and "robots.txt" in blocked.reason
    assert login.method == "skipped"


def test_discover_articles_keeps_same_site_article_links():
    links = [
        "/blog/coshh-guide",
        "https://other.example/blog/x",
        "/tag/safety",
        "/about",
        "/blog/coshh-guide#top",
    ]
    assert webfetch.discover_articles("https://site.example/", links, 5) == [
        "https://site.example/blog/coshh-guide"
    ]


def test_metadata_options_from_draft_keep_users_choices(brief, fake_llm, admin_user):
    run = services.create_run(brief, {})
    own = MetadataOption.objects.create(run=run, kind="title", text="My title", source="edit", selected=True)
    for key in ("research", "outline"):
        execute_step(run.steps.get(key=key).pk)
        approve(run.steps.get(key=key), admin_user)
    execute_step(run.steps.get(key="draft").pk)
    own.refresh_from_db()
    assert own.selected
    assert not run.metadata_options.filter(kind="title", source="ai", selected=True).exists()


def test_empty_image_prompt_fails_instead_of_generating(brief, fake_llm, fake_images, monkeypatch):
    def empty_prompt(provider, model, messages, options):
        result = fake_llm(provider, model, messages, options)
        if "image prompt" in str(messages[-1]["content"]).lower():
            result.text = ""
        return result

    monkeypatch.setattr(executors, "generate", empty_prompt)
    step = _run_hero(brief)
    assert step.status == StepRun.Status.FAILED
    assert "empty image prompt" in step.error
    assert fake_images["generate"] == 0


def test_subject_too_far_left_gets_one_more_photo(brief, fake_llm, fake_images):
    from wagtail.images import get_image_model

    fake_images["too_far_left"] = 1
    step = _run_hero(brief)
    hero_metrics = step.latest_version.metrics["hero"]
    assert fake_images["generate"] == 2
    assert executors.PLACE_RIGHT in fake_images["prompts"][1]
    assert hero_metrics["branded"] is True
    assert any("second photo was generated" in flag for flag in hero_metrics["flags"])
    assert get_image_model().objects.filter(title__startswith="Hero photo").count() == 1


def test_second_photo_too_far_left_stops_and_explains(brief, fake_llm, fake_images):
    fake_images["too_far_left"] = 2
    step = _run_hero(brief)
    assert fake_images["generate"] == 2
    assert step.status == StepRun.Status.READY
    assert step.latest_version.metrics["hero"]["branded"] is False
