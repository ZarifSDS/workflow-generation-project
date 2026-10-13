"""Page types under Root, and author profiles.

The four types the company CMS (cms.sdsmanager.com, Wagtail 6.3) offers under Root are replicated field for
field, with their labels, help texts and choice lists, checked against the live CMS on 2026-10-14:
"Article and News Page" (ArticlePage), "Content category" (ArticleIndexPage), "Home page" (home.HomePage)
and "Webinar" (WebinarPage). Where we deliberately differ it's noted at the field. Approved runs publish
into ArticlePage (M7).
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from modelcluster.contrib.taggit import ClusterTaggableManager
from modelcluster.fields import ParentalKey
from taggit.models import TaggedItemBase
from wagtail import blocks
from wagtail.admin.forms import WagtailAdminPageForm
from wagtail.admin.panels import CommentPanel, FieldPanel, InlinePanel, MultiFieldPanel, Panel
from wagtail.documents import get_document_model_string
from wagtail.fields import StreamField
from wagtail.models import Orderable, Page
from wagtail.search import index

from .blocks import ARTICLE_BLOCKS, RICH_TEXT_FEATURES, AgendaItemBlock  # noqa: F401 - RICH_TEXT_FEATURES is re-exported
from .choices import Language, Locale


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
        return f"{self.name} - {self.role}" if self.role else self.name


# ---- Shared by the page types ----

PARENTS = ["wagtailcore.Page", "home.HomePage", "content.ArticleIndexPage"]  # Root, as in the company CMS


def score(page):
    """The company CMS's sorting score: base score (the page ID) + priority. Higher sorts first."""
    return (page.pk or 0) + (getattr(page, "priority", 0) or 0)


def listing_order(pages, request=None):
    """Highest score first, only pages with a public URL. Works on mixed page types (articles and
    webinars). Pages created directly under Root (as in the headless company CMS) have no URL on this
    site, so they're left out of listings instead of producing broken links."""
    return sorted((p for p in pages if p.get_url(request)), key=score, reverse=True)


def linked_translations(page, request=None):
    return [p for p in page.translations.live().public().order_by("title") if p.get_url(request)]


