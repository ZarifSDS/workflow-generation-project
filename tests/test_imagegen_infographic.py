"""Infographics in the Image generator and the article planner (apps/studio/imagegen.py,
apps/quality/infographic.py): the planner's photo-or-infographic choice, specs written from a description,
the template checks, and redrawing with edited content."""

import copy
import json

import pytest
from django.urls import reverse

from apps.ai.types import GenerationResult
from apps.quality import infographic
from apps.quality.infographic_examples import EXAMPLES
from apps.studio import executors, imagegen
from apps.studio.models import ImageJob, ImagePlan

pytestmark = pytest.mark.django_db

LOGO = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1503.89 500.91">'
    '<rect fill="#626df9" width="1503.89" height="500.91"/></svg>'
)
ARTICLE = """# Safe System of Work: How to Create One

A safe system of work is a planned way of doing a risky task.

## How to Create a Safe System of Work

Assess the task and its hazards, decide how to control each hazard, write down the safe method, train and
brief the people who do it, then monitor and review it.

## Why Systems Fail

Hallowell (2021) found that 45% of hazards are spotted in the pre-job briefing, 35% are missed through blind
spots and 20% can't be seen until work starts.

## Frequently Asked Questions

### Is a safe system of work a legal requirement?

Yes, under the Health and Safety at Work Act.
"""
STEPS_SPEC = {
    "title": "How to create a safe system of work",
    "steps": [
        {"title": "Assess the task"},
        {"title": "Decide the controls"},
        {"title": "Write the method"},
        {"title": "Train and brief"},
        {"title": "Monitor and review"},
    ],
}
SHARES_SPEC = {
    "title": "Most hazards are missed before work starts",
    "segments": [
        {"value": 45, "label": "Spotted in the briefing"},
        {"value": 35, "label": "Missed through blind spots"},
        {"value": 20, "label": "Seen once work starts"},
    ],
    "source": "Hallowell, Professional Safety, 2021",
}


