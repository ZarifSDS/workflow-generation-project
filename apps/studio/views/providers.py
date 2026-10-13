from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect

from apps.ai import catalog
from apps.ai.checks import check_text_providers
from apps.ai.models import ProviderCheck
from apps.ai.providers import get_providers

from .. import permissions
from .common import StudioPage

PROFILE_USE = {
    "quality": "Outline, draft, localise",
    "fast": "Site crawl summary, research",
    "edit": "Review and edit",
    "image": "Hero image",
}


class ProvidersView(StudioPage):
    template_name = "studio/providers.html"
    page_title = "Models and providers"
    post_permission = permissions.OPERATE

    def get_breadcrumbs_items(self):
        return super().get_breadcrumbs_items() + [{"url": "", "label": "Models and providers"}]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        checks = {check.provider: check for check in ProviderCheck.objects.all()}
        configured = get_providers()
        rows = []
        for provider, label in catalog.PROVIDER_LABELS.items():
            models = [m for m in catalog.CATALOG if m.provider == provider]
            rows.append(
                {
                    "label": label,
                    "configured": configured.get(provider) and configured[provider].is_configured,
                    "check": checks.get(provider),
                    "available": [m for m in models if m.selectable],
                    "unavailable": [m for m in models if not m.selectable],
                }
            )
        profiles = []
        for name, config in settings.AI_PROFILES.items():
            main = catalog.find(config["provider"], config["model"])
            fallback = config.get("fallback") or {}
            backup = catalog.find(fallback.get("provider"), fallback.get("model")) if fallback else None
            profiles.append(
                {
                    "name": name.capitalize(),
                    "use": PROFILE_USE.get(name, ""),
                    "main": main.label if main else config["model"],
                    "fallback": backup.label if backup else (fallback.get("model") or "–"),
                }
            )
        last = max((c.checked_at for c in checks.values()), default=None)
        context.update(rows=rows, profiles=profiles, last_checked=last)
        return context

    def post(self, request, *args, **kwargs):
        results = check_text_providers()
        problems = [name for name, (ok, _) in results.items() if not ok]
        if problems:
            messages.warning(request, f"Checked providers. Needs attention: {', '.join(problems)}.")
        else:
            messages.success(request, "Checked providers. All responded.")
        return redirect("studio:providers")
