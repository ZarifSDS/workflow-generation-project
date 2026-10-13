"""Eval: do the replicated page types and a skill-style article map onto a working website?

Pages can be created directly under Root (as in the company CMS, which is headless) or under the site's
Home page. Only pages under a Site's root have public URLs here, so listings and links must cope.
"""

import pytest
from django.urls import reverse
from wagtail.models import Page, Site

from apps.content import markup
from apps.content.models import ArticleIndexPage, ArticlePage, WebinarPage
from apps.home.models import HomePage

pytestmark = pytest.mark.django_db

SAMPLE = """# How Long to Keep Safety Data Sheets

You keep each SDS while the chemical is on site. By the end of this article, you'll know the rule.

## Key Takeaways

- OSHA treats an SDS as an exposure record that you keep for 30 years.

## What OSHA Requires

See our guide to [SDS management](https://sdsmanager.com/us/sds-management-articles/sds-management/).

| Record | Keep for |
|---|---|
| Exposure record | 30 years |

## Digitize Your SDS Library So Every Sheet Stays Current

Pick one shelf this week. [SDS Manager](https://sdsmanager.com/us/ehs-software/) keeps every sheet current.

"Start managing your SDS library"

## Frequently Asked Questions

:::faq
### How Long Do You Keep an SDS?

You keep an SDS for as long as the chemical is in use.
:::

## References

1. OSHA, Access to Employee Exposure and Medical Records, 29 CFR 1910.1020. https://www.osha.gov/x
"""


@pytest.fixture
def site():
    root = Page.get_first_root_node()
    home = HomePage(title="Home", slug="home-eval")
    root.add_child(instance=home)
    Site.objects.update_or_create(is_default_site=True, defaults={"hostname": "localhost", "root_page": home})
    return root, home


def _article(**kwargs):
    h1, body = markup.split_h1(SAMPLE)
    built = markup.build_article(body)
    return ArticlePage(title=h1, body=built.blocks, intro=built.intro, category="article", **kwargs)


def test_skill_style_article_renders_every_component(client, site):
    _, home = site
    page = home.add_child(instance=_article(slug="sds-retention"))
    html = client.get(page.url).content.decode()
    for expected in (
        "Key Takeaways",
        "<table",
        "How Long Do You Keep an SDS?",
        "References",
        "29 CFR 1910.1020",
    ):
        assert expected in html
    assert "[SRC" not in html and "[VISUAL" not in html


def test_cta_button_label_renders_as_a_button(client, site):
    _, home = site
    page = home.add_child(instance=_article(slug="cta"))
    html = client.get(page.url).content.decode()
    assert 'class="article__cta"' in html and "Start managing your SDS library" in html
    assert "&quot;Start managing" not in html and '"Start managing' not in html  # not a quoted line


def test_root_level_pages_do_not_break_listings(client, site):
    root, home = site
    root.add_child(instance=_article(slug="root-article"))  # like the company CMS: directly under Root
    root.add_child(instance=WebinarPage(title="Root webinar", slug="root-webinar", webinar_type="recorded"))
    category = root.add_child(instance=ArticleIndexPage(title="Root category", slug="root-category"))
    category.add_child(instance=_article(slug="in-root-category"))
    home.add_child(instance=_article(slug="home-article"))
    response = client.get(home.url)
    assert response.status_code == 200
    html = response.content.decode()
    assert 'href="None"' not in html and 'href=""' not in html


def test_root_level_pages_can_be_edited_and_previewed(admin_client, site):
    root, _ = site
    page = root.add_child(instance=_article(slug="root-preview"))
    assert admin_client.get(reverse("wagtailadmin_pages:edit", args=[page.pk])).status_code == 200
    preview = admin_client.get(reverse("wagtailadmin_pages:preview_on_edit", args=[page.pk]))
    assert preview.status_code in (200, 405)


def test_add_page_forms_open_for_all_four_types_under_root(admin_client, site):
    for app, model in (
        ("content", "articlepage"),
        ("content", "articleindexpage"),
        ("home", "homepage"),
        ("content", "webinarpage"),
    ):
        response = admin_client.get(reverse("wagtailadmin_pages:add", args=[app, model, 1]))
        assert response.status_code == 200, model
