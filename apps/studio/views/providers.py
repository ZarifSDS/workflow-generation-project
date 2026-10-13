from django.contrib import messages
from django.shortcuts import redirect

from apps.ai import catalog, defaults
from apps.ai.checks import check_text_providers
from apps.ai.models import ProviderCheck
from apps.ai.providers import get_providers

from .. import permissions
from ..pipeline import MODEL_TASKS, profile_for
from .common import StudioPage


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
        all_models = catalog.all_models()
        labels = {**catalog.provider_labels(), **{n: s.label for n, s in configured.items() if s.added}}
        for provider, label in labels.items():
            models = [m for m in all_models if m.provider == provider]
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
        chosen = defaults.overrides()
        for task in MODEL_TASKS:
            config = profile_for(task.key)
            main = catalog.find(config.get("provider"), config.get("model"))
            fallback = config.get("fallback") or {}
            backup = catalog.find(fallback.get("provider"), fallback.get("model")) if fallback else None
            profiles.append(
                {
                    "name": task.label,
                    "use": "Set under Settings › Default models" if task.key in chosen else "Built-in",
                    "main": main.label if main else (config.get("model") or "–"),
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
