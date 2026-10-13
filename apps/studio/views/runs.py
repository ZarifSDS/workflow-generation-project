import difflib

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from apps.ai import catalog

from .. import services
from ..models import GenerationRun, StepRun
from .common import StudioPage


class RunListView(StudioPage):
    template_name = "studio/run_list.html"
    page_title = "Runs"

    def get_breadcrumbs_items(self):
        return super().get_breadcrumbs_items() + [{"url": "", "label": "Runs"}]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        runs = GenerationRun.objects.select_related("brief").prefetch_related("steps")
        status = self.request.GET.get("status", "")
        if status in GenerationRun.Status.values:
            runs = runs.filter(status=status)
        context.update(runs=runs, status=status, statuses=GenerationRun.Status.choices)
        return context


def _checks(version, brief):
    """Summarise a version's metrics for the checks panel."""
    m = version.metrics if version else {}
    if not m:
        return None
    pk = m.get("pkeyword", {})
    red_flags = sum((m.get("accuracy_hints") or {}).get("red_flags", {}).values())
    return {
        "pk_title": pk.get("in_h1"),
        "pk_first100": pk.get("in_first_100_words"),
        "pk_headings": pk.get("in_headings", 0),
        "skeywords": m.get("skeywords", {}),
        "verify": m.get("verify_markers", 0),
        "red_flags": red_flags,
        "meta_narration": m.get("meta_narration", 0),
        "spelling": m.get("wrong_spelling_variant", {}),
        "fkgl": m.get("fkgl"),
        "sections": [s for s in m.get("section_fkgl", []) if s.get("fkgl") is not None],
        "target": float(brief.fkgl),
        "words": m.get("word_count"),
    }


class RunWorkspaceView(StudioPage):
    template_name = "studio/run_workspace.html"

    def dispatch(self, request, *args, **kwargs):
        self.run = get_object_or_404(GenerationRun.objects.select_related("brief"), pk=kwargs["pk"])
        self.page_title = self.run.brief.topic
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return super().get_breadcrumbs_items() + [
            {"url": reverse("studio:runs"), "label": "Runs"},
            {"url": "", "label": self.run.brief.topic},
        ]

    def selected_step(self):
        steps = self.run.steps.all()
        key = self.request.GET.get("step") or self.request.POST.get("step")
        if key:
            step = steps.filter(key=key).first()
            if step:
                return step
        return self.run.current_step

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        step = self.selected_step()
        version = step.latest_version if step else None
        versions = list(step.versions.order_by("-number")) if step else []
        kind = step.definition.kind if step else "text"
        context.update(
            run=self.run,
            brief=self.run.brief,
            steps=self.run.steps.all(),
            step=step,
            version=version,
            versions=versions,
            first_version=versions[-1] if versions else None,
            checks=_checks(version, self.run.brief),
            model_groups=catalog.grouped(kind) if kind in ("text", "image") else [],
            current_model_key=f"{step.provider}::{step.model}" if step and step.model else "",
            can_review=bool(
                step
                and step.status == StepRun.Status.READY
                and self.run.status != GenerationRun.Status.REJECTED
            ),
            has_metadata=self.run.metadata_options.exists(),
        )
        return context

    def post(self, request, *args, **kwargs):
        step = self.selected_step()
        action = request.POST.get("action")
        url = (
            f"{reverse('studio:run', args=[self.run.pk])}?step={step.key}" if step else reverse("studio:runs")
        )
        try:
            if action == "approve":
                services.approve_step(step, request.user)
                messages.success(request, f"Approved {step.label.lower()}.")
            elif action == "edit_approve":
                services.approve_step(step, request.user, edited_content=request.POST.get("content", ""))
                messages.success(request, f"Saved your edit and approved {step.label.lower()}.")
            elif action == "regenerate":
                services.request_regenerate(step, request.POST.get("model", ""), request.POST.get("note", ""))
                messages.success(request, f"{step.label} is queued with the chosen model.")
            elif action == "reject":
                reason = request.POST.get("reason", "").strip()
                if not reason:
                    messages.error(request, "Give a reason for rejecting the run.")
                    return redirect(url)
                services.reject_run(self.run, request.user, reason)
                messages.warning(request, "Run rejected.")
            else:
                messages.error(request, "Unknown action.")
        except ValueError as error:
            messages.error(request, str(error))
        return redirect(url)


class VersionCompareView(StudioPage):
    template_name = "studio/version_compare.html"
    page_title = "Compare versions"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        run = get_object_or_404(GenerationRun, pk=self.kwargs["pk"])
        step = get_object_or_404(StepRun, run=run, key=self.kwargs["step"])
        try:
            old = step.versions.get(number=self.kwargs["a"])
            new = step.versions.get(number=self.kwargs["b"])
        except step.versions.model.DoesNotExist as error:
            raise Http404("That version is no longer kept.") from error
        lines = []
        for line in difflib.unified_diff(
            old.content.splitlines(), new.content.splitlines(), lineterm="", n=2
        ):
            if line.startswith(("---", "+++")):
                continue
            kind = (
                "add"
                if line.startswith("+")
                else "del"
                if line.startswith("-")
                else "hunk"
                if line.startswith("@@")
                else "same"
            )
            lines.append((kind, line))
        context.update(run=run, step=step, old=old, new=new, lines=lines)
        return context

    def get_breadcrumbs_items(self):
        run_url = reverse("studio:run", args=[self.kwargs["pk"]])
        return super().get_breadcrumbs_items() + [
            {"url": reverse("studio:runs"), "label": "Runs"},
            {"url": f"{run_url}?step={self.kwargs['step']}", "label": "Run"},
            {"url": "", "label": "Compare versions"},
        ]
