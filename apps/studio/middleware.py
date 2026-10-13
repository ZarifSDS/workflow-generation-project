"""Admin-only notifications (on your next admin page view, say which steps became ready for review)
and the SVG sandbox header."""

from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import GenerationRun, StepRun

SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


class SvgSandboxMiddleware:
    """Serves SVG files so scripts inside them can't run if someone opens the file directly.

    Covers media served by Django (dev); Caddy sets the same header in share and production mode.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.get("Content-Type", "").startswith("image/svg+xml"):
            response["Content-Security-Policy"] = SVG_CSP
        return response


class ReviewNotificationsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method == "GET"
            and request.path.startswith("/admin/")
            and not request.headers.get("x-requested-with")
            and getattr(request, "user", None) is not None
            and request.user.is_authenticated
            and request.user.is_staff
        ):
            self.notify(request)
        return self.get_response(request)

    def notify(self, request):
        ready = (
            StepRun.objects.filter(
                status=StepRun.Status.READY,
                notified_at__isnull=True,
                run__status=GenerationRun.Status.NEEDS_REVIEW,
            )
            .select_related("run__brief")
            .order_by("finished_at")[:5]
        )
        ids = []
        for step in ready:
            url = f"{reverse('studio:run', args=[step.run_id])}?step={step.key}"
            messages.info(
                request,
                format_html(
                    '{} is ready for review: <a href="{}">{}</a>', step.label, url, step.run.brief.topic
                ),
            )
            ids.append(step.pk)
        if ids:
            StepRun.objects.filter(pk__in=ids).update(notified_at=timezone.now())
