"""Steps can't start before their input is approved, and step timers show real elapsed times."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.studio import services
from apps.studio.models import ContentBrief, StepRun
from apps.studio.tasks import execute_step
from apps.studio.templatetags.studio_tags import clock, took

pytestmark = pytest.mark.django_db


@pytest.fixture
def run(admin_user):
    brief = ContentBrief.objects.create(
        topic="Management of change safety", pkeyword="management of change", content_type="seo_blog"
    )
    return services.create_run(brief, {})


def _ready(step):
    services.add_version(
        step, "# Outline\n\n## Section\n\nText.", provider="ollama_cloud", model="gpt-oss:120b"
    )
    step.status = StepRun.Status.READY
    step.save()
    return step


# ---- Gating: the bug behind "Draft failed: Approve the outline before drafting" ----


def test_choosing_a_model_for_a_waiting_step_does_not_start_it(run):
    _ready(run.steps.get(key="research"))
    draft = run.steps.get(key="draft")
    services.request_regenerate(draft, "ollama_cloud::gpt-oss:120b")
    draft.refresh_from_db()
    assert draft.status == StepRun.Status.PENDING  # not queued: the outline isn't approved
    assert (draft.provider, draft.model) == ("ollama_cloud", "gpt-oss:120b")
    assert services.blocking_step(draft).key == "research"


def test_retrying_an_early_failure_waits_and_approval_starts_it(run, admin_user):
    research, outline, draft = (run.steps.get(key=k) for k in ("research", "outline", "draft"))
    research.status = StepRun.Status.APPROVED
    research.save()
    _ready(outline)
    draft.status, draft.error = StepRun.Status.FAILED, "Approve the outline before drafting."
    draft.save()

    services.retry_step(draft)
    draft.refresh_from_db()
    assert draft.status == StepRun.Status.PENDING and draft.error == ""

    services.approve_step(outline, admin_user)
    draft.refresh_from_db()
    assert draft.status == StepRun.Status.QUEUED and draft.queued_at is not None


def test_approving_the_input_restarts_a_failed_next_step(run, admin_user):
    research, outline = run.steps.get(key="research"), run.steps.get(key="outline")
    _ready(research)
    outline.status, outline.error = StepRun.Status.FAILED, "Approve the research before outlining."
    outline.save()
    services.approve_step(research, admin_user)
    outline.refresh_from_db()
    assert outline.status == StepRun.Status.QUEUED


def test_workspace_says_when_a_model_choice_waits(admin_client, run):
    url = reverse("studio:run", args=[run.pk])
    response = admin_client.post(
        url, {"step": "draft", "action": "regenerate", "model": "ollama_cloud::gpt-oss:120b"}, follow=True
    )
    assert "starts with this model once research is approved" in response.content.decode()


# ---- Timers ----


def test_clock_and_took_formats():
    assert clock(0) == "0:00" and clock(65) == "1:05" and clock(3725) == "1:02:05"
    assert took(9) == "9 s" and took(245) == "4 min 05 s" and took(3720) == "1 h 02 min"


def test_running_step_renders_its_real_elapsed_time(admin_client, run):
    step = run.steps.get(key="research")
    step.status, step.started_at = StepRun.Status.RUNNING, timezone.now() - timedelta(minutes=7, seconds=3)
    step.save()
    html = admin_client.get(reverse("studio:run", args=[run.pk]) + "?step=research").content.decode()
    # Rendered by the server, so a reload shows the time since the start, not 0:00.
    assert ">7:03<" in html or ">7:04<" in html
    assert step.started_at.astimezone(timezone.get_current_timezone()).strftime("%H:%M") in html


def test_queued_step_shows_time_in_queue(admin_client, run):
    step = run.steps.get(key="research")
    step.queued_at = timezone.now() - timedelta(seconds=90)
    step.save()
    html = admin_client.get(reverse("studio:run", args=[run.pk]) + "?step=research").content.decode()
    assert "Queued" in html and (">1:30<" in html or ">1:31<" in html)


def test_finished_step_records_how_long_it_took(run, monkeypatch):
    from apps.studio import executors

    step = run.steps.get(key="research")

    def slow_research(s):
        StepRun.objects.filter(pk=s.pk).update(started_at=timezone.now() - timedelta(seconds=125))
        s.started_at = timezone.now() - timedelta(seconds=125)
        return executors.StepOutput(content="# Research\n\nNotes.", provider="ollama", model="m")

    monkeypatch.setitem(executors.EXECUTORS, "research", slow_research)
    execute_step(step.pk)
    step.refresh_from_db()
    assert step.status == StepRun.Status.READY
    assert 124 <= step.duration_seconds <= 127
    assert 124 <= step.latest_version.metrics["duration_seconds"] <= 127
