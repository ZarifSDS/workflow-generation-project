"""Stress tests for the generation pipeline and its state machine (no provider calls, nothing published live).

The bugs this file first documented as xfail were fixed on 2026-10-14; the tests now assert the fix.
"""

import json

import httpx
import pytest
import respx
from django.db import transaction
from django.urls import reverse

from apps.ai.types import GenerationResult, ImageResult, ProviderError
from apps.content.models import ArticlePage
from apps.quality import hero, house, review
from apps.studio import executors, prompting, serp, services, textclean, verify, webfetch
from apps.studio.models import ContentBrief, GenerationRun, MetadataOption, StepRun
from apps.studio.tasks import execute_step
from tests.test_permissions import _denied, _user

pytestmark = pytest.mark.django_db

_real_crawl_site = webfetch.crawl_site  # the respx test restores it under the no-network safety net

S = StepRun.Status
R = GenerationRun.Status

H1 = "SDS Retention Requirements: How Long to Keep Safety Data Sheets"
OSHA_URL = "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1020"

ARTICLE = f"""# {H1}

OSHA treats a safety data sheet as an exposure record. Keep each sheet for 30 years after the chemical leaves the site. By the end of this article, you'll know which records to keep and for how long.

## Key Takeaways

- Keep the current SDS for every hazardous chemical on site.
- Keep a record of the chemical identity for 30 years.
- Employers must not discard a sheet without a replacement record.

## How Long to Keep Safety Data Sheets

The OSHA records rule, 29 CFR 1910.1020, treats an SDS as an exposure record. Employers must keep it for 30 years. They may keep a list of the chemical identity instead of the sheet itself. See [the OSHA rule]({OSHA_URL}) for the text.

## Practical Policy

Keep the current sheet available on every shift. Archive old versions in one place. Name one person who owns the archive.

:::faq
### Do I need to keep an SDS after the chemical is gone?

An employer keeps a record of the chemical identity and where it was used for 30 years.
:::

## References

1. OSHA, 29 CFR 1910.1020, Access to employee exposure and medical records.
"""  # noqa: E501

EXCERPT = (
    "A plain guide to SDS retention: what OSHA requires, which records count, and how to keep them for "
    "30 years without a filing nightmare."
)
META = f"""
## Metadata options
### Meta Titles
- SDS Retention Requirements: The 30 Year Rule (45 characters)
- How Long to Keep Safety Data Sheets
- SDS Retention Rules for US Employers
### Meta Descriptions
- OSHA treats safety data sheets as exposure records. Learn the 30 year retention rule and what to keep when a chemical leaves your site.
- Keep safety data sheets for 30 years. A plain guide to the OSHA exposure records rule for employers.
### Slugs
- `sds-retention-requirements`
- `how-long-to-keep-sds`
### Tags
- SDS retention requirements, OSHA, exposure records
- safety data sheets, recordkeeping
### Excerpts
- {EXCERPT}
"""  # noqa: E501

MARKED_ARTICLE = (
    ARTICLE.replace(
        "Employers must keep it for 30 years.",
        "Employers must keep it for 30 years [VERIFY] [SRC: https://www.osha.gov/1910.1020].",
    )
    .replace(
        "## Practical Policy\n",
        "## Practical Policy\n\n[VISUAL: a timeline of the 30 year retention period]\n",
    )
    .replace(
        "## Key Takeaways\n",
        "[HERO: a tidy records room with labelled binders]\n\n## Key Takeaways\n",
    )
)

PIPELINE_KEYS = {
    "seo_blog": ["research", "outline", "draft", "review_edit", "cleanup", "hero_image", "publish"],
    "whitepaper": ["research", "outline", "draft", "review_edit", "cleanup", "hero_image", "publish"],
    "lead_magnet": ["research", "outline", "draft", "review_edit", "cleanup", "hero_image", "publish"],
    "outbound": [
        "site_crawl",
        "research",
        "outline",
        "draft",
        "review_edit",
        "cleanup",
        "hero_image",
        "publish",
    ],
}


# ---- Fakes ----


def prompt_kind(messages):
    """Which template a chat request came from, by phrases unique to each prompt's user section."""
    user = messages[-1]["content"]
    if isinstance(user, list):
        return "vision"
    checks = (
        ("Write the full article", "draft"),
        ("Build the site profile", "site_profile"),
        ("deslop scanners reported", "review_deslop"),
        ("fix these defect types", "review_clarity"),
        ("Lower it by syntactic unpacking", "review_wordlevel"),
        ("Localise this article", "localise"),
        ("Return the complete revised", "chat_apply"),
    )
    for phrase, kind in checks:
        if phrase in user:
            return kind
    if "image prompt" in user.lower():
        return "hero_prompt"
    return "other"


VISION = {
    "subject": [0.64, 0.1, 0.92, 1.0],
    "person_at_left_edge": False,
    "facing": "left",
    "readable_text": [],
    "safety_issues": [],
    "scene": "records room",
}


