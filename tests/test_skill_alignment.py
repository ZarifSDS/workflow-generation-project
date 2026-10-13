"""The pipeline follows the ehs-seo-blog-optimized workflow: article-only grades, prompts per Steps 1-2,
metadata with tags and excerpt, the Publish gate, search providers' own settings page and logo branding."""

import io

import httpx
import pytest
from django.urls import reverse
from PIL import Image

from apps.quality import hero
from apps.studio import executors, houseref, prompting, serp, services, textclean
from apps.studio.models import ContentBrief, StepRun

pytestmark = pytest.mark.django_db

ARTICLE = (
    "# How Long to Keep Safety Data Sheets\n\nYou keep each SDS while the chemical is on site. "
    "By the end of this "
    "article, you'll know the rule.\n\n## Key Takeaways\n\n- OSHA treats an SDS as an exposure record.\n\n"
    "## What OSHA Requires\n\n"
    + "Employers keep a record of each chemical for 30 years. You can keep it digitally. " * 6
    + "\n\n## References\n\n1. OSHA 1910.1020.\n"
)


@pytest.fixture
def brief(admin_user):
    return ContentBrief.objects.create(
        topic="How long to keep safety data sheets",
        pkeyword="sds retention requirements",
        skeywords=["how long to keep safety data sheets"],
        content_type="seo_blog",
        region="US",
        fkgl=8,
        created_by=admin_user,
    )


def _ready(step, text):
    services.add_version(step, text, provider="ollama_cloud", model="gpt-oss:120b")
    step.status = StepRun.Status.READY
    step.save()
    return step


# ---- Grades only on the article ----


def test_outline_and_research_have_no_grade_table(admin_client, brief):
    run = services.create_run(brief, {})
    _ready(run.steps.get(key="outline"), "## Search Intent\n\nPlanning text " * 20)
    html = admin_client.get(reverse("studio:run", args=[run.pk]) + "?step=outline").content.decode()
    assert 'id="grades-head"' not in html and 'value="tune"' not in html
    assert "Ask for suggestions" in html  # the chat stays on planning steps


def test_draft_shows_whole_article_and_section_grades(admin_client, brief):
    run = services.create_run(brief, {})
    _ready(run.steps.get(key="draft"), ARTICLE)
    html = admin_client.get(reverse("studio:run", args=[run.pk]) + "?step=draft").content.decode()
    assert "Whole article: FKGL" in html and "Sentence lengths" in html
    assert "not graded" in html  # the References section


# ---- Prompts follow the skill ----


def test_research_outline_and_draft_prompts_carry_the_skill_structure(brief):
    run = services.create_run(brief, {})
    research = run.steps.get(key="research")
    research_prompt = prompting.render("research", prompting.context_for(research))[1]["content"]
    assert "## Must Include" in research_prompt and "## Missing Opportunity" in research_prompt
    assert "Do Better" not in research_prompt and "## Cannibalization" in research_prompt
    assert "sdsmanager.com/us/sds-management-articles" in research_prompt  # internal index rows

    research.status = StepRun.Status.APPROVED
    research.save()
    services.add_version(research, "RESEARCH NOTES MARKER")
    outline = run.steps.get(key="outline")
    outline_prompt = prompting.render("outline", prompting.context_for(outline))[1]["content"]
    assert "## H1 Options" in outline_prompt and "## Conclusion Plan" in outline_prompt
    assert "ehs-software" in outline_prompt  # product registry with the deepest-page rule

    draft_prompt = prompting.render("draft", prompting.context_for(run.steps.get(key="draft")))
    system, user = draft_prompt[0]["content"], draft_prompt[1]["content"]
    assert "RESEARCH NOTES MARKER" in user  # the draft now sees the research
    assert '"this article"' in user and "## Key Takeaways" in user and "### Excerpts" in user
    assert "no em or en dashes" in system


def test_internal_links_and_products_follow_the_region(brief):
    brief.region = "UK"
    rows = houseref.related_articles(brief)
    assert rows and all(row["region"] in ("All", "UK") for row in rows)
    assert "/uk/ehs-software/" in houseref.product_pages_block("UK")


# ---- Metadata: tags and excerpt ----


