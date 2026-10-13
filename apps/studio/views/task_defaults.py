"""Settings › Default models: choose the default model and fallback for each task (superusers).

The choices are stored in apps.ai.models.TaskDefault and take the place of settings.AI_PROFILES
(apps.ai.defaults). New runs and the brief wizard preselect them; a run can still pick its own model per
step. Every change is recorded under Reports › Site history.
"""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from wagtail.log_actions import log

from apps.ai import catalog, defaults
from apps.ai.models import TaskDefault

from ..pipeline import MODEL_TASKS
from .provider_keys import KeysPage


def _label(key):
    if not key:
        return "–"
    item = catalog.by_key(key)
    if item:
        return f"{item.label} ({catalog.provider_label(item.provider)})"
    return key.partition("::")[2] or key


class TaskDefaultsView(KeysPage):
    template_name = "studio/task_defaults.html"
    page_title = "Default models"
    header_icon = "cogs"

    def get_breadcrumbs_items(self):
        return [{"url": "", "label": self.page_title}]

    def rows(self, posted=None):
        stored = {row.task: row for row in TaskDefault.objects.select_related("updated_by")}
        rows = []
        for task in MODEL_TASKS:
            base = defaults.built_in(task.profile)
            row = stored.get(task.key)
            chosen = posted.get(task.key) if posted else None
            rows.append(
                {
                    "task": task,
                    "groups": catalog.grouped(task.kind),
                    "built_in": _label(defaults.model_key(base)),
                    "built_in_fallback": _label(defaults.model_key(base.get("fallback") or {})),
                    "model": chosen[0] if chosen else (row.model_key if row else ""),
                    "fallback": chosen[1] if chosen else (row.fallback_key if row else ""),
                    "row": row,
                }
            )
        return rows

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(rows=kwargs.get("rows") or self.rows(), errors=kwargs.get("errors") or {})
        return context

    def post(self, request, *args, **kwargs):
        selectable = {m.key: m for m in catalog.all_models() if m.selectable}
        posted, errors = {}, {}
        for task in MODEL_TASKS:
            model_key = request.POST.get(f"{task.key}_model", "").strip()
            fallback_key = request.POST.get(f"{task.key}_fallback", "").strip()
            for key in (model_key, fallback_key):
                if key and (key not in selectable or selectable[key].kind != task.kind):
                    errors[task.key] = "Choose a model from the list."
            posted[task.key] = (model_key, fallback_key)
        if errors:
            messages.error(request, "Nothing was saved. Check the highlighted tasks.")
            return self.render_to_response(self.get_context_data(rows=self.rows(posted), errors=errors))

        changed = []
        with transaction.atomic():
            stored = {row.task: row for row in TaskDefault.objects.all()}
            for task in MODEL_TASKS:
                model_key, fallback_key = posted[task.key]
                row = stored.get(task.key)
                if row and (row.model_key, row.fallback_key) == (model_key, fallback_key):
                    continue
                if not row and not (model_key or fallback_key):
                    continue
                if not (model_key or fallback_key):
                    log(instance=row, action="ai.default_reset", user=request.user, data={"task": task.label})
                    row.delete()
                else:
                    row = row or TaskDefault(task=task.key)
                    row.model_key, row.fallback_key, row.updated_by = model_key, fallback_key, request.user
                    row.save()
                    log(
                        instance=row,
                        action="ai.default_set",
                        user=request.user,
                        data={
                            "task": task.label,
                            "model": _label(model_key),
                            "fallback": _label(fallback_key),
                        },
                    )
                changed.append(task.label)
        if changed:
            messages.success(
                request, f"Saved the defaults for {', '.join(changed)}. New runs use them from now on."
            )
        else:
            messages.info(request, "Nothing changed.")
        return redirect("studio:task_defaults")
