"""M9 phase 4: saving edits as versions, approving with a base version, and the view actions."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse

from apps.studio import services
from apps.studio.models import ContentBrief, StepRun

pytestmark = pytest.mark.django_db

TEXT = "# Draft\n\nFirst text."


@pytest.fixture
def run(admin_user):
    brief = ContentBrief.objects.create(
        topic="SDS retention", pkeyword="sds retention", created_by=admin_user
    )
    run = services.create_run(brief, {}, user=admin_user)
    for key in ("draft", "review_edit"):
        step = run.steps.get(key=key)
        services.add_version(step, TEXT)
        step.status = StepRun.Status.READY
        step.save()
    return run


def _user(name, *groups):
    user = get_user_model().objects.create_user(name, password="unused-test-password")
    for group in groups:
        user.groups.add(Group.objects.get(name=group))
    return user


def _csrf_client(user):
    """A client that enforces CSRF like a browser, with the token taken from the workspace page."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    return client


def _post(client, run, data):
    url = reverse("studio:run", args=[run.pk])
    page = client.get(f"{url}?step={data['step']}")
    data = {**data, "csrfmiddlewaretoken": page.context["csrf_token"]}
    return client.post(url, data)


# ---- services.save_edit ----


def test_save_edit_adds_an_edit_version_without_approving(run, admin_user):
    step = run.steps.get(key="draft")
    version = services.save_edit(step, admin_user, "# Draft\r\n\r\nBetter text.", base_version=1)
    step.refresh_from_db()
    assert version.number == 2 and version.source == "edit" and version.created_by == admin_user
    assert version.content == "# Draft\n\nBetter text."  # CRLF from the browser normalised
    assert step.status == StepRun.Status.READY


def test_save_edit_unchanged_is_a_no_op(run, admin_user):
    step = run.steps.get(key="draft")
    assert services.save_edit(step, admin_user, TEXT + "\n", base_version=1) is None
    assert step.versions.count() == 1


def test_save_edit_refuses_a_stale_base(run, admin_user):
    step = run.steps.get(key="draft")
    services.add_version(step, "# Draft\n\nSomeone else's text.")
    with pytest.raises(ValueError, match="Version 2 was saved after you opened version 1"):
        services.save_edit(step, admin_user, "# Draft\n\nMine.", base_version=1)
    assert step.versions.count() == 2


def test_save_edit_only_when_ready_and_not_empty(run, admin_user):
    step = run.steps.get(key="draft")
    with pytest.raises(ValueError, match="empty"):
        services.save_edit(step, admin_user, "  \n", base_version=1)
    step.status = StepRun.Status.APPROVED
    step.save()
    with pytest.raises(ValueError, match="ready for review"):
        services.save_edit(step, admin_user, "# New", base_version=1)


def test_approve_refuses_a_stale_base(run, admin_user):
    step = run.steps.get(key="draft")
    services.add_version(step, "# Draft\n\nNewer.")
    with pytest.raises(ValueError, match="was saved after"):
        services.approve_step(step, admin_user, base_version=1)
    services.approve_step(step, admin_user, base_version=2)
    step.refresh_from_db()
    assert step.status == StepRun.Status.APPROVED


# ---- views (CSRF enforced) ----


def test_writer_saves_a_version_of_a_writing_step(run):
    client = _csrf_client(_user("writer", "Writers"))
    response = _post(
        client,
        run,
        {"step": "draft", "action": "save_version", "content": "# Draft\n\nMine.", "base_version": 1},
    )
    assert response.status_code == 302
    step = run.steps.get(key="draft")
    assert step.latest_version.number == 2 and step.status == StepRun.Status.READY


def test_writer_cannot_save_a_version_of_an_editing_step(run):
    client = _csrf_client(_user("writer", "Writers"))
    _post(
        client,
        run,
        {"step": "review_edit", "action": "save_version", "content": "# Mine", "base_version": 1},
    )
    assert run.steps.get(key="review_edit").versions.count() == 1


def test_edit_approve_view_saves_and_approves(run):
    client = _csrf_client(_user("editor", "Editors"))
    response = _post(
        client,
        run,
        {"step": "draft", "action": "edit_approve", "content": "# Draft\n\nEdited.", "base_version": 1},
    )
    step = run.steps.get(key="draft")
    assert response.status_code == 302
    assert step.status == StepRun.Status.APPROVED
    assert step.latest_version.content == "# Draft\n\nEdited."


def test_stale_edit_approve_shows_the_conflict(run):
    client = _csrf_client(_user("editor", "Editors"))
    services.add_version(run.steps.get(key="draft"), "# Draft\n\nNewer.")
    response = _post(
        client, run, {"step": "draft", "action": "edit_approve", "content": "# Mine", "base_version": 1}
    )
    step = run.steps.get(key="draft")
    assert step.status == StepRun.Status.READY and step.latest_version.content == "# Draft\n\nNewer."
    page = client.get(response.url)
    assert "was saved after you opened version 1" in page.text


def test_post_without_csrf_token_is_refused(run):
    client = _csrf_client(_user("editor", "Editors"))
    url = reverse("studio:run", args=[run.pk])
    response = client.post(
        url, {"step": "draft", "action": "save_version", "content": "# X", "base_version": 1}
    )
    assert response.status_code == 403


# ---- the workspace page wires up the editor ----


def test_workspace_offers_the_editor_on_text_steps(run, admin_client):
    from django.core.files.base import ContentFile
    from wagtail.images import get_image_model

    image = get_image_model().objects.create(
        title="Panel",
        file=ContentFile(
            b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"></svg>', name="panel.svg"
        ),
    )
    step = run.steps.get(key="draft")
    services.add_version(step, f'# Draft\n\n![Panel](wagtail://image?id={image.pk} "Caption")\n')
    html = admin_client.get(reverse("studio:run", args=[run.pk]) + "?step=draft").text
    assert "studio/editor/editor.js" in html and "studio/editor/editor.css" in html
    assert f'data-autosave-key="studio:draft:{run.pk}:draft:2"' in html
    assert html.count('name="base_version" value="2"') == 2  # approve and edit forms
    assert 'value="save_version"' in html and 'value="edit_approve"' in html
    assert "data-editor-open" in html
    # Preview data for the editor (the same shape as the editor's refs endpoint)
    import json
    import re

    refs = json.loads(
        re.search(r'id="editor-refs" type="application/json">(.*?)</script>', html, re.S).group(1)
    )
    assert refs["images"][str(image.pk)]["url"].startswith("/media/images/panel")
    assert refs["images"][str(image.pk)]["ref"] == f"wagtail://image?id={image.pk}"


def _has_editor(client, run, key):
    html = client.get(reverse("studio:run", args=[run.pk]) + f"?step={key}").text
    return "studio/editor/editor.js" in html or "data-editor-form" in html


def test_no_editor_for_the_hero_image(run, admin_client):
    hero = run.steps.get(key="hero_image")
    services.add_version(hero, "Branded hero.")
    hero.status = StepRun.Status.READY
    hero.save()
    assert not _has_editor(admin_client, run, "hero_image")


def test_no_editor_on_steps_you_cant_review(run, client):
    client.force_login(_user("writer", "Writers"))
    assert _has_editor(client, run, "draft")
    assert not _has_editor(client, run, "review_edit")  # an editing step: editors only


def test_approved_steps_clear_drafts_kept_in_the_browser(run, admin_client):
    services.approve_step(run.steps.get(key="draft"), get_user_model().objects.get(username="admin"))
    html = admin_client.get(reverse("studio:run", args=[run.pk]) + "?step=draft").text
    assert f'data-editor-clear="{run.pk}:draft"' in html
