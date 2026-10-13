"""The company CMS's four page types under Root, and the Default models settings page."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Page, Site

from apps.ai import defaults
from apps.ai.models import TaskDefault
from apps.content.models import ArticleIndexPage, ArticlePage, WebinarPage, listing_order
from apps.home.models import HomePage
from apps.studio import services
from apps.studio.forms import step_rows
from apps.studio.models import ContentBrief, StepRun
from apps.studio.pipeline import MODEL_TASKS, STEPS, profile_for

pytestmark = pytest.mark.django_db

FOUR_TYPES = ["Article and News Page", "Content category", "Home page", "Webinar"]


@pytest.fixture
def home():
    root = Page.get_first_root_node()
    Site.objects.update_or_create(is_default_site=True, defaults={"hostname": "testsite", "root_page": root})
    page = HomePage(title="Home", slug="home-test")
    root.add_child(instance=page)
    return page


def _names(page_class_or_page):
    return sorted(str(m._meta.verbose_name) for m in page_class_or_page.creatable_subpage_models())


# ---- page types ----


def test_root_and_home_offer_the_four_company_types(home):
    assert _names(Page.get_first_root_node().specific) == FOUR_TYPES
    assert _names(home) == FOUR_TYPES


def test_add_subpage_screen_lists_the_four_types(admin_client):
    response = admin_client.get(reverse("wagtailadmin_pages:add_subpage", args=[1]))
    html = response.content.decode()
    for name in FOUR_TYPES:
        assert name in html


def test_listing_order_is_page_id_plus_priority(home):
    first = home.add_child(instance=ArticlePage(title="First", slug="first", body=[]))
    second = home.add_child(instance=ArticlePage(title="Second", slug="second", body=[]))
    assert listing_order([first, second]) == [second, first]
    first.priority = second.pk - first.pk + 1
    assert listing_order([first, second]) == [first, second]


def test_admin_titles_follow_the_company_cms(home):
    article = ArticlePage(title="What is an SDS?", slug="sds", body=[], category="article", language="en")
    news = ArticlePage(title="OSHA update", slug="osha", body=[], category="news", language="de")
    webinar = WebinarPage(title="Warehouse risks", slug="warehouse", language="en", webinar_type="recorded")
    assert article.get_admin_display_title() == "Article What is an SDS? (en)"
    assert news.get_admin_display_title() == "News OSHA update (de)"
    assert webinar.get_admin_display_title() == "Webinar: Warehouse risks (en)"


def test_edit_form_shows_the_computed_score_and_requires_intro(admin_client, home):
    page = home.add_child(instance=ArticlePage(title="Scored", slug="scored", body=[], priority=5))
    html = admin_client.get(reverse("wagtailadmin_pages:edit", args=[page.pk])).content.decode()
    assert f"Base Score ({page.pk}) + Priority (5) = Final Score ({page.pk + 5})" in html
    for label in [
        "Article information",
        "Hero image block",
        "Gallery images",
        "Locale short name",
        "English page",
        "Scheduled publish date",
        "Custom richtext",
    ]:
        assert label in html


def test_webinar_page_keeps_the_zoom_link_private(client, home):
    webinar = WebinarPage(
        title="Warehouse risks",
        slug="warehouse",
        intro="Live panel.",
        start_at=timezone.now() + timedelta(days=3),
        duration_minutes=45,
        zoom_join_url="https://zoom.example/j/secret-meeting",
        learn_points=[("point", "Where warehouse risk builds up")],
        agenda=[("item", {"time": "0:00", "title": "Welcome", "description": ""})],
    )
    home.add_child(instance=webinar)
    html = client.get(webinar.url).content.decode()
    assert "Warehouse risks" in html and "Where warehouse risk builds up" in html and "Welcome" in html
    assert "zoom.example" not in html
    assert webinar.is_upcoming


def test_content_category_lists_its_pages(client, home):
    category = home.add_child(instance=ArticleIndexPage(title="Articles", slug="articles"))
    category.add_child(instance=ArticlePage(title="Inside", slug="inside", intro="Short intro.", body=[]))
    html = client.get(category.url).content.decode()
    assert "Inside" in html and "Short intro." in html


def test_article_and_news_menu_listings_filter_by_category(admin_client, home):
    home.add_child(instance=ArticlePage(title="An article", slug="a1", body=[], category="article"))
    home.add_child(instance=ArticlePage(title="A news item", slug="n1", body=[], category="news"))
    articles = admin_client.get(reverse("article_pages:index")).content.decode()
    news = admin_client.get(reverse("news_pages:index")).content.decode()
    assert "An article" in articles and "A news item" not in articles
    assert "A news item" in news and "An article" not in news


# ---- Settings › Default models ----


def _brief():
    return ContentBrief.objects.create(
        topic="SDS retention", pkeyword="sds retention", content_type="seo_blog"
    )


def test_task_default_overrides_the_built_in_profile():
    built_in = profile_for("draft")
    TaskDefault.objects.create(task="draft", model_key="gemini::gemini-3.8-flash")
    defaults.clear_cache()
    chosen = profile_for("draft")
    assert (chosen["provider"], chosen["model"]) == ("gemini", "gemini-3.8-flash")
    assert chosen["fallback"] == built_in["fallback"]  # the built-in fallback is kept unless set


def test_new_runs_and_the_wizard_use_the_chosen_default():
    TaskDefault.objects.create(task="outline", model_key="groq::openai/gpt-oss-120b")
    defaults.clear_cache()
    rows = {row["def"].key: row for row in step_rows("seo_blog")}
    assert rows["outline"]["default"] == "groq::openai/gpt-oss-120b"
    run = services.create_run(_brief(), {})
    outline = StepRun.objects.get(run=run, key="outline")
    assert (outline.provider, outline.model) == ("groq", "openai/gpt-oss-120b")


def test_defaults_page_is_for_superusers_only(client):
    user = get_user_model().objects.create_user("writer", password="unused-test-password", is_staff=True)
    client.force_login(user)
    response = client.get(reverse("studio:task_defaults"))
    assert response.status_code in (302, 403)


def test_defaults_page_lists_every_task_and_saves(admin_client):
    html = admin_client.get(reverse("studio:task_defaults")).content.decode()
    for task in MODEL_TASKS:
        assert task.label in html
    response = admin_client.post(
        reverse("studio:task_defaults"),
        {"research_model": "gemini::gemini-3.8-flash", "research_fallback": "groq::openai/gpt-oss-120b"},
    )
    assert response.status_code == 302
    row = TaskDefault.objects.get(task="research")
    assert (row.model_key, row.fallback_key) == ("gemini::gemini-3.8-flash", "groq::openai/gpt-oss-120b")
    # Choosing "Built-in" again removes the row.
    admin_client.post(reverse("studio:task_defaults"), {"research_model": "", "research_fallback": ""})
    assert not TaskDefault.objects.filter(task="research").exists()


def test_defaults_page_rejects_unknown_or_wrong_kind_models(admin_client):
    image_model = next(t for t in MODEL_TASKS if t.kind == "image")
    response = admin_client.post(
        reverse("studio:task_defaults"),
        {"draft_model": "nowhere::fake", f"{image_model.key}_model": "gemini::gemini-3.8-flash"},
    )
    assert response.status_code == 200
    assert "Choose a model from the list." in response.content.decode()
    assert not TaskDefault.objects.exists()


def test_every_step_with_a_model_is_a_task():
    assert {s.key for s in STEPS.values() if s.profile} <= {t.key for t in MODEL_TASKS}
