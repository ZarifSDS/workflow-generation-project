import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.studio import services
from apps.studio.models import ContentBrief, GenerationRun, MetadataOption, StepRun

pytestmark = pytest.mark.django_db


@pytest.fixture
def brief(admin_user):
    return ContentBrief.objects.create(
        topic="How long to keep Safety Data Sheets",
        pkeyword="SDS retention requirements",
        skeywords=["how long to keep safety data sheets"],
        wordcount=1800,
        fkgl=9,
        region="US",
        content_type="seo_blog",
        created_by=admin_user,
    )


def make_ready(step, text="# SDS retention requirements\n\nSDS retention requirements are set by OSHA."):
    services.add_version(step, text, provider="ollama_cloud", model="gpt-oss:120b")
    step.status = StepRun.Status.READY
    step.save()
    services.refresh_run_status(step.run)
    return step


# ---- Health and navigation ----


def test_healthz_reports_database_ok(client):
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_dashboard_requires_login(client):
    response = client.get(reverse("studio:dashboard"))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_every_screen_renders(admin_client, admin_user):
    call_command("studio_demo")
    run = GenerationRun.objects.filter(status=GenerationRun.Status.NEEDS_REVIEW).first()
    urls = [
        reverse("studio:dashboard"),
        reverse("studio:briefs"),
        reverse("studio:brief_new"),
        reverse("studio:brief_edit", args=[run.brief_id]),
        reverse("studio:runs"),
        reverse("studio:run", args=[run.pk]),
        reverse("studio:metadata", args=[run.pk]),
        reverse("studio:compare", args=[run.pk, "outline", 1, 2]),
        reverse("studio:providers"),
        reverse("studio_presets:index"),
    ]
    for url in urls:
        assert admin_client.get(url).status_code == 200, url


def test_sidebar_badge_counts_steps_waiting_for_review(admin_client, brief):
    run = services.create_run(brief, {})
    make_ready(run.steps.get(key="research"))
    response = admin_client.get(reverse("wagtailadmin_home"))
    assert b"Content Studio (1)" in response.content


# ---- Runs and steps ----


def test_create_run_uses_pipeline_and_profile_defaults(brief, settings):
    run = services.create_run(brief, {"localise": {"enabled": False}})
    keys = list(run.steps.values_list("key", flat=True))
    assert keys[:2] == ["search_results", "research"] and "site_crawl" not in keys
    assert run.steps.get(key="search_results").status == StepRun.Status.SKIPPED  # off in these tests
    first = run.steps.get(key="research")
    assert first.status == StepRun.Status.QUEUED
    assert first.model == settings.AI_PROFILES["fast"]["model"]
    assert run.steps.get(key="localise").status == StepRun.Status.SKIPPED


def test_guest_posts_start_with_site_crawl(brief):
    brief.content_type = "outbound"
    brief.save()
    run = services.create_run(brief, {})
    assert list(run.steps.order_by("order").values_list("key", flat=True)[:2]) == [
        "search_results",
        "site_crawl",
    ]


def test_approve_queues_next_step_and_edit_creates_version(brief, admin_user):
    run = services.create_run(brief, {})
    research = make_ready(run.steps.get(key="research"))
    services.approve_step(research, admin_user, edited_content="# Edited\n\nMy own research notes.")
    research.refresh_from_db()
    assert research.status == StepRun.Status.APPROVED
    assert research.latest_version.source == "edit"
    assert run.steps.get(key="outline").status == StepRun.Status.QUEUED


def test_versions_keep_first_and_last_three(brief):
    run = services.create_run(brief, {})
    step = run.steps.get(key="outline")
    for n in range(6):
        services.add_version(step, f"# Version {n + 1}\n\nText.")
    assert list(step.versions.values_list("number", flat=True)) == [1, 4, 5, 6]


def test_regenerate_refuses_unavailable_models(brief):
    run = services.create_run(brief, {})
    step = run.steps.get(key="research")
    with pytest.raises(ValueError):
        services.request_regenerate(step, "ollama_cloud::kimi-k3")
    services.request_regenerate(step, "gemini::gemini-3.7-flash", note="Shorter")
    step.refresh_from_db()
    assert (step.provider, step.model, step.status) == ("gemini", "gemini-3.7-flash", StepRun.Status.QUEUED)


