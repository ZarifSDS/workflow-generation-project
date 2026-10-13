import urllib.request

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import JsonResponse
from django.views.generic import TemplateView
from wagtail.admin.views.generic.base import WagtailAdminTemplateMixin

from .. import permissions


def reachable(url, timeout=1.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status < 500
    except OSError:
        return False


def host_services():
    ollama, comfyui = settings.OLLAMA_BASE_URL, settings.COMFYUI_BASE_URL
    return [
        {
            "name": "Ollama on your PC",
            "url": ollama,
            "ok": reachable(f"{ollama}/api/tags"),
            "fix": "Start Ollama from the Start menu.",
        },
        {
            "name": "ComfyUI on your PC",
            "url": comfyui,
            "ok": reachable(f"{comfyui}/system_stats"),
            "fix": "Start ComfyUI to generate images locally; Cloudflare is used otherwise.",
        },
    ]


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


class StudioPage(WagtailAdminTemplateMixin, TemplateView):
    """Base for Content Studio admin pages: Wagtail header, breadcrumbs and studio assets.

    `permission_required` guards every request and `post_permission` additionally guards POSTs
    (apps/studio/permissions.py).
    """

    header_icon = "rocket"
    breadcrumbs_items = None
    permission_required = permissions.ACCESS
    post_permission = None

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.has_perm(self.permission_required) or (
            request.method == "POST" and self.post_permission and not user.has_perm(self.post_permission)
        ):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        items = [{"url": "", "label": "Content Studio"}]
        return items + (self.breadcrumbs_items or [])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["generation_connected"] = getattr(settings, "STUDIO_EXECUTE_STEPS", False)
        context["profiles_interim"] = getattr(settings, "AI_PROFILES_INTERIM", False)
        user = self.request.user
        context["can_write"] = permissions.can_start_runs(user)
        context["can_operate"] = user.has_perm(permissions.OPERATE)
        return context
