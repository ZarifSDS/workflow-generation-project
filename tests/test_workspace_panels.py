"""The run screen's side panels (UX audit item 4): measured durations in the model lists, one grade
readout per step, and what to do about each quality-scan count."""

import pytest
from django.urls import reverse

from apps.studio import services
from apps.studio.models import ContentBrief, StepRun
from apps.studio.views.runs import observed_durations

pytestmark = pytest.mark.django_db

ARTICLE = (
    "# SDS Retention: How Long to Keep Them\n\n"
    + "Keep every safety data sheet on file. " * 40
    + ("\n\n## What the Rule Says\n\n" + "The employer keeps each record for thirty years after use. " * 30)
)


@pytest.fixture
def run(admin_user):
    brief = ContentBrief.objects.create(
        topic="SDS retention", pkeyword="SDS retention", created_by=admin_user
    )
    return services.create_run(brief, {})


def test_model_lists_show_how_long_each_model_took_for_this_step(run, admin_client):
    step = run.steps.get(key="draft")
    for seconds in (40, 60, 200):
        services.add_version(
            step,
            ARTICLE,
            provider="ollama_cloud",
            model="gpt-oss:120b",
            extra_metrics={"duration_seconds": seconds},
        )
    assert observed_durations("draft")["ollama_cloud::gpt-oss:120b"] == {"seconds": 60, "runs": 3}
    step.status = StepRun.Status.READY
    step.save()
    page = admin_client.get(reverse("studio:run", args=[run.pk]) + "?step=draft")
    assert "took 1 min" in page.text and "for this step (median of 3)" in page.text


def test_one_grade_readout_and_what_to_do_about_scans(run, admin_client):
    step = run.steps.get(key="draft")
    version = services.add_version(step, ARTICLE)
    version.metrics = {**version.metrics, "quality": {"deslop_findings": [{"x": 1}], "unclear_references": 2}}
    version.save()
    step.status = StepRun.Status.READY
    step.save()
    page = admin_client.get(reverse("studio:run", args=[run.pk]) + "?step=draft")
    assert 'href="#grades-head">Grade by section, with Tune' in page.text
    assert 'class="s-grade"' not in page.text  # the sidebar bars aren't repeated beside the table
    assert "remove the AI tells" in page.text and "Name the thing." in page.text


@pytest.mark.parametrize(
    "template",
    ["task_defaults.html", "provider_model_form.html", "provider_models.html", "run_workspace.html"],
)
def test_inline_scripts_wait_for_the_page(template):
    """Wagtail renders the extra_js block before the page content, so an inline script that looks up
    elements must wait for DOMContentLoaded (Default models showed empty dropdowns without it)."""
    from pathlib import Path

    text = (Path(__file__).parent.parent / "apps/studio/templates/studio" / template).read_text(
        encoding="utf-8"
    )
    script = text[text.index("{% block extra_js %}") :]
    assert 'document.addEventListener("DOMContentLoaded"' in script