def test_workspace_actions(admin_client, brief):
    run = services.create_run(brief, {})
    make_ready(run.steps.get(key="research"))
    url = reverse("studio:run", args=[run.pk])
    response = admin_client.post(url, {"step": "research", "action": "approve"})
    assert response.status_code == 302
    assert run.steps.get(key="research").status == StepRun.Status.APPROVED

    response = admin_client.post(url, {"step": "outline", "action": "reject", "reason": "Wrong angle"})
    run.refresh_from_db()
    assert run.status == GenerationRun.Status.REJECTED and run.reject_reason == "Wrong angle"


def test_model_output_is_sanitised(admin_client, brief):
    run = services.create_run(brief, {})
    make_ready(
        run.steps.get(key="research"), "# Title\n\n<script>alert(1)</script> <img src=x onerror=alert(2)>"
    )
    response = admin_client.get(reverse("studio:run", args=[run.pk]) + "?step=research")
    html = response.content.decode()
    rendered = html.split('class="s-output" data-editor-output>', 1)[1].split("</div>", 1)[0]
    assert "<script" not in rendered and "<img" not in rendered and "onerror" not in rendered
    assert "<script>alert(1)" not in html  # only ever present escaped, e.g. in the edit textarea


# ---- Wizard ----


def test_wizard_starts_a_run_with_chosen_models(admin_client):
    data = {
        "content_type": "lead_magnet",
        "topic": "SDS compliance checklist",
        "pkeyword": "SDS compliance checklist",
        "skeywords_text": "chemical register",
        "fkgl": "9",
        "region": "AU",
        "comprehension": "practitioner",
        "cta_style": "button",
        "action": "start",
        "step_research_model": "groq::openai/gpt-oss-120b",
        "step_research_gate": "on",
        "step_draft_model": "ollama_cloud::kimi-k3",  # paid: must be ignored
    }
    response = admin_client.post(reverse("studio:brief_new"), data)
    assert response.status_code == 302
    run = GenerationRun.objects.get()
    assert run.brief.skeywords == ["chemical register"]
    assert run.steps.get(key="research").model == "openai/gpt-oss-120b"
    assert run.steps.get(key="draft").model != "kimi-k3"


def test_wizard_requires_site_url_for_guest_posts(admin_client):
    data = {
        "content_type": "outbound",
        "topic": "Labelling",
        "pkeyword": "labelling",
        "fkgl": "8",
        "region": "UK",
        "comprehension": "practitioner",
        "cta_style": "none",
        "action": "start",
    }
    response = admin_client.post(reverse("studio:brief_new"), data)
    assert response.status_code == 200
    assert b"target site" in response.content
    assert not GenerationRun.objects.exists()


def test_wizard_saves_preset(admin_client):
    data = {
        "content_type": "seo_blog",
        "topic": "x",
        "pkeyword": "x",
        "fkgl": "9",
        "region": "UK",
        "comprehension": "practitioner",
        "cta_style": "subtle",
        "action": "save_preset",
        "preset_name": "SDS blog UK",
        "step_draft_model": "gemini::gemini-3.8-flash",
    }
    admin_client.post(reverse("studio:brief_new"), data)
    from apps.studio.models import BriefPreset

    preset = BriefPreset.objects.get(name="SDS blog UK")
    assert preset.region == "UK" and preset.step_models["draft"] == "gemini::gemini-3.8-flash"


# ---- Title and meta ----


def test_metadata_add_own_and_select(admin_client, brief):
    run = services.create_run(brief, {})
    first = MetadataOption.objects.create(run=run, kind="title", text="SDS Retention Requirements Guide")
    url = reverse("studio:metadata", args=[run.pk])
    admin_client.post(url, {"action": "add", "kind": "title", "own_title": "  My own   title  "})
    own = run.metadata_options.get(source="edit")
    assert own.text == "My own title" and own.selected
    admin_client.post(url, {"action": "save", "selected": [str(first.pk)]})
    own.refresh_from_db()
    first.refresh_from_db()
    assert first.selected and not own.selected
