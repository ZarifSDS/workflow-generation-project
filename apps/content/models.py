"""Published destination for approved runs (M7): an article index, article pages and author profiles.

The page's fields follow the company CMS's "Article and News Page" where they help editors (intro,
category, tags, author, image/embed/FAQ blocks); publishing date and time use Wagtail's own go_live_at.
"""

from django.conf import settings
from django.db import models
from modelcluster.contrib.taggit import ClusterTaggableManager
from modelcluster.fields import ParentalKey
from taggit.models import TaggedItemBase
from wagtail.admin.panels import FieldPanel, MultiFieldPanel, Panel
from wagtail.fields import StreamField
from wagtail.models import Page
from wagtail.search import index
from wagtail.snippets.models import register_snippet

from .blocks import ARTICLE_BLOCKS, RICH_TEXT_FEATURES  # noqa: F401 - RICH_TEXT_FEATURES is re-exported


class RunLinkPanel(Panel):
    """Links an article back to the Content Studio run that produced it."""

    class BoundPanel(Panel.BoundPanel):
        template_name = "content/panels/run_link.html"

        def is_shown(self):
            return bool(getattr(self.instance, "run_id", None))

        def get_context_data(self, parent_context=None):
            context = super().get_context_data(parent_context)
            context["run"] = self.instance.run
            return context


@register_snippet
class Author(index.Indexed, models.Model):
    name = models.CharField(max_length=120)
    role = models.CharField(
        max_length=120, blank=True, help_text="Shown under the name, e.g. EHS consultant."
    )
    bio = models.TextField(blank=True)
    photo = models.ForeignKey(
        "wagtailimages.Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="author_profile",
        help_text="Articles from this person's runs get this profile automatically.",
    )

    panels = [
        FieldPanel("name"),
        FieldPanel("role"),
        FieldPanel("bio"),
        FieldPanel("photo"),
        FieldPanel("user"),
    ]
    search_fields = [index.SearchField("name"), index.AutocompleteField("name")]

    class Meta:
        ordering = ["name"]
        verbose_name = "author profile"

    def __str__(self):
        return self.name


class ArticlePageTag(TaggedItemBase):
    content_object = ParentalKey("content.ArticlePage", on_delete=models.CASCADE, related_name="tagged_items")


class ArticleIndexPage(Page):
    parent_page_types = ["home.HomePage"]
    subpage_types = ["content.ArticlePage"]
    max_count = 1

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context["articles"] = (
            ArticlePage.objects.child_of(self).live().specific().order_by("-first_published_at")
        )
        return context


class ArticlePage(Page):
    class Category(models.TextChoices):
        ARTICLE = "article", "Article"
        NEWS = "news", "News"

    intro = models.TextField(
        blank=True, help_text="One or two sentences shown above the article and in listings."
    )
    hero_image = models.ForeignKey(
        "wagtailimages.Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = StreamField(ARTICLE_BLOCKS)
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.ARTICLE)
    tags = ClusterTaggableManager(through=ArticlePageTag, blank=True)
    author = models.ForeignKey(
        Author, null=True, blank=True, on_delete=models.SET_NULL, related_name="articles"
    )
    region = models.CharField(max_length=4, blank=True)
    primary_keyword = models.CharField(max_length=120, blank=True)
    run = models.OneToOneField(
        "studio.GenerationRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="article_page",
        help_text="The Content Studio run that produced this article.",
    )

    parent_page_types = ["content.ArticleIndexPage"]
    subpage_types = []

    content_panels = [
        RunLinkPanel(),
        *Page.content_panels,
        MultiFieldPanel(
            [FieldPanel("category"), FieldPanel("author"), FieldPanel("tags")], heading="Article information"
        ),
        FieldPanel("intro"),
        FieldPanel("hero_image"),
        FieldPanel("body"),
    ]
    promote_panels = [*Page.promote_panels, FieldPanel("primary_keyword"), FieldPanel("region")]
    search_fields = [*Page.search_fields, index.SearchField("intro"), index.SearchField("body")]
