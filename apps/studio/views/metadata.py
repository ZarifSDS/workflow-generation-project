from urllib.parse import urlparse

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from .. import permissions, services
from ..models import GenerationRun, MetadataOption
from .common import StudioPage


class MetadataView(StudioPage):
    template_name = "studio/metadata.html"
    page_title = "Title and meta"
    post_permission = permissions.WRITING

    def dispatch(self, request, *args, **kwargs):
        self.run = get_object_or_404(GenerationRun.objects.select_related("brief"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return super().get_breadcrumbs_items() + [
            {"url": reverse("studio:runs"), "label": "Runs"},
            {"url": reverse("studio:run", args=[self.run.pk]), "label": self.run.brief.topic},
            {"url": "", "label": "Title and meta"},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        options = self.run.metadata_options.all()
        keyword = self.run.brief.pkeyword.lower()
        groups = []
        for kind, label in MetadataOption.Kind.choices:
            items = [o for o in options if o.kind == kind]
            groups.append(
                {
                    "kind": kind,
                    "label": label,
                    "items": items,
                    "limit": MetadataOption.LIMITS[kind],
                    "multiple": kind == MetadataOption.Kind.TITLE,
                }
            )
        selected = {
            kind: next((o for o in options if o.kind == kind and o.selected), None)
            for kind in MetadataOption.Kind.values
        }
        title = selected["title"].text if selected["title"] else ""
        brief = self.run.brief
        if brief.content_type == "outbound" and (brief.site_domain or brief.site):
            host = urlparse(brief.site_domain).netloc or brief.site
            crumbs = [host.removeprefix("www.")]
        else:
            # Where sdsmanager.com publishes articles (the internal index's URLs).
            crumbs = ["sdsmanager.com", brief.region.lower(), "sds-management-articles"]
        context.update(
            preview_crumbs=crumbs,
            run=self.run,
            groups=groups,
            selected=selected,
            keyword=keyword,
            keyword_in_title=bool(title) and keyword in title.lower(),
            titles_selected=sum(1 for o in options if o.kind == "title" and o.selected),
        )
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action == "add":
            kind = request.POST.get("kind")
            if kind not in MetadataOption.Kind.values:
                messages.error(request, "Unknown option type.")
            else:
                try:
                    services.add_own_metadata(self.run, kind, request.POST.get(f"own_{kind}", ""))
                    messages.success(request, "Added your option and selected it.")
                except ValueError as error:
                    messages.error(request, str(error))
        else:
            ids = {int(value) for value in request.POST.getlist("selected") if value.isdigit()}
            for kind in ("meta", "slug", "tags", "excerpt"):  # single choice per kind
                value = request.POST.get(f"choice_{kind}")
                if value and value.isdigit():
                    ids.add(int(value))
            try:
                services.set_metadata_selection(self.run, ids)
                messages.success(request, "Saved your selection.")
            except ValueError as error:
                messages.error(request, str(error))
        return redirect("studio:metadata", pk=self.run.pk)