class ListedPageForm(WagtailAdminPageForm):
    """Intro is required when an editor saves (as in the company CMS); the model allows it empty so the
    Publish step can save a draft and report the missing intro instead of failing. Priority's help text
    shows the computed score, as the company CMS does."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "intro" in self.fields:
            self.fields["intro"].required = True
        if "priority" in self.fields:
            base = self.instance.pk
            priority = self.instance.priority or 0
            final = (base or 0) + priority
            self.fields["priority"].help_text = (
                f"The computed sorting score follows: Base Score ({base}) + Priority ({priority}) "
                f"= Final Score ({final}). Higher scores are listed first."
            )

    def clean(self):
        cleaned = super().clean()
        english = cleaned.get("english_page")
        if english and self.instance.pk and english.pk == self.instance.pk:
            self.add_error("english_page", "A page can't be its own English version.")
        elif english and cleaned.get("language") == Language.EN:
            self.add_error(
                "english_page",
                "Only translations link to an English page. Change the language or clear this.",
            )
        return cleaned


def _locale_field():
    # Named "region" in the database: runs fill it from the brief's region (US, UK, AU, CA, NZ, EU).
    return models.CharField("locale short name", max_length=4, choices=Locale.choices, blank=True)


def _language_field():
    return models.CharField(max_length=5, choices=Language.choices, blank=True, default=Language.EN)


def _display_title(prefix, page):
    """How the company CMS lists pages in the admin, e.g. "Article What is an SDS? (en)"."""
    language = f" ({page.language})" if page.language else ""
    return f"{prefix}{page.title}{language}"


class ArticlePageTag(TaggedItemBase):
    content_object = ParentalKey("content.ArticlePage", on_delete=models.CASCADE, related_name="tagged_items")


class ArticleIndexPage(Page):
    """Content category, with a link to the category it translates. Lists the live pages under it."""

    original_content_category = models.ForeignKey(
        "content.ArticleIndexPage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="translations",
        verbose_name="original content category",
        help_text="The original content category.",
    )
    language = _language_field()
    region = _locale_field()

    parent_page_types = ["wagtailcore.Page", "home.HomePage"]
    subpage_types = ["content.ArticlePage", "content.WebinarPage"]

    content_panels = [
        *Page.content_panels,
        FieldPanel("original_content_category"),
        FieldPanel("language"),
        FieldPanel("region"),
    ]

    class Meta:
        verbose_name = "Content category"
        verbose_name_plural = "Content categories"

    def get_admin_display_title(self):
        return _display_title("", self)

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context["articles"] = listing_order(self.get_children().live().public().specific(), request)
        return context


class ArticlePage(Page):
    class Category(models.TextChoices):
        ARTICLE = "article", "Article"
        NEWS = "news", "News"

    # Article information
    created_date = models.DateTimeField(default=timezone.now)
    author = models.ForeignKey(
        Author,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="articles",
        verbose_name="author profile",
    )
    tags = ClusterTaggableManager(through=ArticlePageTag, blank=True)

    hero_image = models.ForeignKey(
        "wagtailimages.Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # A text area rather than the company CMS's one-line box: intros run to a sentence or two.
    intro = models.TextField(blank=True)
    body = StreamField(ARTICLE_BLOCKS, verbose_name="body blocks")

    region = _locale_field()
    language = _language_field()
    english_page = models.ForeignKey(
        "content.ArticlePage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="translations",
        help_text="The English article.",
    )
    category = models.CharField(max_length=10, choices=Category.choices, blank=True)
    priority = models.IntegerField(default=0)

    primary_keyword = models.CharField(max_length=120, blank=True)
    run = models.OneToOneField(
        "studio.GenerationRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="article_page",
        help_text="The Content Studio run that produced this article.",
    )

    parent_page_types = PARENTS
    subpage_types = []
    base_form_class = ListedPageForm

    content_panels = [
        RunLinkPanel(),
        *Page.content_panels,
        MultiFieldPanel(
            [FieldPanel("created_date"), FieldPanel("author"), FieldPanel("tags")],
            heading="Article information",
        ),
        FieldPanel("hero_image", heading="Hero image block", icon="image"),
        FieldPanel("intro"),
        FieldPanel("body"),
        InlinePanel("gallery_images", heading="Gallery images", label="Gallery images"),
        FieldPanel("region"),
        FieldPanel("language"),
        FieldPanel("english_page"),
        FieldPanel("category"),
        FieldPanel("priority"),
        # Wagtail's own go_live_at, so the date really schedules publishing.
        FieldPanel("go_live_at", heading="Scheduled publish date", icon="date"),
    ]
    promote_panels = [
        *Page.promote_panels,
        MultiFieldPanel([FieldPanel("primary_keyword")], heading="For content planning"),
    ]
    settings_panels = [CommentPanel()]  # go_live_at is in the content tab
    search_fields = [*Page.search_fields, index.SearchField("intro"), index.SearchField("body")]

    class Meta:
        verbose_name = "Article and News Page"

    def get_admin_display_title(self):
        return _display_title(f"{self.get_category_display()} " if self.category else "", self)

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context["translations"] = linked_translations(self, request)
        return context


class ArticleGalleryImage(Orderable):
    page = ParentalKey(ArticlePage, on_delete=models.CASCADE, related_name="gallery_images")
    image = models.ForeignKey("wagtailimages.Image", on_delete=models.CASCADE, related_name="+")
    caption = models.CharField(max_length=255, blank=True)

    panels = [FieldPanel("image"), FieldPanel("caption")]


SLIDES_MAX_BYTES = 10 * 1024 * 1024


class WebinarPageForm(ListedPageForm):
    def clean(self):
        cleaned = super().clean()
        slides = cleaned.get("slides_file")
        if slides:
            if not slides.file.name.lower().endswith(".pdf"):
                self.add_error("slides_file", "Choose a PDF.")
            elif (slides.get_file_size() or 0) > SLIDES_MAX_BYTES:
                self.add_error("slides_file", "The slides PDF is larger than 10 MB.")
        if cleaned.get("webinar_type") == WebinarPage.Type.LIVE and not cleaned.get("start_at"):
            self.add_error("start_at", "A live webinar needs a start time.")
        return cleaned


class WebinarPage(Page):
    class Type(models.TextChoices):
        LIVE = "live", "Live (Zoom)"
        RECORDED = "recorded", "Recorded (YouTube)"

    # Webinar information
    webinar_type = models.CharField(max_length=10, choices=Type.choices, default=Type.LIVE)
    # The company CMS asks for UTC; here the time is in the site's time zone, like every other date field.
    start_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=f"Start date/time of the live webinar ({settings.TIME_ZONE}).",
    )
    duration_minutes = models.PositiveIntegerField(
        null=True, blank=True, help_text="Planned duration in minutes, e.g. 45."
    )
    capacity = models.PositiveIntegerField(
        null=True, blank=True, help_text="Maximum number of registrations. Leave empty for unlimited."
    )
    webinar_category = models.CharField(
        max_length=80, blank=True, help_text='Topic tag shown on cards, e.g. "GHS Compliance".'
    )
    # Links & files
    zoom_join_url = models.URLField(
        "zoom join url",
        blank=True,
        help_text="Zoom join link. PRIVATE: never shown on the public page.",
    )
    youtube_url = models.URLField(
        "youtube url", blank=True, help_text="YouTube link of the recording (replay/on-demand embed)."
    )
    slides_file = models.ForeignKey(
        get_document_model_string(),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text='Slides PDF offered via the "Get slides" button (max 10 MB).',
    )
    host = models.ForeignKey(
        Author, null=True, blank=True, on_delete=models.SET_NULL, related_name="webinars"
    )

    hero_image = models.ForeignKey(
        "wagtailimages.Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    intro = models.TextField(blank=True)
    body = StreamField(ARTICLE_BLOCKS, blank=True, verbose_name="body blocks")
    learn_points = StreamField(
        [("point", blocks.CharBlock(label="Point", max_length=255))],
        blank=True,
        help_text='Bullet items for the "What you\'ll learn" section.',
    )
    agenda = StreamField(
        [("item", AgendaItemBlock())], blank=True, help_text="Agenda (upcoming) / chapters (recorded)."
    )

    region = _locale_field()
    language = _language_field()
    english_page = models.ForeignKey(
        "content.WebinarPage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="translations",
        help_text="The English article.",
    )
    priority = models.IntegerField(default=0)

    parent_page_types = PARENTS
    subpage_types = []
    base_form_class = WebinarPageForm

    content_panels = [
        *Page.content_panels,
        MultiFieldPanel(
            [
                FieldPanel("webinar_type"),
                FieldPanel("start_at"),
                FieldPanel("duration_minutes"),
                FieldPanel("capacity"),
                FieldPanel("webinar_category"),
            ],
            heading="Webinar information",
        ),
        MultiFieldPanel(
            [FieldPanel("zoom_join_url"), FieldPanel("youtube_url"), FieldPanel("slides_file")],
            heading="Links & files",
        ),
        FieldPanel("host"),
        FieldPanel("hero_image", heading="Hero image block", icon="image"),
        FieldPanel("intro"),
        FieldPanel("body"),
        FieldPanel("learn_points"),
        FieldPanel("agenda"),
        FieldPanel("region"),
        FieldPanel("language"),
        FieldPanel("english_page"),
        FieldPanel("priority"),
        FieldPanel("go_live_at", heading="Scheduled publish date", icon="date"),
    ]
    settings_panels = [CommentPanel()]
    search_fields = [*Page.search_fields, index.SearchField("intro"), index.SearchField("body")]

    class Meta:
        verbose_name = "Webinar"

    def get_admin_display_title(self):
        return _display_title("Webinar: ", self)

    @property
    def ends_at(self):
        return self.start_at + timedelta(minutes=self.duration_minutes or 60) if self.start_at else None

    @property
    def is_upcoming(self):
        return self.webinar_type == self.Type.LIVE and bool(self.start_at) and timezone.now() < self.ends_at

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context["translations"] = linked_translations(self, request)
        return context