class Model:
    """A fake text model: answers per prompt kind; `answers[kind]` is a string or f(user_message)."""

    def __init__(self, article=ARTICLE, meta=META, **answers):
        self.calls, self.article, self.meta, self.answers = [], article, meta, answers

    def __call__(self, provider, model, messages, options):
        kind = prompt_kind(messages)
        self.calls.append((kind, provider, model, messages))
        user = messages[-1]["content"]
        if kind in self.answers:
            answer = self.answers[kind]
            text = answer(user) if callable(answer) else answer
        elif kind == "vision":
            text = json.dumps(VISION)
        elif kind == "draft":
            text = self.article + self.meta
        elif kind == "review_deslop":
            text = self.article + "\n\n## Deslop notes\n- None."
        elif kind == "review_clarity":
            text = self.article + "\n\n## Clarity edits\n- Intro: named the SDS."
        elif kind == "review_wordlevel":
            text = ""  # a tune that returns nothing is skipped, the text stays
        elif kind == "hero_prompt":
            text = "A tidy records room with labelled binders, soft daylight, no text."
        elif kind == "site_profile":
            text = (
                "## Site profile\n\n| Narrative mode | personal |\n\n"
                "## Recommendations for this guest post\n\n- Short."
            )
        elif kind == "localise":
            text = self.article.replace("OSHA", "HSE") + "\n\n## Localisation notes\n- OSHA became HSE."
        else:
            text = f"# Output from {model}\n\n## Notes\n\nResearch notes for {kind}."
        return GenerationResult(provider=provider, model=model, text=text, output_tokens=100, total_time=0.1)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Safety net: nothing in this module may reach a provider, a search engine or a site."""

    def refuse(what):
        def _refuse(*args, **kwargs):
            raise AssertionError(f"unexpected {what} call")

        return _refuse

    monkeypatch.setattr(executors, "generate", refuse("text model"))
    monkeypatch.setattr(executors, "generate_image", refuse("image model"))
    monkeypatch.setattr(webfetch, "crawl_site", refuse("site crawl"))
    monkeypatch.setattr(serp, "search", refuse("search"))
    monkeypatch.setattr(serp, "autocomplete", refuse("autocomplete"))


@pytest.fixture
def model(monkeypatch):
    fake = Model()
    monkeypatch.setattr(executors, "generate", fake)
    return fake


def _tiny_png():
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "teal").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def fake_images(monkeypatch):
    calls = {"generate": 0}

    def generate_image(provider, model, prompt, options):
        calls["generate"] += 1
        return ImageResult(provider=provider, model=model, data=_tiny_png(), mime_type="image/png")

    def brand(photo, markup, vision):
        fit = {"lines": 2, "size_px": 26.5, "scale_percent": 100, "ends_x": 300, "limit_x": 331}
        return hero.HeroResult(
            png=_tiny_png(), webp=b"webp", metrics={"headline": markup, "headline_fit": fit}
        )

    monkeypatch.setattr(executors, "generate_image", generate_image)
    monkeypatch.setattr(hero, "brand", brand)
    return calls


@pytest.fixture
def fake_crawl(monkeypatch):
    text = "word " * 400
    calls = []

    def crawl(home_url, *args, **kwargs):
        calls.append((home_url, kwargs))
        return [
            webfetch.FetchedPage(home_url, "direct", text, ["Intro"]),
            webfetch.FetchedPage(home_url + "blog/a", "reader", text, ["How to"]),
            webfetch.FetchedPage(home_url + "members/x", "skipped", reason="Requires login"),
        ]

    monkeypatch.setattr(webfetch, "crawl_site", crawl)
    return calls


def make_brief(user, content_type="seo_blog", **fields):
    values = dict(
        topic="How long to keep SDSs",
        pkeyword="SDS retention requirements",
        skeywords=["how long to keep safety data sheets"],
        wordcount=1200,
        fkgl=9,
        region="US",
        content_type=content_type,
        created_by=user,
    )
    if content_type == "outbound":
        values.update(
            site="Example Safety Blog", site_domain="https://blog.example.com/", narrative_mode="personal"
        )
    values.update(fields)
    return ContentBrief.objects.create(**values)


@pytest.fixture
def brief(admin_user):
    return make_brief(admin_user)


def config(content_type, gate, hero=True):
    """A wizard step_config with every gate on or off; `hero=False` switches the Hero image step off."""
    steps = {key: {"gate": gate} for key in PIPELINE_KEYS[content_type]}
    if not hero:
        steps["hero_image"]["enabled"] = False
    return steps


def drive(run, user=None, approve=True, until=None, limit=40):
    """Execute queued steps and approve ready ones until nothing is left (or `until` has run).
    Returns [(key, step status, run status)] after each execution."""
    trail = []
    for _ in range(limit):
        queued = run.steps.filter(status=S.QUEUED).order_by("order").first()
        if queued:
            execute_step(queued.pk)
            queued.refresh_from_db()
            run.refresh_from_db()
            trail.append((queued.key, queued.status, run.status))
            if queued.status == S.FAILED or queued.key == until:
                break
            continue
        ready = run.steps.filter(status=S.READY).order_by("order").first()
        if ready and approve:
            services.approve_step(ready, user)
            continue
        break
    run.refresh_from_db()
    return trail


def step(run, key):
    return run.steps.get(key=key)


def content(run, key):
    return step(run, key).latest_version.content


# ---- 1. Full runs per content type ----


@pytest.mark.parametrize("content_type", ["seo_blog", "outbound", "lead_magnet", "whitepaper"])
def test_full_run_with_every_gate_on(admin_user, model, fake_images, fake_crawl, content_type):
    brief = make_brief(admin_user, content_type)
    run = services.create_run(brief, config(content_type, True), user=admin_user)
    assert run.status == R.QUEUED
    keys = PIPELINE_KEYS[content_type]
    assert step(run, keys[0]).status == S.QUEUED
    assert all(step(run, key).status == S.PENDING for key in keys[1:])

    trail = drive(run, admin_user)
    assert trail == [(key, S.READY, R.NEEDS_REVIEW) for key in keys]
    assert run.status == R.DONE
    for key in keys:
        current = step(run, key)
        assert current.status == S.APPROVED and current.approved_by == admin_user, key
        assert current.latest_version.number == 1 and current.versions.count() == 1, key
    if content_type in ("seo_blog", "whitepaper"):
        assert step(run, "localise").status == S.SKIPPED and not step(run, "localise").enabled
    assert fake_images["generate"] == 1
    if content_type == "outbound":
        assert fake_crawl[0][0] == "https://blog.example.com/"
        # A guest post goes to the host as files: the last step exports, no sdsmanager.com page.
        assert ArticlePage.objects.count() == 0
        assert "Nothing was published on sdsmanager.com" in content(run, "publish")
        return
    assert ArticlePage.objects.count() == 1
    page = run.article_page
    assert page.live is False and page.workflow_in_progress
    assert page.current_workflow_state.workflow.name == "Moderators approval"
    assert page.title == H1 and page.slug == "sds-retention-requirements"
    assert "Moderators approval" in content(run, "publish")


@pytest.mark.parametrize("content_type", ["seo_blog", "outbound", "lead_magnet", "whitepaper"])
def test_full_run_with_every_gate_off_continues_automatically(
    admin_user, model, fake_images, fake_crawl, content_type
):
    brief = make_brief(admin_user, content_type)
    run = services.create_run(brief, config(content_type, False), user=admin_user)
    keys = PIPELINE_KEYS[content_type]

    trail = drive(run, approve=False)
    assert [(key, status) for key, status, _ in trail] == [(key, S.APPROVED) for key in keys]
    assert [run_status for _, _, run_status in trail] == [R.QUEUED] * (len(keys) - 1) + [R.DONE]
    assert not run.steps.filter(status__in=[S.READY, S.PENDING, S.QUEUED]).exists()
    for key in keys:
        current = step(run, key)
        assert current.approved_at is not None and current.approved_by is None, key
        assert current.latest_version.number == 1, key
    if content_type == "outbound":
        assert ArticlePage.objects.count() == 0  # exported, not published
        return
    assert ArticlePage.objects.count() == 1
    page = run.article_page
    assert page.live is False and page.workflow_in_progress
    assert page.search_description.startswith("OSHA treats safety data sheets")
    assert page.intro.startswith("A plain guide to SDS retention")


def test_run_is_running_while_the_model_works(brief, monkeypatch):
    seen = []

    def generate(provider, model, messages, options):
        seen.append(GenerationRun.objects.get(pk=run.pk).status)
        seen.append(StepRun.objects.get(run=run, key="research").status)
        return GenerationResult(provider=provider, model=model, text="# Research\n\nNotes.")

    monkeypatch.setattr(executors, "generate", generate)
    run = services.create_run(brief, {})
    execute_step(step(run, "research").pk)
    assert seen == [R.RUNNING, S.RUNNING]
    run.refresh_from_db()
    assert run.status == R.NEEDS_REVIEW


def test_failed_step_fails_the_run_and_retry_requeues(brief, monkeypatch):
    def broken(*args, **kwargs):
        raise ProviderError("server", "boom", 500)

    monkeypatch.setattr(executors, "generate", broken)
    run = services.create_run(brief, {})
    research = step(run, "research")
    execute_step(research.pk)
    run.refresh_from_db()
    research.refresh_from_db()
    assert research.status == S.FAILED and run.status == R.FAILED
    assert "temporary error" in research.error
    assert research.versions.count() == 0
    services.retry_step(research)
    research.refresh_from_db()
    run.refresh_from_db()
    assert research.status == S.QUEUED and research.error == "" and run.status == R.QUEUED


@pytest.mark.search_step
def test_search_step_without_results_but_with_suggestions_continues(brief, model, monkeypatch):
    def no_search(*args, **kwargs):
        raise serp.SerpError("No search provider is configured.")

    monkeypatch.setattr(serp, "search", no_search)
    monkeypatch.setattr(serp, "autocomplete", lambda *a, **k: ["sds retention requirements osha"])
    monkeypatch.setattr(serp, "read_pages", lambda *a, **k: [])
    run = services.create_run(brief, {})
    search = step(run, "search_results")
    execute_step(search.pk)
    search.refresh_from_db()
    assert search.status == S.APPROVED, search.error
    assert "No search provider" in search.latest_version.note
    assert step(run, "research").status == S.QUEUED


@pytest.mark.search_step
def test_search_step_with_nothing_at_all_fails_the_run(brief, model, monkeypatch):
    def no_search(*args, **kwargs):
        raise serp.SerpError("No search provider is configured.")

    monkeypatch.setattr(serp, "search", no_search)
    monkeypatch.setattr(serp, "autocomplete", lambda *a, **k: [])
    run = services.create_run(brief, {})
    search = step(run, "search_results")
    execute_step(search.pk)
    search.refresh_from_db()
    run.refresh_from_db()
    assert search.status == S.FAILED and "No search provider" in search.error
    assert run.status == R.FAILED and step(run, "research").status == S.PENDING


# ---- 2. Markers ----


@pytest.fixture
def marked_run(admin_user, monkeypatch):
    fake = Model(article=MARKED_ARTICLE)
    monkeypatch.setattr(executors, "generate", fake)
    brief = make_brief(admin_user)
    run = services.create_run(brief, config("seo_blog", False), user=admin_user)
    drive(run, approve=False)
    return run


@pytest.fixture
def marked_cleanup(admin_user, monkeypatch):
    """Final cleanup given an article that still has markers: one an editor wrote back in after review."""
    monkeypatch.setattr(executors, "generate", Model(article=MARKED_ARTICLE))
    run = services.create_run(make_brief(admin_user), config("seo_blog", False), user=admin_user)
    for key in ("search_results", "research", "outline", "draft", "review_edit"):
        current = step(run, key)
        if current.status == S.SKIPPED:
            continue
        services.add_version(current, MARKED_ARTICLE)
        current.status = S.APPROVED
        current.save()
    cleanup = step(run, "cleanup")
    cleanup.status = S.QUEUED
    cleanup.save()
    execute_step(cleanup.pk)
    run.refresh_from_db()
    return run


def test_no_marker_passes_review_and_the_sources_are_kept_apart(fake_images, marked_run):
    run = marked_run
    assert "[VERIFY]" in content(run, "draft")
    reviewed = step(run, "review_edit").latest_version
    for marker in ("[VERIFY", "[SRC:", "[VISUAL:", "## References"):
        assert marker not in reviewed.content, marker
    assert "[HERO: a tidy" in reviewed.content  # the hero cue is for Final cleanup, which removes it
    verification = reviewed.metrics["verification"]
    assert "https://www.osha.gov/1910.1020" in [url for _, url in verification["sources"]]
    assert verification["visual_cues"][0][1] == "a timeline of the 30 year retention period"
    assert "## Sources (kept out of the article)" in reviewed.note
    cleanup = step(run, "cleanup")
    assert cleanup.status == S.APPROVED and "[HERO:" not in cleanup.latest_version.content
    assert run.status == R.DONE  # nothing held the run


def test_markers_written_back_after_review_hold_cleanup_until_resolved(
    marked_cleanup, admin_user, fake_images
):
    run = marked_cleanup
    cleanup = step(run, "cleanup")
    assert cleanup.status == S.READY and run.status == R.NEEDS_REVIEW
    assert [m["kind"] for m in cleanup.latest_version.metrics["markers"]] == ["VERIFY", "SRC", "VISUAL"]
    assert "Publishing is blocked" in cleanup.latest_version.note
    with pytest.raises(ValueError, match="Resolve the working markers"):
        services.approve_step(cleanup, admin_user)

    stripped = services.strip_sources(cleanup, admin_user)
    assert stripped.number == 2 and stripped.source == "edit"
    assert "[SRC:" not in stripped.content and "30 years [VERIFY]." in stripped.content
    with pytest.raises(ValueError, match="no \\[SRC:\\] markers left"):
        services.strip_sources(cleanup, admin_user)
    with pytest.raises(ValueError, match="1 VERIFY, 1 VISUAL"):
        services.approve_step(cleanup, admin_user)

    resolved = stripped.content.replace(" [VERIFY]", "").replace(
        "[VISUAL: a timeline of the 30 year retention period]\n\n", ""
    )
    assert not house.find_markers(resolved)
    services.approve_step(cleanup, admin_user, edited_content=resolved, base_version=2)
    cleanup.refresh_from_db()
    assert cleanup.status == S.APPROVED and cleanup.latest_version.number == 3
    assert step(run, "hero_image").status == S.QUEUED

    trail = drive(run, approve=False)
    assert [(k, s) for k, s, _ in trail] == [("hero_image", S.APPROVED), ("publish", S.APPROVED)]
    assert run.status == R.DONE and ArticlePage.objects.count() == 1
    body = json.dumps(list(run.article_page.body.raw_data))
    assert "VERIFY" not in body and "VISUAL" not in body and "SRC:" not in body


def test_approving_cleanup_with_an_edit_that_adds_a_marker_is_refused(marked_cleanup, admin_user):
    cleanup = step(marked_cleanup, "cleanup")
    clean = house.strip_sources(cleanup.latest_version.content).replace(" [VERIFY]", "")
    clean = clean.replace("[VISUAL: a timeline of the 30 year retention period]\n\n", "")
    with pytest.raises(ValueError, match="1 VERIFY"):
        services.approve_step(cleanup, admin_user, edited_content=clean + "\nNew claim [VERIFY].\n")
    cleanup.refresh_from_db()
    assert cleanup.status == S.READY and cleanup.versions.count() == 1


def test_publish_with_markers_still_present_fails_cleanly(admin_user, brief):
    run = services.create_run(brief, {"hero_image": {"enabled": False}}, user=admin_user)
    for key in ("draft", "cleanup"):
        current = step(run, key)
        services.add_version(current, MARKED_ARTICLE)
        current.status = S.APPROVED
        current.save()
    publish = step(run, "publish")
    publish.status = S.QUEUED
    publish.save()
    execute_step(publish.pk)
    publish.refresh_from_db()
    run.refresh_from_db()
    assert publish.status == S.FAILED and run.status == R.FAILED
    assert "Resolve the working markers" in publish.error and "1 VERIFY, 1 SRC, 1 VISUAL" in publish.error
    assert ArticlePage.objects.count() == 0 and publish.versions.count() == 0


def test_review_rewrite_that_drops_a_marker_is_refused(admin_user, monkeypatch):
    fake = Model(
        article=MARKED_ARTICLE,
        review_deslop=MARKED_ARTICLE.replace(" [VERIFY]", "") + "\n\n## Deslop notes\n- Removed a marker.",
    )
    monkeypatch.setattr(executors, "generate", fake)
    run = services.create_run(make_brief(admin_user), config("seo_blog", False, hero=False), user=admin_user)
    drive(run, approve=False)
    reviewed = step(run, "review_edit").latest_version
    deslop = next(s for s in reviewed.metrics["review"]["substeps"] if s["number"] == 2)
    assert deslop["changed"] is False and "[VERIFY]" in deslop["summary"]
    # The refused rewrite left the draft's text; then the markers and References left the article.
    assert reviewed.content.strip() == verify.finalise(content(run, "draft"))[0].strip()


# ---- 3. Hostile model outputs ----


@pytest.mark.parametrize("text", ["", "   \n\t  \n"])
def test_empty_model_output_fails_the_step(brief, monkeypatch, text):
    fake = Model(other=text)
    monkeypatch.setattr(executors, "generate", fake)
    run = services.create_run(brief, {})
    research = step(run, "research")
    execute_step(research.pk)
    research.refresh_from_db()
    assert research.status == S.FAILED
    assert research.versions.count() == 0


def test_draft_without_any_heading_still_reaches_a_page(admin_user, model, fake_images):
    plain = (
        "OSHA treats a safety data sheet as an exposure record. Keep it for 30 years after the chemical "
        "leaves the site. Archive old sheets in one place, and name one person who owns the archive so "
        "nobody has to guess where the records are. "
    ) * 3  # a grade needs 100 words
    model.article = plain.strip()
    run = services.create_run(make_brief(admin_user), config("seo_blog", False), user=admin_user)
    trail = drive(run, approve=False)
    assert trail[-1] == ("publish", S.APPROVED, R.DONE)
    review_metrics = step(run, "review_edit").latest_version.metrics["review"]
    assert [row["heading"] for row in review_metrics["grades"]] == ["(intro)"]
    page = run.article_page
    assert page.title == "SDS Retention Requirements: The 30 Year Rule"  # no H1: the selected meta title
    assert page.intro == EXCERPT
    assert [block.block_type for block in page.body] == ["paragraph"]


def test_review_rewrite_dropping_all_headings_is_refused_and_text_unchanged(admin_user, model):
    model.answers["review_deslop"] = "Just one paragraph with no headings at all."
    model.answers["review_clarity"] = "Still no headings.\n\n## Clarity edits\n- none"
    run = services.create_run(make_brief(admin_user), config("seo_blog", False, hero=False), user=admin_user)
    drive(run, approve=False, until="cleanup")
    reviewed = step(run, "review_edit").latest_version
    substeps = {s["number"]: s for s in reviewed.metrics["review"]["substeps"]}
    assert substeps[2]["changed"] is False and "headings were dropped" in substeps[2]["summary"]
    assert substeps[3]["changed"] is False and "headings were dropped" in substeps[3]["summary"]
    assert reviewed.content.strip() == verify.finalise(ARTICLE)[0].strip()  # sources kept apart
    assert "## Review sequence" in reviewed.note


def test_crlf_draft_publishes_a_clean_page(admin_user, fake_images, monkeypatch):
    fake = Model(article=ARTICLE.replace("\n", "\r\n"), meta=META.replace("\n", "\r\n"))
    monkeypatch.setattr(executors, "generate", fake)
    run = services.create_run(make_brief(admin_user), config("seo_blog", False), user=admin_user)
    trail = drive(run, approve=False)
    assert trail[-1] == ("publish", S.APPROVED, R.DONE), trail
    assert run.metadata_options.get(kind="slug", selected=True).text == "sds-retention-requirements"
    assert "\r" not in content(run, "cleanup")
    page = run.article_page
    assert page.title == H1 and page.slug == "sds-retention-requirements"
    headings = [b.value["text"] for b in page.body if b.block_type == "heading"]
    assert headings[:2] == ["Key Takeaways", "How Long to Keep Safety Data Sheets"]
    assert "\r" not in json.dumps(list(page.body.raw_data))


def test_model_output_with_crlf_is_stored_with_lf(admin_user, monkeypatch):
    fake = Model(article=ARTICLE.replace("\n", "\r\n"), meta=META.replace("\n", "\r\n"))
    monkeypatch.setattr(executors, "generate", fake)
    run = services.create_run(make_brief(admin_user), config("seo_blog", False, hero=False), user=admin_user)
    drive(run, approve=False, until="draft")
    assert "\r" not in content(run, "draft")


def test_curly_quotes_dashes_and_emoji_are_fixed_by_cleanup(admin_user, model, fake_images):
    model.article = ARTICLE.replace(
        "Keep each sheet for 30 years after the chemical leaves the site.",
        "Keep each sheet for 30 years — “thirty”, not 10–20 — after the chemical leaves the site 🚀.",
    )
    run = services.create_run(make_brief(admin_user), config("seo_blog", False), user=admin_user)
    drive(run, approve=False)
    cleaned = content(run, "cleanup")
    assert '"thirty"' in cleaned and "10-20" in cleaned and "🚀" not in cleaned
    assert "—" not in cleaned and "–" not in cleaned and "“" not in cleaned
    note = step(run, "cleanup").latest_version.note
    assert "House style:" in note and "dashes" in note and "emoji" in note and "curly quotes" in note
    assert run.status == R.DONE


def test_200kb_output_is_saved_and_cleaned(admin_user, model, fake_images):
    paragraph = "Keep the current safety data sheet on every shift. Archive old versions in one place. "
    big = ARTICLE.replace("## References", "## Long Section\n\n" + paragraph * 2400 + "\n\n## References")
    assert len(big.encode()) > 200_000
    model.article = big
    run = services.create_run(make_brief(admin_user), config("seo_blog", False), user=admin_user)
    trail = drive(run, approve=False, until="cleanup")
    assert [(k, s) for k, s, _ in trail] == [
        ("research", S.APPROVED),
        ("outline", S.APPROVED),
        ("draft", S.APPROVED),
        ("review_edit", S.APPROVED),
        ("cleanup", S.APPROVED),
    ]
    assert len(content(run, "draft")) > 200_000
    assert len(content(run, "cleanup")) > 200_000
    assert step(run, "draft").latest_version.metrics.get("metrics_error") is None


def test_draft_without_metadata_section_is_noted_and_publishes_from_the_h1(admin_user, model, fake_images):
    model.meta = ""
    run = services.create_run(make_brief(admin_user), config("seo_blog", False), user=admin_user)
    drive(run, approve=False)
    draft = step(run, "draft")
    assert "didn't return title and meta options" in draft.latest_version.note
    assert not run.metadata_options.exists()
    assert run.status == R.DONE
    page = run.article_page
    assert page.title == H1 and page.seo_title == "" and page.search_description == ""
    assert page.slug == "sds-retention-requirements-how-long-to-keep-safety-data-sheets"
    assert "No meta description is selected" in step(run, "publish").latest_version.note
    draft_page = page.get_latest_revision_as_object()
    assert set(draft_page.tags.names()) == {
        "SDS retention requirements",
        "how long to keep safety data sheets",
    }


def test_seven_metadata_options_per_kind_are_capped_at_five(admin_user, model):
    lines = []
    for heading, prefix in (
        ("Meta Titles", "Title option"),
        ("Meta Descriptions", "Description option"),
        ("Slugs", "slug-option"),
        ("Tags", "tag option"),
        ("Excerpts", "Excerpt option"),
    ):
        lines.append(f"### {heading}")
        lines += [f"- {prefix} {n}" for n in range(1, 8)]
    model.meta = "\n## Metadata options\n" + "\n".join(lines) + "\n"
    run = services.create_run(make_brief(admin_user), config("seo_blog", False, hero=False), user=admin_user)
    drive(run, approve=False, until="draft")
    for kind in ("title", "meta", "slug", "tags", "excerpt"):
        options = list(run.metadata_options.filter(kind=kind).order_by("created_at", "pk"))
        assert len(options) == 5, kind
        assert [o.selected for o in options] == [True, False, False, False, False], kind
    assert run.metadata_options.get(kind="title", selected=True).text == "Title option 1"


def test_metadata_section_with_malformed_lists_yields_no_options(admin_user, model):
    model.meta = (
        "\n## Metadata options\n\nTitle: SDS Retention Rules\n"
        "Meta: Keep them for 30 years.\nSlug sds-retention\n"
    )
    run = services.create_run(make_brief(admin_user), config("seo_blog", False, hero=False), user=admin_user)
    drive(run, approve=False, until="draft")
    draft = step(run, "draft")
    assert not run.metadata_options.exists()
    assert "didn't return title and meta options" in draft.latest_version.note
    assert "Metadata options" not in draft.latest_version.content
    assert draft.latest_version.content.strip().endswith("medical records.")


def test_split_metadata_handles_quotes_counts_and_numbered_lists():
    article, options = textclean.split_metadata(
        '# T\n\nBody.\n\n## metadata options\n### Meta titles\n1. "Quoted title" (52 chars)\n2) `Second`\n'
        "### Tags\n* a, b\n### Something else\n- ignored\n"
    )
    assert article == "# T\n\nBody."
    assert options == {"title": ["Quoted title", "Second"], "tags": ["a, b"]}


def test_code_fenced_draft_is_unwrapped(admin_user, model):
    model.answers["draft"] = "```markdown\n" + ARTICLE + META + "```\n"
    run = services.create_run(make_brief(admin_user), config("seo_blog", False, hero=False), user=admin_user)
    drive(run, approve=False, until="draft")
    assert "```" not in content(run, "draft")


# ---- 4. State machine edge cases ----


@pytest.fixture
def ready_run(admin_user, brief):
    run = services.create_run(brief, {}, user=admin_user)
    research = step(run, "research")
    services.add_version(research, "# Research\n\n## Notes\n\nText.", provider="ollama", model="m")
    research.status = S.READY
    research.save()
    services.refresh_run_status(run)
    return run


def test_approve_twice_is_refused_and_queues_the_next_step_once(ready_run, admin_user):
    research = step(ready_run, "research")
    services.approve_step(research, admin_user)
    outline = step(ready_run, "outline")
    queued_at = outline.queued_at
    assert outline.status == S.QUEUED and queued_at is not None
    with pytest.raises(ValueError, match="ready for review"):
        services.approve_step(research, admin_user)
    outline.refresh_from_db()
    assert outline.queued_at == queued_at


def test_approve_with_identical_edit_adds_no_version(ready_run, admin_user):
    research = step(ready_run, "research")
    services.approve_step(research, admin_user, edited_content="# Research\r\n\r\n## Notes\r\n\r\nText.\n")
    research.refresh_from_db()
    assert research.status == S.APPROVED and research.versions.count() == 1


def test_approve_with_an_empty_edit_is_refused(ready_run, admin_user):
    research = step(ready_run, "research")
    with pytest.raises(ValueError):
        services.approve_step(research, admin_user, edited_content="   \n")
    research.refresh_from_db()
    assert research.status == S.READY and research.versions.count() == 1


def test_execute_step_twice_runs_the_model_once(brief, model):
    run = services.create_run(brief, config("seo_blog", False), user=None)
    research = step(run, "research")
    execute_step(research.pk)
    execute_step(research.pk)
    assert len(model.calls) == 1
    research.refresh_from_db()
    assert research.status == S.APPROVED and research.versions.count() == 1
    assert step(run, "outline").status == S.QUEUED


def test_execute_step_on_a_pending_or_ready_step_is_a_no_op(ready_run, model):
    research, outline = step(ready_run, "research"), step(ready_run, "outline")
    execute_step(outline.pk)  # pending: the research isn't approved
    execute_step(research.pk)  # ready: waiting for review
    assert model.calls == []
    outline.refresh_from_db()
    research.refresh_from_db()
    assert outline.status == S.PENDING and research.status == S.READY
    assert research.versions.count() == 1


def test_recover_step_only_on_a_running_step(ready_run, admin_user):
    research = step(ready_run, "research")
    with pytest.raises(ValueError, match="Only a running step"):
        services.recover_step(research, admin_user)
    research.status = S.RUNNING
    research.save()
    services.refresh_run_status(ready_run)
    assert ready_run.status == R.RUNNING
    services.recover_step(research, admin_user, reason="")
    research.refresh_from_db()
    ready_run.refresh_from_db()
    assert research.status == S.FAILED and "Marked as failed by admin" in research.error
    assert research.finished_at is not None and ready_run.status == R.FAILED
    services.retry_step(research)
    research.refresh_from_db()
    assert research.status == S.QUEUED and research.error == ""


def test_reject_then_reopen_then_approve(ready_run, admin_user):
    run = ready_run
    research = step(run, "research")
    services.reject_run(run, admin_user, "Wrong angle.")
    research.refresh_from_db()
    assert research.status == S.REJECTED and run.status == R.REJECTED and run.reject_reason == "Wrong angle."
    assert services.review_count() == 0
    with pytest.raises(ValueError, match="ready for review"):
        services.approve_step(research, admin_user)
    assert services.refresh_run_status(run).status == R.REJECTED  # a rejected run stays rejected

    assert services.reopen_run(run) == "Wrong angle."
    with pytest.raises(ValueError, match="Only a rejected run"):
        services.reopen_run(run)
    research.refresh_from_db()
    assert research.status == S.READY and run.status == R.NEEDS_REVIEW and run.reject_reason == ""
    assert services.review_count() == 1
    services.approve_step(research, admin_user)
    assert step(run, "outline").status == S.QUEUED
    run.refresh_from_db()
    assert run.status == R.QUEUED


def test_regenerate_on_a_ready_step_requeues_with_the_chosen_model(ready_run):
    research = step(ready_run, "research")
    services.request_regenerate(research, "ollama_cloud::gpt-oss:120b", "Shorter.")
    research.refresh_from_db()
    assert research.status == S.QUEUED and research.regenerate_note == "Shorter."
    assert (research.provider, research.model) == ("ollama_cloud", "gpt-oss:120b")
    assert research.versions.count() == 1  # the old version stays until the new one is saved


def test_regenerate_on_a_running_step_is_refused(ready_run):
    research = step(ready_run, "research")
    research.status = S.RUNNING
    research.save()
    with pytest.raises(ValueError):
        services.request_regenerate(research, "ollama_cloud::gpt-oss:120b")
    research.refresh_from_db()
    assert research.status == S.RUNNING


def test_regenerate_on_an_approved_step_is_refused(ready_run, admin_user, model):
    research = step(ready_run, "research")
    services.approve_step(research, admin_user)
    with pytest.raises(ValueError):
        services.request_regenerate(research, "ollama_cloud::gpt-oss:120b")
    research.refresh_from_db()
    assert research.status == S.APPROVED


def test_rerun_only_for_model_less_steps_waiting_for_review(ready_run):
    with pytest.raises(ValueError, match="without a model"):
        services.rerun_step(step(ready_run, "research"))
    cleanup = step(ready_run, "cleanup")
    with pytest.raises(ValueError, match="without a model"):
        services.rerun_step(cleanup)  # pending, not ready
    services.add_version(cleanup, ARTICLE)
    cleanup.status = S.READY
    cleanup.save()
    services.rerun_step(cleanup)
    cleanup.refresh_from_db()
    assert cleanup.status == S.QUEUED and cleanup.versions.count() == 1


def test_pruned_versions_do_not_break_the_base_version_check(ready_run, admin_user):
    research = step(ready_run, "research")
    for n in range(5):
        services.add_version(research, f"# Research v{n + 2}\n\nText.")
    assert list(research.versions.values_list("number", flat=True)) == [1, 4, 5, 6]
    with pytest.raises(ValueError, match="Version 6 was saved after you opened version 1"):
        services.save_edit(research, admin_user, "# Mine", base_version=1)
    with pytest.raises(ValueError, match="Version 6 was saved after you opened version 3"):
        services.save_edit(research, admin_user, "# Mine", base_version=3)  # a pruned version
    with pytest.raises(ValueError, match="doesn't say which version"):
        services.save_edit(research, admin_user, "# Mine", base_version="abc")
    saved = services.save_edit(research, admin_user, "# Mine", base_version=6)
    assert saved.number == 7
    assert list(research.versions.values_list("number", flat=True)) == [1, 5, 6, 7]


# ---- 5. review.accept_rewrite and protected_ok ----


@pytest.mark.parametrize(
    "before, after, fragment",
    [
        ("Keep the sheet for 30 years.", "Keep the sheet for three decades.", "30 years"),
        (f"See [the rule]({OSHA_URL}).", "See the rule.", OSHA_URL),
        ("Employers must not discard it.", "Employers must discard it.", "negation"),
        ("OSHA treats it as a record.", "The agency treats it as a record.", "OSHA"),
        ("Keep it under 29 CFR 1910.1020.", "Keep it under the records rule.", "1910.1020"),
    ],
)
def test_rewrites_that_drop_protected_facts_are_refused(before, after, fragment):
    ok, reason = review.protected_ok(before, after)
    assert not ok and fragment in reason


def test_unfolding_not_x_but_y_is_accepted():
    ok, _ = review.protected_ok("An SDS is not just a form but a record.", "An SDS is a record.")
    assert ok
    ok, _ = review.protected_ok("It is not only a form, but a record.", "It is a record.")
    assert ok


def test_an_unrelated_unfoldable_negation_does_not_license_dropping_another():
    before = "An SDS is not just a form but a record. Employers must not discard it."
    after = "An SDS is not just a form but a record. Employers must discard it."
    ok, reason = review.protected_ok(before, after)
    assert not ok and "negation" in reason


def test_accept_rewrite_rejects_empty_shrunken_and_headingless_output():
    before = "## A\n\nOne two three four five six seven eight nine ten.\n\n## B\n\nMore words here."
    assert review.accept_rewrite(before, "") == (False, "empty output")
    assert review.accept_rewrite(before, "## A\n\nOne two.") == (False, "headings were dropped")
    assert review.accept_rewrite(before, "## A\n\nOne.\n\n## B\n\nTwo.") == (
        False,
        "too much text was removed",
    )
    assert review.accept_rewrite(before, before + "\n\n## C\n\nAn added section is fine.")[0]


# Each body three times over: a grade needs 100 words (readability.MIN_WORDS).
LONG_SECTION = "## Why Records Matter\n\n" + " ".join(
    [
        "Employers that discontinue a hazardous chemical may discard its safety data sheet only when they "
        "maintain a record of the chemical identity and the period of use for at least 30 years under the "
        "OSHA standard, because the agency considers the information an exposure record."
    ]
    * 3
)
CHOPPY = "## Why Records Matter\n\n" + " ".join(
    [
        "Employers may stop using a chemical. They may discard its safety data sheet. "
        "They must keep a record. The record names the chemical identity. It gives the period of use. "
        "Keep it for at least 30 years. The OSHA standard requires this. "
        "The agency calls it an exposure record."
    ]
    * 3
)
# Sentence lengths 13, 23, 1 and 13 words: three length bands, so the rewrite isn't "flat".
VARIED = "## Why Records Matter\n\n" + " ".join(
    [
        "Employers that stop using a hazardous chemical may discard its safety data sheet. They must keep a "
        "record of the chemical identity and the period of use for at least 30 years under the OSHA "
        "standard. Why? The agency treats that information as an exposure record for the people involved."
    ]
    * 3
)


def test_tune_refuses_a_big_drop_that_leaves_sentences_flat():
    before = review.grade(LONG_SECTION)
    after = review.grade(CHOPPY)
    assert before - after > review.MAX_GRADE_JUMP and review._flatness(CHOPPY) >= review.FLAT_RATIO
    with pytest.raises(ValueError, match="choppy"):
        review.tune_unit(LONG_SECTION + "\n", 1, 9, "US", lambda name, ctx: CHOPPY)


def test_tune_accepts_a_big_drop_with_varied_sentences():
    text, before, after = review.tune_unit(LONG_SECTION + "\n", 1, 9, "US", lambda name, ctx: VARIED)
    assert after < before and "Why?" in text and text.startswith("## Why Records Matter")


def test_tune_refuses_a_rewrite_that_does_not_lower_the_grade():
    with pytest.raises(ValueError, match="didn't lower the grade"):
        review.tune_unit(LONG_SECTION + "\n", 1, 9, "US", lambda name, ctx: ctx["section"])


# ---- 6. Metadata ----


def _approved_article(run, article=ARTICLE):
    for key in ("draft", "cleanup"):
        current = step(run, key)
        services.add_version(current, article)
        current.status = S.APPROVED
        current.save()


def _publish(run):
    publish = step(run, "publish")
    publish.status = S.QUEUED
    publish.save()
    execute_step(publish.pk)
    publish.refresh_from_db()
    return publish


def _options(run):
    created = {}
    for kind, texts in (
        ("title", ["First Title", "SDS Retention: The Chosen Title"]),
        ("meta", ["First description.", "The chosen meta description."]),
        ("slug", ["`first-slug`", "`chosen-slug`"]),
        ("tags", ["first, tags", "SDS retention, OSHA, exposure records"]),
        ("excerpt", ["First excerpt.", "The chosen excerpt for the intro."]),
    ):
        created[kind] = [
            MetadataOption.objects.create(run=run, kind=kind, text=text, selected=index == 0)
            for index, text in enumerate(texts)
        ]
    return created


def test_publish_uses_the_selected_metadata(admin_user, brief):
    run = services.create_run(brief, {"hero_image": {"enabled": False}}, user=admin_user)
    _approved_article(run)
    created = _options(run)
    services.set_metadata_selection(run, {created[kind][1].pk for kind in created})
    assert [o.selected for o in run.metadata_options.order_by("kind", "pk")] == [False, True] * 5
    publish = _publish(run)
    assert publish.status == S.READY, publish.error
    page = run.article_page
    assert page.title == H1 and page.seo_title == "SDS Retention: The Chosen Title"
    assert page.search_description == "The chosen meta description."
    assert page.slug == "chosen-slug" and page.intro == "The chosen excerpt for the intro."
    draft_page = page.get_latest_revision_as_object()
    assert set(draft_page.tags.names()) == {"SDS retention", "OSHA", "exposure records"}
    from taggit.models import Tag

    assert Tag.objects.filter(name__in=["SDS retention", "OSHA", "exposure records"]).count() == 3


def test_publish_keeps_the_opening_paragraph_when_an_excerpt_is_selected(admin_user, brief):
    run = services.create_run(brief, {"hero_image": {"enabled": False}}, user=admin_user)
    _approved_article(run)
    MetadataOption.objects.create(run=run, kind="excerpt", text="A teaser for the listing.", selected=True)
    assert _publish(run).status == S.READY
    page = run.article_page
    assert page.intro == "A teaser for the listing."
    body = json.dumps(list(page.body.raw_data))
    assert "By the end of this article" in body


def test_own_metadata_and_limits(brief):
    run = services.create_run(brief, {})
    with pytest.raises(ValueError, match="Type an option"):
        services.add_own_metadata(run, "title", "   \n ")
    option = services.add_own_metadata(run, "title", "  A   title\nwith   gaps  ")
    assert option.text == "A title with gaps" and option.selected and option.source == "edit"
    assert not option.too_long and option.limit == 60
    with pytest.raises(ValueError, match="within 60 characters \\(this one has 61\\)"):
        services.add_own_metadata(run, "title", "x" * 61)
    assert MetadataOption(kind="excerpt", text="y" * 401).too_long
    assert not MetadataOption(kind="meta", text="z" * 160).too_long


def test_own_metadata_gets_house_mechanics_and_replaces_a_single_choice(brief):
    run = services.create_run(brief, {})
    title = services.add_own_metadata(run, "title", "SDS Retention – What to Keep")
    assert title.text == "SDS Retention: What to Keep"
    slug = services.add_own_metadata(run, "slug", "  SDS Retention: Rules & Exposure Records ")
    assert slug.text == "sds-retention-rules-exposure-records"
    first = services.add_own_metadata(run, "meta", "First description.")
    second = services.add_own_metadata(run, "meta", "Second description.")
    first.refresh_from_db()
    assert second.selected and not first.selected  # one meta description selected, not two
    another = services.add_own_metadata(run, "title", "Another Title")
    title.refresh_from_db()
    assert title.selected and another.selected  # extra titles stay as A/B options


def test_selecting_an_over_limit_option_is_refused(brief):
    run = services.create_run(brief, {})
    long_meta = MetadataOption.objects.create(run=run, kind="meta", text="z" * 170)
    short = MetadataOption.objects.create(run=run, kind="meta", text="Fine.", selected=True)
    with pytest.raises(ValueError, match="170 of 160 characters"):
        services.set_metadata_selection(run, {long_meta.pk})
    short.refresh_from_db()
    assert short.selected  # nothing changed


def test_metadata_screen_previews_the_real_path_and_explains_a_refusal(admin_client, brief):
    run = services.create_run(brief, {})
    MetadataOption.objects.create(run=run, kind="slug", text="sds-retention", selected=True)
    long_meta = MetadataOption.objects.create(run=run, kind="meta", text="z" * 170)
    url = reverse("studio:metadata", args=[run.pk])
    page = admin_client.get(url).content.decode()
    assert f"sdsmanager.com › {brief.region.lower()} › sds-management-articles › sds-retention" in page
    response = admin_client.post(url, {"action": "save", "choice_meta": str(long_meta.pk)}, follow=True)
    assert "170 of 160 characters" in response.content.decode()
    brief.content_type, brief.site_domain = "outbound", "https://www.example-safety.com/blog/"
    brief.save()
    assert "example-safety.com › sds-retention" in admin_client.get(url).content.decode()


def test_own_metadata_longer_than_the_column_is_refused_cleanly(brief):
    run = services.create_run(brief, {})
    with transaction.atomic(), pytest.raises(ValueError):
        services.add_own_metadata(run, "excerpt", "word " * 120)


def test_same_slug_in_two_runs_gets_a_suffix(admin_user, brief):
    pages = []
    for _ in range(2):
        run = services.create_run(brief, {"hero_image": {"enabled": False}}, user=admin_user)
        _approved_article(run)
        MetadataOption.objects.create(run=run, kind="slug", text="sds-retention", selected=True)
        assert _publish(run).status == S.READY
        pages.append(run.article_page)
    assert [page.slug for page in pages] == ["sds-retention", "sds-retention-2"]
    assert ArticlePage.objects.count() == 2 and not ArticlePage.objects.filter(live=True).exists()


# ---- 7. Permissions smoke ----


@pytest.fixture
def cleanup_ready(admin_user, brief):
    run = services.create_run(brief, {}, user=admin_user)
    for key in ("draft", "review_edit"):
        current = step(run, key)
        services.add_version(current, ARTICLE)
        current.status = S.APPROVED
        current.save()
    cleanup = step(run, "cleanup")
    services.add_version(cleanup, ARTICLE)
    cleanup.status = S.READY
    cleanup.save()
    services.refresh_run_status(run)
    return run


def test_writers_cannot_approve_cleanup_but_editors_can(client, cleanup_ready):
    run = cleanup_ready
    url = reverse("studio:run", args=[run.pk])
    client.force_login(_user("writer", "Writers"))
    response = client.post(url, {"step": "cleanup", "action": "approve"})
    assert response.status_code == 302
    assert "for editors." in client.get(response.url).text
    assert step(run, "cleanup").status == S.READY
    client.logout()

    client.force_login(_user("editor", "Editors"))
    client.post(url, {"step": "cleanup", "action": "approve"})
    cleanup = step(run, "cleanup")
    assert cleanup.status == S.APPROVED and cleanup.approved_by.username == "editor"
    assert step(run, "hero_image").status == S.QUEUED


def test_anonymous_cannot_act_and_is_sent_to_login(client, cleanup_ready):
    run = cleanup_ready
    url = reverse("studio:run", args=[run.pk])
    response = client.post(url, {"step": "cleanup", "action": "approve"})
    assert response.status_code == 302 and "/admin/login/" in response["Location"]
    assert step(run, "cleanup").status == S.READY
    assert client.get(reverse("studio:metadata", args=[run.pk])).status_code == 302


def test_moderators_cannot_change_metadata(client, cleanup_ready):
    run = cleanup_ready
    client.force_login(_user("moderator", "Moderators"))
    response = client.post(
        reverse("studio:metadata", args=[run.pk]), {"action": "add", "kind": "title", "own_title": "Mine"}
    )
    assert _denied(response)
    assert not run.metadata_options.exists()


# ---- 8. Outbound ----


def test_site_crawl_needs_two_readable_pages(admin_user, model, monkeypatch):
    brief = make_brief(admin_user, "outbound")
    monkeypatch.setattr(
        webfetch,
        "crawl_site",
        lambda *a, **k: [
            webfetch.FetchedPage("https://blog.example.com/", "direct", "word " * 300, ["Intro"]),
            webfetch.FetchedPage("https://blog.example.com/blog/a", "skipped", reason="Could not be read"),
        ],
    )
    run = services.create_run(brief, {})
    crawl = step(run, "site_crawl")
    execute_step(crawl.pk)
    crawl.refresh_from_db()
    run.refresh_from_db()
    assert crawl.status == S.FAILED and "enough public pages" in crawl.error
    assert model.calls == [] and run.status == R.FAILED
    assert step(run, "research").status == S.PENDING


def test_site_crawl_without_a_site_url_fails_before_fetching(admin_user, model, fake_crawl):
    brief = make_brief(admin_user, "outbound", site_domain="")
    run = services.create_run(brief, {})
    crawl = step(run, "site_crawl")
    execute_step(crawl.pk)
    crawl.refresh_from_db()
    assert crawl.status == S.FAILED and "target site's URL" in crawl.error
    assert fake_crawl == []


def test_site_crawl_output_has_the_pages_table_and_feeds_the_profile(admin_user, model, fake_crawl, settings):
    brief = make_brief(admin_user, "outbound")
    run = services.create_run(brief, {})
    crawl = step(run, "site_crawl")
    execute_step(crawl.pk)
    crawl.refresh_from_db()
    assert crawl.status == S.READY, crawl.error
    home_url, kwargs = fake_crawl[0]
    assert home_url == "https://blog.example.com/" and kwargs["max_pages"] == settings.STUDIO_CRAWL_MAX_PAGES
    text = crawl.latest_version.content
    table = text[text.index("## Pages read") :]
    rows = [line for line in table.splitlines() if line.startswith("| https://")]
    assert len(rows) == 3
    assert "| https://blog.example.com/ | Direct | 400 |" in rows[0]
    assert "| https://blog.example.com/blog/a | Reader service | 400 |" in rows[1]
    assert "| Skipped | – | – | Requires login |" in rows[2]
    profile_prompt = model.calls[0][3][-1]["content"]
    assert "Build the site profile for **Example Safety Blog** (https://blog.example.com/)" in profile_prompt
    assert "Words: 400" in profile_prompt and "Headings: How to" in profile_prompt


def test_narrative_mode_and_site_profile_flow_into_later_prompts(admin_user, model, fake_crawl):
    brief = make_brief(admin_user, "outbound")
    run = services.create_run(brief, config("outbound", False), user=admin_user)
    drive(run, approve=False, until="draft")
    kinds = [call[0] for call in model.calls]
    assert kinds[:4] == ["site_profile", "other", "other", "draft"]
    draft_prompt = model.calls[3][3][-1]["content"]
    assert "| Narrative mode | Personal |" in draft_prompt
    assert "| Target site | Example Safety Blog |" in draft_prompt
    assert (
        "Approved site profile of the target site:" in draft_prompt
        and "| Narrative mode | personal |" in draft_prompt
    )
    assert "| Call to action |" not in draft_prompt

    brief.narrative_mode = ""
    brief.save()
    assert "| Narrative mode | from the site profile |" in prompting.brief_table(brief)


HOME_HTML = (
    "<html><body><nav><a href='/account/login'>Login</a></nav><main>"
    "<a href='/blog/coshh-guide'>COSHH guide</a> <a href='/blog/sds-basics'>SDS basics</a>"
    "<a href='https://other.example/blog/x'>Elsewhere</a>"
    + "<p>"
    + "Plain words about workplace safety for small firms. " * 60
    + "</p></main></body></html>"
)
ARTICLE_HTML = (
    "<html><body><article><h2>What the rule says</h2><p>"
    + "I keep my sheets in one binder and check them every month. " * 60
    + "</p></article></body></html>"
)


@respx.mock
def test_site_crawl_over_http_reads_home_and_discovered_articles(admin_user, model, settings, monkeypatch):
    monkeypatch.setattr(webfetch, "crawl_site", _real_crawl_site)
    settings.STUDIO_CRAWL_MAX_PAGES = 3
    headers = {"content-type": "text/html; charset=utf-8"}
    respx.get("https://blog.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private/")
    )
    respx.get("https://blog.example.com/").mock(
        return_value=httpx.Response(200, text=HOME_HTML, headers=headers)
    )
    respx.get("https://blog.example.com/blog/coshh-guide").mock(
        return_value=httpx.Response(200, text=ARTICLE_HTML, headers=headers)
    )
    respx.get("https://blog.example.com/blog/sds-basics").mock(return_value=httpx.Response(403))
    reader = respx.get("https://r.jina.ai/https://blog.example.com/blog/sds-basics").mock(
        return_value=httpx.Response(200, text="## Basics\n\n" + "Short plain words. " * 150)
    )
    brief = make_brief(admin_user, "outbound")
    run = services.create_run(brief, {})
    crawl = step(run, "site_crawl")
    execute_step(crawl.pk)
    crawl.refresh_from_db()
    assert crawl.status == S.READY, crawl.error
    text = crawl.latest_version.content
    assert "| https://blog.example.com/ | Direct |" in text
    assert "| https://blog.example.com/blog/coshh-guide | Direct |" in text
    assert "| https://blog.example.com/blog/sds-basics | Reader service |" in text
    assert reader.called and "account/login" not in text
    assert "first-person words: 120" in model.calls[0][3][-1]["content"]
