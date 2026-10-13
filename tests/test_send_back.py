"""Sending a step back with feedback, and reopening a rejected run."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.studio import services
from apps.studio.models import ChatMessage, ContentBrief, GenerationRun, StepRun

pytestmark = pytest.mark.django_db

OUTLINE = "# Management of change\n\n## What MOC covers\n\nText about the scope of the procedure.\n"


@pytest.fixture
def run(admin_user):
    brief = ContentBrief.objects.create(
        topic="Management of change safety", pkeyword="moc", content_type="seo_blog"
    )
    run = services.create_run(brief, {})
    research = run.steps.get(key="research")
    research.status = StepRun.Status.APPROVED
    research.save()
    outline = run.steps.get(key="outline")
    services.add_version(outline, OUTLINE, provider="ollama_cloud", model="gpt-oss:120b")
    outline.status = StepRun.Status.READY
    outline.provider, outline.model = "ollama_cloud", "gpt-oss:120b"
    outline.save()
    services.refresh_run_status(run)
    return run


def _url(run, step="outline"):
    return reverse("studio:run", args=[run.pk]) + f"?step={step}"


def test_send_back_regenerates_with_feedback_and_chosen_model(admin_client, run):
    response = admin_client.post(
        _url(run),
        {
            "step": "outline",
            "action": "send_back",
            "how": "regenerate",
            "feedback": "Simpler, answer the searcher's question first.",
            "model": "groq::openai/gpt-oss-120b",
        },
    )
    assert response.status_code == 302
    outline = run.steps.get(key="outline")
    assert outline.status == StepRun.Status.QUEUED
    assert (outline.provider, outline.model) == ("groq", "openai/gpt-oss-120b")
    assert outline.regenerate_note == "Simpler, answer the searcher's question first."


def test_send_back_as_targeted_edits_uses_the_chat(admin_client, run):
    admin_client.post(
        _url(run),
        {"step": "outline", "action": "send_back", "how": "edit", "feedback": "Cut the software section."},
    )
    reply = ChatMessage.objects.get(step__run=run, role="assistant")
    assert reply.action == ChatMessage.Action.APPLY and reply.status == ChatMessage.Status.PENDING
    assert run.steps.get(key="outline").status == StepRun.Status.READY


def test_send_back_needs_feedback(admin_client, run):
    response = admin_client.post(
        _url(run), {"step": "outline", "action": "send_back", "how": "regenerate"}, follow=True
    )
    assert "Say what should change" in response.content.decode()
    assert run.steps.get(key="outline").status == StepRun.Status.READY


def test_rejected_run_can_be_reopened_and_regenerated_with_the_reason(admin_client, run, admin_user):
    services.reject_run(run, admin_user, "Readers want simpler, query-first articles.")
    html = admin_client.get(reverse("studio:run", args=[run.pk])).content.decode()
    assert "Reopen and regenerate outline with this feedback" in html  # the rejected step is selected

    admin_client.post(
        _url(run), {"step": "outline", "action": "reopen_regenerate", "model": "ollama_cloud::gpt-oss:120b"}
    )
    run.refresh_from_db()
    outline = run.steps.get(key="outline")
    assert run.status != GenerationRun.Status.REJECTED and run.reject_reason == ""
    assert outline.status == StepRun.Status.QUEUED
    assert outline.regenerate_note == "Readers want simpler, query-first articles."


def test_reopen_only_restores_review(admin_client, run, admin_user):
    services.reject_run(run, admin_user, "Wrong angle")
    admin_client.post(_url(run), {"step": "outline", "action": "reopen"})
    run.refresh_from_db()
    assert run.status == GenerationRun.Status.NEEDS_REVIEW
    assert run.steps.get(key="outline").status == StepRun.Status.READY


def test_waiting_step_shows_no_duration_from_an_earlier_attempt(run):
    draft = run.steps.get(key="draft")
    draft.started_at = timezone.now() - timedelta(seconds=5)
    draft.finished_at = timezone.now()
    draft.status = StepRun.Status.PENDING
    assert draft.duration_seconds is None
    draft.status = StepRun.Status.FAILED
    assert draft.duration_seconds == 5