def test_metadata_tags_and_excerpt_reach_the_page(brief):
    text = (
        "# Title\n\nBody.\n\n## Metadata options\n### Meta Titles\n- SDS Retention Requirements Guide\n"
        "### Meta Descriptions\n- " + "x" * 150 + "\n### Slugs\n- sds-retention\n"
        "### Tags\n- sds retention requirements, how long to keep safety data sheets, osha\n"
        "### Excerpts\n- You keep an SDS while the chemical is on site "
        "and its exposure record for 30 years.\n"
    )
    _, options = textclean.split_metadata(text)
    assert set(options) == {"title", "meta", "slug", "tags", "excerpt"}
    assert options["tags"][0].startswith("sds retention requirements, ")


# ---- Publish gate ----


def test_publish_refuses_while_markers_remain(brief, monkeypatch):
    run = services.create_run(brief, {})
    from apps.content import exports

    monkeypatch.setattr(
        exports,
        "article_content",
        lambda run, variant="final": type("C", (), {"text": "# T\n\nA claim [VERIFY].\n"})(),
    )
    with pytest.raises(executors.StepError, match="Resolve the working markers"):
        executors.publish(run.steps.get(key="publish"))


def test_strip_sources_on_final_cleanup(brief, admin_user):
    run = services.create_run(brief, {})
    cleanup = _ready(run.steps.get(key="cleanup"), "# T\n\nA fact [SRC: https://osha.gov/x].\n")
    saved = services.strip_sources(cleanup, admin_user)
    assert "[SRC" not in saved.content and saved.source == "edit"


# ---- Search data providers ----


def test_search_providers_have_their_own_settings_page(admin_client):
    search_html = admin_client.get(reverse("studio:search_providers")).content.decode()
    assert "Serper (Google results)" in search_html and "DuckDuckGo" in search_html
    keys_html = admin_client.get(reverse("studio:provider_keys")).content.decode()
    assert "Serper (Google results)" not in keys_html and "Groq" in keys_html


def test_duckduckgo_is_the_keyless_default(monkeypatch):
    for name in ("SERPER_API_KEY", "BRAVE_SEARCH_API_KEY", "GOOGLE_CSE_API_KEY", "OLLAMA_CLOUD_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    page = (
        '<a rel="nofollow" class="result__a" '
        'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fsds">SDS '
        '<b>retention</b></a><a class="result__snippet" href="#">Keep it 30 years.</a>'
    )
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, text=page)

    data = serp.search("sds retention", "UK", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert data.provider == "duckduckgo" and "kl=uk-en" in seen["body"]
    assert data.results[0].url == "https://example.com/sds" and data.results[0].title == "SDS retention"


# ---- In-article image branding ----


def _png(color=(30, 120, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", (800, 450), color).save(buffer, "PNG")
    return buffer.getvalue()


def test_inner_images_get_the_logo_or_a_clear_reason():
    if [name for name in hero.INNER_ASSETS if not (hero.VENDOR_DIR / "assets" / name).is_file()]:
        with pytest.raises(hero.BrandingError, match="logo files aren't installed"):
            hero.brand_inner(_png(), "chart.png")
        return
    data, report = hero.brand_inner(_png(), "chart.png")
    assert data != _png() and report.get("corner") in {"bottom-right", "bottom-left", "top-right", "top-left"}


def test_vector_images_are_not_branded():
    with pytest.raises(hero.BrandingError, match="aren't branded"):
        hero.brand_inner(b"<svg/>", "diagram.svg")


def test_upload_can_place_the_logo_in_a_chosen_corner(admin_client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    if [name for name in hero.INNER_ASSETS if not (hero.VENDOR_DIR / "assets" / name).is_file()]:
        pytest.skip("brand assets aren't installed (docs/setup.md step 5)")
    _, report = hero.brand_inner(_png(), "chart.png", corner="tl")
    assert report.get("corner") == "top-left"
    response = admin_client.post(
        reverse("studio:editor_upload_image"),
        {
            "file": SimpleUploadedFile("chart.png", _png(), content_type="image/png"),
            "alt": "A chart of retention periods",
            "brand": "1",
            "logo_corner": "br",
        },
    )
    assert response.status_code == 201 and "bottom right" in response.json()["branding"]
