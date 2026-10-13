from apps.ai.models import ProviderCheck

from ..models import GenerationRun
from .common import StudioPage, host_services


class DashboardView(StudioPage):
    template_name = "studio/dashboard.html"
    page_title = "Content Studio"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        runs = GenerationRun.objects.select_related("brief").prefetch_related("steps")
        context.update(
            review=runs.filter(status=GenerationRun.Status.NEEDS_REVIEW),
            in_progress=runs.filter(
                status__in=[
                    GenerationRun.Status.QUEUED,
                    GenerationRun.Status.RUNNING,
                    GenerationRun.Status.FAILED,
                ]
            ),
            recent=runs.filter(status__in=[GenerationRun.Status.DONE, GenerationRun.Status.REJECTED])[:5],
            services=host_services(),
            checks=ProviderCheck.objects.order_by("provider"),
            has_any=runs.exists(),
        )
        return context
