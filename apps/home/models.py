from wagtail.models import Page


class HomePage(Page):
    """The site's front page: what the studio is, a way into the admin, and the published articles."""

    # The four types the company CMS offers under its home page ("+" on Home).
    subpage_types = [
        "content.ArticlePage",
        "content.ArticleIndexPage",
        "home.HomePage",
        "content.WebinarPage",
    ]

    class Meta:
        verbose_name = "Home page"

    def get_context(self, request, *args, **kwargs):
        from apps.content.models import ArticlePage, listing_order

        context = super().get_context(request, *args, **kwargs)
        pages = ArticlePage.objects.live().public().descendant_of(self).specific()
        context["articles"] = listing_order(pages, request)[:20]
        return context
