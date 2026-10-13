import urllib.request

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.generic import TemplateView
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin

# The content pipeline the studio will automate (see docs/workflow.md).
PIPELINE_STEPS = [
    ("Brief", "Topic, keywords, audience, region, word count and readability target."),
    ("Research", "Sources, facts and claims to verify."),
    ("Outline", "Detailed and headings-only outlines. Needs your approval."),
    ("Draft", "Full draft plus metadata options. Needs your approval."),
    ("Edit and de-AI", "Revision with quality checks and a changelog. Needs your approval."),
    ("Final cleanup", "Hidden-character removal and final polish."),
    ("Hero image", "Generated image with house branding."),
    ("Localise", "Regional or language variants."),
]


def _reachable(url, timeout=1.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status < 500
    except OSError:
        return False


def healthz(request):
    """Liveness and database check used by the Docker healthcheck."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database = "ok"
    except Exception:  # noqa: BLE001 - report any DB failure as unhealthy
        database = "error"
    status = 200 if database == "ok" else 503
    body = {"status": "ok" if status == 200 else "error", "database": database}
    return JsonResponse(body, status=status)


class StudioOverviewView(WagtailAdminTemplateMixin, TemplateView):
    template_name = "studio/overview.html"
    page_title = "Content Studio"
    header_icon = "rocket"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pipeline_steps"] = PIPELINE_STEPS
        ollama, comfyui = settings.OLLAMA_BASE_URL, settings.COMFYUI_BASE_URL
        context["services"] = [
            ("Ollama (host)", ollama, _reachable(f"{ollama}/api/tags")),
            ("ComfyUI (host)", comfyui, _reachable(f"{comfyui}/system_stats")),
        ]
        return context
