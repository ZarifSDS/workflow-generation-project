"""The friendlier run screen and wizard (docs/pricing-and-ux-plan.md, Part 2): text first, a next-step
banner, one "Change this" area, a grouped step list, no reload over unsaved typing, no one-click runs."""

import pytest
from django.urls import reverse

from apps.studio import services
from apps.studio.models import ContentBrief, StepRun

pytestmark = pytest.mark.django_db

ARTICLE = (
    "# SDS Retention: How Long to Keep Them\n\n"
    + "Keep every safety data sheet on file. " * 40
    + "\n\n## What the Rule Says\n\n"
    + "The employer keeps each record for thirty years after use [VERIFY]. " * 20
)


@pytest.fixture
def run(admin_user):
    brief = ContentBrief.objects.create(
        topic="SDS retention", pkeyword="SDS retention", created_by=admin_user
    )
    return services.create_run(brief, {})


def _ready(run, key, content=ARTICLE):
    step = run.steps.get(key=key)
    services.add_version(step, content)
    step.status = StepRun.Status.READY
    step.save()
    return step


def _page(client, run, key):
    return client.get(reverse("studio:run", args=[run.pk]) + f"?step={key}").content.decode()


def test_the_text_comes_first_with_a_banner_and_an_approve_that_says_what_follows(admin_client, run):
    _ready(run, "draft")
    html = _page(admin_client, run, "draft")
    assert "Draft is ready for you." in html and "must be resolved before it can be published" in html
    assert "Approve and start review and edit" in html
    # Order: banner, text, markers, approve, Change this, then the folded logs.
    banner, text = html.index("Draft is ready for you."), html.index("data-editor-output")
    markers, approve = html.index('id="markers-head"'), html.index('value="approve"')
    change = html.index('id="change-head"')
    assert banner < text < markers < approve < change


def test_change_this_has_three_ways_and_the_side_model_panel_waits_for_failures(admin_client, run):
    _ready(run, "draft")
    html = _page(admin_client, run, "draft")
    for way in ("Edit it yourself", "Ask for specific changes", "Write it again"):
        assert way in html
    assert 'value="chat_apply"' in html and 'name="how" value="regenerate"' in html
    assert 'value="edit">Apply as targeted edits' not in html  # merged into "Ask for specific changes"
    # The side panel's model picker shows only before a run or after a failure.
    assert 'id="regen-model"' not in html
    # One primary button on the page (Approve), plus "Save and approve" inside the editor once it's open.
    assert html.count('class="button" type="submit"') == 2
    assert 'class="button" type="submit" name="action" value="edit_approve"' in html


def test_a_failed_step_keeps_the_model_panel_and_shows_a_critical_callout(admin_client, run):
    step = run.steps.get(key="research")
    step.status, step.error = StepRun.Status.FAILED, "The model timed out."
    step.save()
    html = _page(admin_client, run, "research")
    assert 'id="regen-model"' in html and "s-callout--critical" in html


def test_the_step_list_is_grouped_and_numbered(admin_client, run):
    _ready(run, "outline", "# Outline\n\nH2: First\n")
    html = _page(admin_client, run, "outline")
    assert '<h3 class="s-phase"' in html and ">Plan</h3>" in html and ">Write</h3>" in html
    active = [s for s in run.steps.all() if s.status != StepRun.Status.SKIPPED]
    number = [s.key for s in active].index("outline") + 1
    assert f"step {number} of {len(active)}" in html, html[html.index('id="step-head"') :][:300]


def test_an_approved_step_points_to_the_next_one(admin_client, run):
    step = _ready(run, "research", "# Research\n\nNotes.\n")
    step.status = StepRun.Status.APPROVED
    step.save()
    html = _page(admin_client, run, "research")
    assert "Research is approved." in html and "Go to outline" in html


def test_the_page_never_reloads_over_unsaved_typing():
    from pathlib import Path

    text = (Path(__file__).parent.parent / "apps/studio/templates/studio/run_workspace.html").read_text(
        encoding="utf-8"
    )
    assert "data-reload-note" in text and "if (!unsaved()) { window.location.reload(); return; }" in text


def test_the_briefs_list_opens_the_wizard_instead_of_starting_a_run(admin_client, run):
    brief = run.brief
    html = admin_client.get(reverse("studio:briefs")).content.decode()
    assert f'href="/admin/studio/briefs/{brief.pk}/edit/?start=1#start"' in html
    assert 'name="mode" value="autopilot">Autopilot' not in html  # no one-click run any more
    wizard = admin_client.get(reverse("studio:brief_edit", args=[brief.pk]) + "?mode=autopilot&start=1")
    page = wizard.content.decode()
    assert 'value="autopilot" checked' in page and ">Start a new run</button>" in page
    assert "data-run-estimate" in page


def test_the_wizard_folds_the_advanced_parts(admin_client):
    html = admin_client.get(reverse("studio:brief_new")).content.decode()
    assert "Reader and length" in html and "Advanced: models and approvals" in html
    assert 'form="sheet-row-form"' in html and 'id="sheet-row-form"' in html
    assert html.index("How should it run?") < html.index('name="topic"')
