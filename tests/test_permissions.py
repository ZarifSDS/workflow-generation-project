"""M8: Content Studio roles (Writers, Editors, Moderators, Operators)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from apps.studio import services
from apps.studio.models import ContentBrief, StepRun

pytestmark = pytest.mark.django_db


def _user(name, *groups):
    user = get_user_model().objects.create_user(name, password="unused-test-password")
    for group in groups:
        user.groups.add(Group.objects.get(name=group))
    return user


@pytest.fixture
def run(admin_user):
    brief = ContentBrief.objects.create(
        topic="SDS retention", pkeyword="sds retention", created_by=admin_user
    )
    run = services.create_run(brief, {}, user=admin_user)
    for key in ("draft", "review_edit"):
        step = run.steps.get(key=key)
        services.add_version(step, "# Draft\n\nText.")
        step.status = StepRun.Status.READY
        step.save()
    return run


def _client_for(client, *groups):
    client.force_login(_user("-".join(groups).lower() or "nobody", *groups))
    return client


def _denied(response):
    """Wagtail answers a denied admin request with a redirect to the dashboard (or a bare 403)."""
    return response.status_code == 403 or (
        response.status_code == 302 and response.url == reverse("wagtailadmin_home")
    )


def _approve(client, run, key):
    return client.post(reverse("studio:run", args=[run.pk]), {"step": key, "action": "approve"})


def test_groups_hold_the_role_permissions():
    def codes(name):
        return set(Group.objects.get(name=name).permissions.values_list("codename", flat=True))

    assert {"access_admin", "access_studio", "review_writing_steps"} <= codes("Writers")
    assert "review_editing_steps" not in codes("Writers")
    assert {"review_writing_steps", "review_editing_steps"} <= codes("Editors")
    assert {"access_studio"} <= codes("Moderators")
    assert not {"review_writing_steps", "review_editing_steps"} & codes("Moderators")
    assert {"operate_studio", "add_briefpreset", "change_briefpreset"} <= codes("Operators")


def test_writer_approves_writing_steps_only(client, run):
    client = _client_for(client, "Writers")
    _approve(client, run, "draft")
    assert run.steps.get(key="draft").status == StepRun.Status.APPROVED

    response = _approve(client, run, "review_edit")
    assert run.steps.get(key="review_edit").status == StepRun.Status.READY
    follow = client.get(response.url)
    assert "for editors." in follow.text

    page = client.get(reverse("studio:run", args=[run.pk]) + "?step=review_edit").text
    assert "Ready for review by editors" in page
    assert 'value="approve"' not in page
    assert _denied(client.get(reverse("studio:run_export", args=[run.pk, "md"])))


def test_editor_approves_editing_steps(client, run):
    client = _client_for(client, "Editors")
    _approve(client, run, "review_edit")
    assert run.steps.get(key="review_edit").status == StepRun.Status.APPROVED


def test_moderator_can_read_runs_but_not_act(client, run):
    client = _client_for(client, "Moderators")
    assert client.get(reverse("studio:run", args=[run.pk])).status_code == 200
    _approve(client, run, "draft")
    assert run.steps.get(key="draft").status == StepRun.Status.READY
    assert _denied(client.get(reverse("studio:brief_new")))
    assert "New brief" not in client.get(reverse("studio:dashboard")).text


def test_admin_user_without_studio_role_is_kept_out(client):
    user = _user("plain")
    user.user_permissions.add(Permission.objects.get(codename="access_admin"))
    client.force_login(user)
    assert _denied(client.get(reverse("studio:dashboard")))
    assert "Content Studio" not in client.get(reverse("wagtailadmin_home")).text


def test_only_operators_recheck_providers(client):
    writer = _client_for(client, "Writers")
    assert _denied(writer.post(reverse("studio:providers")))
    assert "Re-check providers" not in writer.get(reverse("studio:providers")).text


def test_operator_marks_a_stuck_step_failed(client, run):
    step = run.steps.get(key="research")
    step.status = StepRun.Status.RUNNING
    step.save()
    url = reverse("studio:run", args=[run.pk])

    writer = _client_for(client, "Writers")
    assert "Mark as failed" not in writer.get(url + "?step=research").text
    writer.post(url, {"step": "research", "action": "recover"})
    assert run.steps.get(key="research").status == StepRun.Status.RUNNING

    client.logout()
    operator = _client_for(client, "Operators")
    assert "Mark as failed" in operator.get(url + "?step=research").text
    operator.post(url, {"step": "research", "action": "recover"})
    step.refresh_from_db()
    assert step.status == StepRun.Status.FAILED
    assert "Marked as failed by operators" in step.error


def test_group_editor_lists_studio_permissions(admin_client):
    group = Group.objects.get(name="Writers")
    response = admin_client.get(reverse("wagtailusers_groups:edit", args=[group.pk]))
    assert response.status_code == 200
    assert "Can use Content Studio" in response.text
