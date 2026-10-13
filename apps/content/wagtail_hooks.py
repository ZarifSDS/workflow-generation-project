"""Admin additions for the page types: rich text features Wagtail 8 doesn't fully provide, and the menu
entries the company CMS has (Article, News, Content categories, Webinars, Author profiles).

Rich text:

- underline: a new Draftail inline style stored as <u> (the dialect's ++text++).
- Sanitiser rules ("editorhtml") for underline, strikethrough, code and blockquote: Wagtail registers
  the editor side of the last three but not the rules its DB-HTML sanitiser
  (APIRichText.sanitize_db_html) uses, so publishing would otherwise strip them.
"""

import wagtail.admin.rich_text.editors.draftail.features as draftail_features
from wagtail import hooks
from wagtail.admin.rich_text.converters.editor_html import WhitelistRule
from wagtail.admin.rich_text.converters.html_to_contentstate import InlineStyleElementHandler
from wagtail.admin.views.pages.listing import IndexView
from wagtail.admin.viewsets.pages import PageListingViewSet
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet
from wagtail.whitelist import allow_without_attributes

from .models import ArticleIndexPage, ArticlePage, Author, WebinarPage


@hooks.register("register_rich_text_features")
def register_underline(features):
    features.register_editor_plugin(
        "draftail",
        "underline",
        draftail_features.InlineStyleFeature({"type": "UNDERLINE", "label": "U", "description": "Underline"}),
    )
    features.register_converter_rule(
        "contentstate",
        "underline",
        {
            "from_database_format": {"u": InlineStyleElementHandler("UNDERLINE")},
            "to_database_format": {"style_map": {"UNDERLINE": "u"}},
        },
    )


@hooks.register("register_rich_text_features")
def register_sanitiser_rules(features):
    for feature, elements in {
        "underline": ["u"],
        "strikethrough": ["s"],
        "code": ["code"],
        "blockquote": ["blockquote"],
    }.items():
        features.register_converter_rule(
            "editorhtml", feature, [WhitelistRule(element, allow_without_attributes) for element in elements]
        )


# ---- Admin menu: the company CMS's page listings (Article, News, Content categories, Webinars) ----


class _CategoryIndexView(IndexView):
    category = ""

    def get_base_queryset(self):
        return super().get_base_queryset().filter(category=self.category)


class ArticleListIndexView(_CategoryIndexView):
    category = ArticlePage.Category.ARTICLE


class NewsListIndexView(_CategoryIndexView):
    category = ArticlePage.Category.NEWS


@hooks.register("register_admin_viewset")
def register_page_listings():
    return [
        PageListingViewSet(
            "article_pages",
            model=ArticlePage,
            index_view_class=ArticleListIndexView,
            menu_label="Article",
            icon="list-ul",
            add_to_admin_menu=True,
            menu_order=110,
        ),
        PageListingViewSet(
            "news_pages",
            model=ArticlePage,
            index_view_class=NewsListIndexView,
            menu_label="News",
            icon="globe",
            add_to_admin_menu=True,
            menu_order=120,
        ),
        PageListingViewSet(
            "content_categories",
            model=ArticleIndexPage,
            menu_label="Content categories",
            icon="folder-open-1",
            add_to_admin_menu=True,
            menu_order=130,
        ),
        PageListingViewSet(
            "webinar_pages",
            model=WebinarPage,
            menu_label="Webinars",
            icon="media",
            add_to_admin_menu=True,
            menu_order=140,
        ),
    ]


class AuthorViewSet(SnippetViewSet):
    model = Author
    menu_label = "Author profiles"
    icon = "user"
    add_to_admin_menu = True
    menu_order = 450
    list_display = ["name", "role", "user"]
    search_fields = ["name"]


register_snippet(AuthorViewSet)
