"""M4: step execution with fake providers (no real API calls)."""

import httpx
import pytest
import respx
from django.urls import reverse

from apps.ai.types import GenerationResult, ImageResult, ProviderError
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
        if "Write the full piece" in user:
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


def test_hero_image_is_saved_to_wagtail_images(brief, fake_llm, monkeypatch, admin_user):
    monkeypatch.setattr(
        executors,
        "generate_image",
        lambda provider, model, prompt, options: ImageResult(
            provider=provider, model=model, data=_tiny_png(), mime_type="image/png"
        ),
    )
    run = services.create_run(brief, {})
    step = run.steps.get(key="hero_image")
    step.status = StepRun.Status.QUEUED
    step.save()
    execute_step(step.pk)
    step.refresh_from_db()
    assert step.status == StepRun.Status.READY, step.error
    assert step.latest_version.image is not None
    assert "Image prompt" in step.latest_version.note


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
