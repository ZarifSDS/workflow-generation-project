"""Published destination for approved runs (M7): an article index and article pages."""

from django.db import models
from wagtail import blocks
from wagtail.admin.panels import FieldPanel, Panel
from wagtail.contrib.table_block.blocks import TableBlock
from wagtail.fields import StreamField
from wagtail.models import Page
from wagtail.search import index

RICH_TEXT_FEATURES = ["bold", "italic", "link", "ol", "ul", "h4", "code", "blockquote", "hr"]


class HeadingBlock(blocks.StructBlock):
    text = blocks.CharBlock(max_length=255)
    level = blocks.ChoiceBlock(choices=[("h2", "Section (H2)"), ("h3", "Subsection (H3)")], default="h2")

    class Meta:
        icon = "title"
        template = "content/blocks/heading.html"


ARTICLE_BLOCKS = [
    ("heading", HeadingBlock()),
    ("paragraph", blocks.RichTextBlock(features=RICH_TEXT_FEATURES)),
    ("table", TableBlock()),
]


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
    hero_image = models.ForeignKey(
        "wagtailimages.Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = StreamField(ARTICLE_BLOCKS)
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

    content_panels = [RunLinkPanel(), *Page.content_panels, FieldPanel("hero_image"), FieldPanel("body")]
    promote_panels = [*Page.promote_panels, FieldPanel("primary_keyword"), FieldPanel("region")]
    search_fields = [*Page.search_fields, index.SearchField("body")]
