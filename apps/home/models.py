from wagtail.models import Page


class HomePage(Page):
    """The site's front page: what the studio is, a way into the admin, and the published articles."""

    def get_context(self, request, *args, **kwargs):
        from apps.content.models import ArticlePage

        context = super().get_context(request, *args, **kwargs)
        context["articles"] = (
            ArticlePage.objects.live().public().specific().order_by("-first_published_at")[:20]
        )
        return context