@pytest.fixture(autouse=True)
def _setup(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = tmp_path
    logo = tmp_path / "logo.svg"
    logo.write_text(LOGO, encoding="utf-8")
    monkeypatch.setattr(infographic, "LOGO", logo)
    infographic._logo_markup.cache_clear()
    yield
    infographic._logo_markup.cache_clear()


@pytest.fixture
def model(monkeypatch):
    """Answers the planner and the spec writer; records every prompt."""
    calls = {"prompts": [], "plan": None, "spec": STEPS_SPEC}

    def generate(provider, model, messages, options):
        user = messages[-1]["content"]
        calls["prompts"].append(user)
        if isinstance(user, str) and "Plan the visuals for this article" in user:
            text = json.dumps(calls["plan"])
        else:
            text = json.dumps(calls["spec"])
        return GenerationResult(provider=provider, model=model, text=text, output_tokens=60, total_time=0.1)

    monkeypatch.setattr(executors, "generate", generate)
    return calls


def _job(admin_user, **fields):
    job = ImageJob.objects.create(kind="infographic", created_by=admin_user, **fields)
    imagegen.execute(job.pk)
    job.refresh_from_db()
    return job


def test_a_given_spec_is_drawn_without_a_model(admin_user, model, admin_client):
    job = _job(admin_user, template="steps", spec=EXAMPLES["steps"])
    assert job.status == ImageJob.Status.DONE, job.error
    assert model["prompts"] == []
    assert job.image.width == 1600 and job.image.description == job.metrics["alt_text"]
    assert job.metrics["files"]["svg"].endswith(".svg") and not job.needs_a_look
    page = admin_client.get(reverse("studio:image_job", args=[job.pk]))
    assert "Infographic: Numbered steps" in page.text and "SVG (editable)" in page.text
    assert "WebP (1200" in page.text and "Redraw with this content" in page.text
    svg = admin_client.get(reverse("studio:image_job_download", args=[job.pk, "svg"]))
    assert svg.status_code == 200 and b"<svg" in svg.content


def test_a_spec_is_written_from_the_description_and_its_figures_checked(admin_user, model):
    model["spec"] = SHARES_SPEC
    description = "Hallowell 2021: 45% spotted in the briefing, 35% missed through blind spots."
    job = _job(admin_user, template="part_to_whole", description=description)
    assert "Template: part_to_whole" in model["prompts"][0] and description in model["prompts"][0]
    # The 20% isn't in the description, so the model invented it: not drawn, and said why.
    assert (
        job.image is None
        and job.needs_a_look
        and job.metrics["spec_source"] == "written from the description"
    )
    assert any("Not in your description: 20" in flag for flag in job.flags)
    job2 = _job(admin_user, template="part_to_whole", description=description + " 20% seen once work starts.")
    assert job2.image is not None, job2.flags


def test_the_planner_offers_infographics_with_their_checks(admin_user, model, admin_client):
    shares_wrong = copy.deepcopy(SHARES_SPEC)
    shares_wrong["segments"][0]["value"] = 50
    model["plan"] = {
        "ideas": [
            {"kind": "hero", "description": "A supervisor briefs a crew beside a machine.", "why": "Topic"},
            {
                "kind": "infographic",
                "section": "How to Create a Safe System of Work",
                "template": "steps",
                "spec": STEPS_SPEC,
                "description": "The five steps",
                "why": "Shows the order",
            },
            {
                "kind": "infographic",
                "section": "Why Systems Fail",
                "template": "part_to_whole",
                "spec": shares_wrong,
                "description": "Where hazards are caught",
                "why": "The cited shares",
            },
            {
                "kind": "infographic",
                "section": "Why Systems Fail",
                "template": "pie",
                "spec": {},
                "description": "Not a template",
                "why": "",
            },
        ],
        "not_photos": [],
    }
    plan = ImagePlan.objects.create(article_text=ARTICLE, created_by=admin_user)
    imagegen.execute_plan(plan.pk)
    plan.refresh_from_db()
    assert plan.status == "ready", plan.error
    assert "steps (Numbered steps)" in model["prompts"][0]  # the template guide reached the planner
    kinds = [(i["kind"], i.get("template"), i.get("passes")) for i in plan.ideas]
    assert kinds == [
        ("hero", None, None),
        ("infographic", "steps", True),
        ("infographic", "part_to_whole", False),
    ]
    assert any("add up to 105%" in c for c in plan.ideas[2]["checks"])
    page = admin_client.get(reverse("studio:image_plan", args=[plan.pk]))
    assert "Infographic (Numbered steps)" in page.text and "Passes its checks" in page.text
    assert "Needs edits" in page.text and "Edit the content</summary>" in page.text
    # Make the steps one, with an edited title; its figures are checked against the article.
    edited = dict(STEPS_SPEC, title="Five steps to a safe system of work")
    admin_client.post(
        reverse("studio:image_plan", args=[plan.pk]),
        {"action": "make", "pick-1": "1", "description-1": "The five steps", "spec-1": json.dumps(edited)},
    )
    job = ImageJob.objects.get(kind="infographic")
    assert (job.template, job.section, job.plan) == ("steps", "How to Create a Safe System of Work", plan)
    assert job.spec["title"] == "Five steps to a safe system of work"
    imagegen.execute(job.pk)
    job.refresh_from_db()
    assert job.image is not None, job.flags


def test_a_planned_chart_must_use_the_articles_figures(admin_user, model):
    invented = copy.deepcopy(SHARES_SPEC)
    invented["segments"][0]["value"], invented["segments"][1]["value"] = 40, 40
    model["plan"] = {
        "ideas": [
            {
                "kind": "infographic",
                "section": "Why Systems Fail",
                "template": "part_to_whole",
                "spec": invented,
                "description": "Shares",
                "why": "",
            }
        ],
    }
    plan = ImagePlan.objects.create(article_text=ARTICLE, created_by=admin_user)
    imagegen.execute_plan(plan.pk)
    plan.refresh_from_db()
    idea = next(i for i in plan.ideas if i["kind"] == "infographic")
    assert not idea["passes"] and any("Not in the article: 40" in c for c in idea["checks"])


def test_redraw_with_edited_content_and_invalid_json(admin_user, model, admin_client):
    job = _job(admin_user, template="steps", spec=STEPS_SPEC, description="The five steps")
    url = reverse("studio:image_job", args=[job.pk])
    bad = admin_client.post(url, {"action": "redraw", "spec": "{not json"}, follow=True)
    assert "valid JSON" in bad.text and ImageJob.objects.count() == 1
    edited = dict(STEPS_SPEC, title="Five steps")
    response = admin_client.post(url, {"action": "redraw", "spec": json.dumps(edited)})
    new = ImageJob.objects.exclude(pk=job.pk).get()
    assert response["Location"] == reverse("studio:image_job", args=[new.pk])
    assert (new.kind, new.template, new.spec["title"]) == ("infographic", "steps", "Five steps")
    admin_client.post(url, {"action": "rewrite"})
    rewrite = ImageJob.objects.order_by("-pk").first()
    assert rewrite.spec == {} and rewrite.description == "The five steps"  # the model writes it again


def test_the_generator_form_takes_an_infographic(admin_client):
    url = reverse("studio:images")
    missing = admin_client.post(
        url, {"kind": "infographic", "region": "US", "corner": "auto", "description": "x"}
    )
    assert "Choose the infographic" in missing.text
    bad = admin_client.post(
        url,
        {"kind": "infographic", "template": "steps", "region": "US", "corner": "auto", "spec_json": "[1]"},
    )
    assert "one JSON object" in bad.text
    ok = admin_client.post(
        url,
        {
            "kind": "infographic",
            "template": "steps",
            "region": "US",
            "corner": "auto",
            "spec_json": json.dumps(STEPS_SPEC),
        },
    )
    job = ImageJob.objects.get()
    assert ok["Location"] == reverse("studio:image_job", args=[job.pk])
    assert job.spec == STEPS_SPEC and job.template == "steps"


# ---- The form editor ----


def test_the_editor_schema_covers_every_template_and_example():
    for kind, (_, lists, required, _) in infographic.TEMPLATES.items():
        fields = {f["key"]: f for f in infographic.EDITOR_SCHEMA[kind]}
        assert set(EXAMPLES[kind]) <= set(fields), kind  # every example field can be edited
        for name in [*required, *lists]:
            assert fields[name].get("required") or fields[name]["type"] == "list", (kind, name)
        for name, (low, high) in lists.items():
            assert (fields[name]["min"], fields[name]["max"]) == (low, high), (kind, name)
            sub = {f["key"] for f in fields[name]["fields"]}
            for item in EXAMPLES[kind][name]:
                assert set(item) <= sub, (kind, name, item)


def test_the_preview_draws_without_making_a_job(admin_client, admin_user):
    url = reverse("studio:infographic_preview")
    ok = admin_client.post(url, {"template": "steps", "spec": STEPS_SPEC}, content_type="application/json")
    data = ok.json()
    assert ok.status_code == 200 and data["image"].startswith("data:image/webp;base64,")
    assert data["blocked"] is False and data["alt"] and not ImageJob.objects.exists()
    bad = admin_client.post(url, {"template": "pie", "spec": STEPS_SPEC}, content_type="application/json")
    assert bad.status_code == 400 and "template" in bad.json()["error"]
    empty = admin_client.post(url, {"template": "steps", "spec": {}}, content_type="application/json")
    assert "Fill in the content" in empty.json()["error"]
    # With a plan, figures are checked against its article.
    plan = ImagePlan.objects.create(article_text=ARTICLE, created_by=admin_user)
    shares = copy.deepcopy(SHARES_SPEC)
    shares["segments"][0]["value"], shares["segments"][1]["value"] = 40, 40
    checked = admin_client.post(
        url, {"template": "part_to_whole", "spec": shares, "plan": plan.pk}, content_type="application/json"
    ).json()
    assert checked["blocked"] and any("Not in the article: 40" in p["text"] for p in checked["problems"])


def test_the_preview_needs_writing_rights(client, django_user_model):
    from django.contrib.auth.models import Permission

    user = django_user_model.objects.create_user("viewer", password="x")
    user.user_permissions.add(
        Permission.objects.get(codename="access_admin"), Permission.objects.get(codename="access_studio")
    )
    client.force_login(user)
    response = client.post(
        reverse("studio:infographic_preview"),
        {"template": "steps", "spec": STEPS_SPEC},
        content_type="application/json",
    )
    assert response.status_code == 403


def test_the_editor_is_on_the_job_plan_and_generator_pages(admin_user, model, admin_client):
    job = _job(admin_user, template="steps", spec=STEPS_SPEC)
    page = admin_client.get(reverse("studio:image_job", args=[job.pk])).text
    assert 'data-target="again-spec"' in page and 'data-template="steps"' in page
    assert 'id="infographic-schema"' in page and "studio/infographic_editor.js" in page
    plan = ImagePlan.objects.create(
        article_text=ARTICLE,
        created_by=admin_user,
        status="ready",
        ideas=[
            {
                "kind": "infographic",
                "section": "How to Create a Safe System of Work",
                "template": "steps",
                "template_label": "Numbered steps",
                "spec": STEPS_SPEC,
                "description": "Steps",
                "passes": True,
            }
        ],
    )
    page = admin_client.get(reverse("studio:image_plan", args=[plan.pk])).text
    assert 'data-target="spec-0"' in page and f'data-plan="{plan.pk}"' in page and 'id="spec-0"' in page
    page = admin_client.get(reverse("studio:images") + "?tab=single").text
    assert 'data-target="id_spec_json"' in page and 'data-template-select="id_template"' in page


def test_the_editor_script_waits_for_the_page():
    from pathlib import Path

    script = (Path(__file__).parent.parent / "apps/studio/static/studio/infographic_editor.js").read_text(
        "utf-8"
    )
    assert "DOMContentLoaded" in script
