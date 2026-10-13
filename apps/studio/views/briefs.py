from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from .. import services
from ..forms import BriefForm, parse_step_config, preset_from_brief, step_rows
from ..models import BriefPreset, ContentBrief, ContentType, Region
from .common import StudioPage


def _preset_payload():
    """Preset values for the wizard's JS prefill."""
    payload = {}
    for preset in BriefPreset.objects.all():
        payload[str(preset.pk)] = {
            "content_type": preset.content_type,
            "region": preset.region,
            "fkgl": str(preset.fkgl),
            "wordcount": preset.wordcount or "",
            "audience": preset.audience,
            "comprehension": preset.comprehension,
            "cta_style": preset.cta_style,
            "narrative_mode": preset.narrative_mode,
            "step_models": preset.step_models,
        }
    return payload


class BriefWizardView(StudioPage):
    template_name = "studio/brief_wizard.html"
    page_title = "New brief"

    def dispatch(self, request, *args, **kwargs):
        self.brief = get_object_or_404(ContentBrief, pk=kwargs["pk"]) if kwargs.get("pk") else None
        if self.brief:
            self.page_title = "Edit brief"
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return super().get_breadcrumbs_items() + [
            {"url": reverse("studio:briefs"), "label": "Briefs"},
            {"url": "", "label": self.page_title},
        ]

    def get_context_data(self, form=None, **kwargs):
        context = super().get_context_data(**kwargs)
        initial = {}
        if not self.brief and self.request.GET.get("type") in ContentType.values:
            initial["content_type"] = self.request.GET["type"]
        form = form or BriefForm(instance=self.brief, initial=initial)
        content_type = form["content_type"].value() or ContentType.SEO_BLOG
        context.update(
            form=form,
            brief=self.brief,
            rows=step_rows(content_type, settings.AI_PROFILES),
            presets=_preset_payload(),
            type_help={
                "seo_blog": "For sdsmanager.com",
                "outbound": "Third-party site",
                "lead_magnet": "Checklist, guide",
                "whitepaper": "Long-form report",
            },
        )
        return context

    def post(self, request, *args, **kwargs):
        form = BriefForm(request.POST, instance=self.brief)
        action = request.POST.get("action", "start")
        if not form.is_valid():
            messages.error(request, "Some fields need attention.")
            return self.render_to_response(self.get_context_data(form=form))
        content_type = form.cleaned_data["content_type"]
        step_config = parse_step_config(request.POST, content_type)

        if action == "save_preset":
            name = request.POST.get("preset_name", "").strip()
            if not name:
                messages.error(request, "Give the preset a name to save it.")
                return self.render_to_response(self.get_context_data(form=form))
            preset = preset_from_brief(name, form.cleaned_data, step_config)
            messages.success(request, f"Saved preset “{preset.name}”.")
            return self.render_to_response(
                self.get_context_data(form=BriefForm(request.POST, instance=self.brief))
            )

        brief = form.save(commit=False)
        if not brief.created_by_id:
            brief.created_by = request.user
        brief.save()
        if action == "save":
            messages.success(request, f"Saved brief “{brief.topic}”.")
            return redirect("studio:briefs")
        run = services.create_run(brief, step_config, request.user)
        messages.success(request, f"Started a run for “{brief.topic}”.")
        return redirect("studio:run", pk=run.pk)


class BriefListView(StudioPage):
    template_name = "studio/brief_list.html"
    page_title = "Briefs"

    def get_breadcrumbs_items(self):
        return super().get_breadcrumbs_items() + [{"url": "", "label": "Briefs"}]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        briefs = ContentBrief.objects.prefetch_related("runs")
        query = self.request.GET.get("q", "").strip()
        content_type = self.request.GET.get("type", "")
        region = self.request.GET.get("region", "")
        if query:
            briefs = briefs.filter(Q(topic__icontains=query) | Q(pkeyword__icontains=query))
        if content_type in ContentType.values:
            briefs = briefs.filter(content_type=content_type)
        if region in Region.values:
            briefs = briefs.filter(region=region)
        context.update(
            briefs=briefs,
            q=query,
            type=content_type,
            region=region,
            types=ContentType.choices,
            regions=Region.choices,
        )
        return context

    def post(self, request, *args, **kwargs):
        """Start a new run from an existing brief, with default models."""
        brief = get_object_or_404(ContentBrief, pk=request.POST.get("brief"))
        run = services.create_run(brief, {}, request.user)
        messages.success(request, f"Started a run for “{brief.topic}”.")
        return redirect("studio:run", pk=run.pk)
