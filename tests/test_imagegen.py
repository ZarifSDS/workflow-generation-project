"""The standalone Image generator (apps/studio/imagegen.py): one image without a brief."""

import io
import json

import httpx
import pytest
import respx
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.ai.types import GenerationResult, ImageResult
from apps.quality import hero
from apps.studio import executors, imagegen
from apps.studio.models import ContentBrief, GenerationRun, ImageJob

pytestmark = pytest.mark.django_db

VISION = {
    "subject": [0.6, 0.15, 0.85, 1.0],
    "person_at_left_edge": True,
    "facing": "left",
    "readable_text": [],
    "safety_issues": [],
    "scene": "warehouse aisle",
    "alt_text": "A warehouse worker reads a safety data sheet beside chemical drums.",
}


def _png(width=1440, height=816, colour=(215, 215, 215)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def fakes(monkeypatch):
    calls = {"prompts": [], "images": 0, "brand": [], "inner": [], "vision": dict(VISION)}

    def generate(provider, model, messages, options):
        if isinstance(messages[-1]["content"], list):
            calls["vision_prompt"] = messages[-1]["content"][0]["text"]
            text = json.dumps(calls["vision"])
        else:
            calls["prompts"].append(messages)
            text = "A warehouse worker reading an SDS binder, soft daylight, no text."
        return GenerationResult(provider=provider, model=model, text=text, output_tokens=40, total_time=0.1)

    def generate_image(provider, model, prompt, options):
        calls["images"] += 1
        calls["image_prompt"] = prompt
        return ImageResult(provider=provider, model=model, data=_png(), mime_type="image/png")

    def brand(photo, markup, vision):
        calls["brand"].append(markup)
        return hero.HeroResult(
            png=_png(1440, 810), webp=b"RIFF-webp", svg=b"<svg/>", metrics={"headline": markup}
        )

    def brand_inner(data, filename, corner="auto"):
        calls["inner"].append(corner)
        return data, {"corner": corner, "version": "regular"}

    monkeypatch.setattr(executors, "generate", generate)
    monkeypatch.setattr(imagegen, "generate_image", generate_image)
    monkeypatch.setattr(hero, "brand", brand)
    monkeypatch.setattr(hero, "brand_inner", brand_inner)
    return calls


def _job(admin_user, **fields):
    values = {"kind": "hero", "headline": "SDS Retention: How Long to Keep Them", "created_by": admin_user}
    job = ImageJob.objects.create(**{**values, **fields})
    imagegen.execute(job.pk)
    job.refresh_from_db()
    return job


def test_a_blog_hero_is_made_without_a_brief(admin_user, fakes):
    job = _job(admin_user, description="Keeping safety data sheets on file")
    assert job.status == ImageJob.Status.DONE, job.error
    assert fakes["brand"] == ["**SDS Retention:** | How Long to Keep Them"]
    assert job.image.description == VISION["alt_text"]
    assert job.metrics["files"]["webp"].endswith(".webp") and job.metrics["files"]["svg"].endswith(".svg")
    assert imagegen.file_bytes(job, "svg") == b"<svg/>"
    assert imagegen.file_bytes(job, "webp") == b"RIFF-webp"
    assert not job.needs_a_look
    # The blog hero's composition: subject in the right third, a veil over the left.
    prompt = fakes["prompts"][0][0]["content"] + fakes["prompts"][0][1]["content"]
    assert "right third" in prompt and "white veil" in fakes["vision_prompt"]
    assert not ContentBrief.objects.exists() and not GenerationRun.objects.exists()


def test_a_lead_image_is_unbranded_at_its_size(admin_user, fakes):
    job = _job(
        admin_user, kind="lead", headline="", description="SDS binder in a warehouse", width=1600, height=900
    )
    assert job.status == ImageJob.Status.DONE, job.error
    assert fakes["brand"] == [] and fakes["inner"] == []
    assert (job.image.width, job.image.height) == (1600, 900)
    webp = Image.open(io.BytesIO(imagegen.file_bytes(job, "webp")))
    assert webp.format == "WEBP" and webp.size == (1600, 900)
    assert "no veil, logo or headline is added" in fakes["prompts"][0][0]["content"]


def test_an_in_article_image_gets_the_logo_in_the_chosen_corner(admin_user, fakes):
    job = _job(admin_user, kind="inline", headline="", description="Chemical store", corner="br")
    assert job.status == ImageJob.Status.DONE, job.error
    assert fakes["inner"] == ["br"]
    assert (job.image.width, job.image.height) == imagegen.DEFAULT_SIZES[ImageJob.Kind.INLINE]
    assert job.metrics["logo"]["corner"] == "br"


def test_an_uploaded_photo_is_used_instead_of_generating(admin_user, fakes, admin_client):
    upload = SimpleUploadedFile("drums.png", _png(2000, 1125, (180, 180, 180)), content_type="image/png")
    response = admin_client.post(
        reverse("studio:images"),
        {"kind": "lead", "region": "US", "corner": "auto", "upload": upload},
    )
    job = ImageJob.objects.get()
    assert response.status_code == 302 and response["Location"] == reverse("studio:image_job", args=[job.pk])
    assert job.source is not None and job.status == ImageJob.Status.QUEUED
    imagegen.execute(job.pk)
    job.refresh_from_db()
    assert job.status == ImageJob.Status.DONE, job.error
    assert fakes["images"] == 0 and fakes["prompts"] == []  # no prompt and no generated photo
    assert job.photo == job.source and (job.image.width, job.image.height) == hero.DEFAULT_HOST_SIZE


def test_readable_text_marks_the_image_for_a_look(admin_user, fakes):
    fakes["vision"]["readable_text"] = [{"text": "brand name on a drum", "box": [0.7, 0.5, 0.8, 0.6]}]
    fakes["vision"]["safety_issues"] = [{"issue": "no gloves while decanting", "severity": "high"}]
    job = _job(admin_user, kind="lead", headline="", description="Decanting solvent")
    assert job.needs_a_look
    assert "Readable text or logo in the photo: brand name on a drum" in job.flags
    assert "Safety: no gloves while decanting" in job.flags


def test_the_same_photo_can_take_a_new_headline(admin_user, fakes, admin_client):
    job = _job(admin_user, description="Keeping safety data sheets on file")
    response = admin_client.post(
        reverse("studio:image_job", args=[job.pk]), {"action": "same_photo", "headline": "SDS Rules: Short"}
    )
    new = ImageJob.objects.exclude(pk=job.pk).get()
    assert response["Location"] == reverse("studio:image_job", args=[new.pk])
    assert new.source == job.photo and new.headline == "SDS Rules: Short"
    imagegen.execute(new.pk)
    assert fakes["images"] == 1 and fakes["brand"][-1] == "**SDS Rules:** | Short"


def test_the_form_asks_for_something_to_work_from(admin_client):
    response = admin_client.post(reverse("studio:images"), {"kind": "lead", "region": "US", "corner": "auto"})
    assert response.status_code == 200 and not ImageJob.objects.exists()
    assert "Describe what the image shows" in response.text
    response = admin_client.post(
        reverse("studio:images"), {"kind": "hero", "region": "US", "corner": "auto", "description": "Drums"}
    )
    assert "A blog hero needs a headline" in response.text
    response = admin_client.post(
        reverse("studio:images"),
        {
            "kind": "lead",
            "region": "US",
            "corner": "auto",
            "description": "Drums",
            "width": "50",
            "height": "50",
        },
    )
    assert "between 200 and 4000" in response.text


def test_the_pages_render_and_a_failure_is_explained(admin_user, admin_client, fakes, monkeypatch):
    def broken(*args, **kwargs):
        from apps.ai.types import ProviderError

        raise ProviderError("not_free", "402 payment required", 402)

    monkeypatch.setattr(imagegen, "generate_image", broken)
    job = _job(admin_user, description="Drums")
    assert job.status == ImageJob.Status.FAILED and job.error
    page = admin_client.get(reverse("studio:images") + "?tab=single")
    assert page.status_code == 200 and "Image generator" in page.text and "SDS Retention" in page.text
    detail = admin_client.get(reverse("studio:image_job", args=[job.pk]))
    assert "It didn't work." in detail.text
    status = admin_client.get(reverse("studio:image_job_status", args=[job.pk])).json()
    assert status == {"status": "failed", "active": False}
    assert admin_client.get(reverse("studio:image_job_download", args=[job.pk, "png"])).status_code == 404


def test_viewers_without_writing_rights_cannot_make_images(client, django_user_model):
    from django.contrib.auth.models import Permission

    user = django_user_model.objects.create_user("viewer", password="x")
    user.user_permissions.add(
        Permission.objects.get(codename="access_admin"), Permission.objects.get(codename="access_studio")
    )
    client.force_login(user)
    assert client.get(reverse("studio:images")).status_code == 200
    response = client.post(reverse("studio:images"), {"kind": "lead", "description": "Drums"})
    # Wagtail answers a denied admin request by redirecting to the dashboard with a message.
    assert response.status_code in (302, 403) and response.get("Location", "/admin/") == "/admin/"
    assert not ImageJob.objects.exists()


# ---- Images tailored to an existing article ----

ARTICLE = """# SDS Retention: How Long to Keep Them

OSHA treats safety data sheets as exposure records, so you keep them for 30 years.

## What the Rule Says

Keep each SDS while the chemical is on site.

[VISUAL: photo, a worker filing SDS binders in a records room]

## How Long to Keep Old Versions

[VISUAL: flowchart of the retention decision]

Archive superseded sheets with the date they were replaced.

## Frequently Asked Questions

### Can I keep SDSs digitally?

Yes, if every worker can reach them on each shift.
"""

PLAN = {
    "ideas": [
        {
            "kind": "hero",
            "description": "A safety coordinator files SDS binders in a bright records room.",
            "why": "The topic at a glance.",
            "headline": "A made-up headline",
        },
        {
            "kind": "inline",
            "section": "What the Rule Says",
            "description": "A worker files a binder.",
            "why": "Shows the filing step.",
        },
        {"kind": "inline", "section": "A Section That Doesn't Exist", "description": "Invented.", "why": ""},
        {"kind": "hero", "description": "A second hero.", "why": ""},
    ],
    "not_photos": ["How Long to Keep Old Versions: a flowchart, make it in a design tool"],
}


@pytest.fixture
def planner(fakes, monkeypatch):
    original = executors.generate
    seen = []

    def generate(provider, model, messages, options):
        user = messages[-1]["content"]
        if isinstance(user, str) and "Plan the images for this article" in user:
            seen.append(user)
            text = json.dumps(PLAN)
            return GenerationResult(
                provider=provider, model=model, text=text, output_tokens=80, total_time=0.1
            )
        return original(provider, model, messages, options)

    monkeypatch.setattr(executors, "generate", generate)
    return seen


@pytest.fixture
def article_run(admin_user):
    from apps.studio import services
    from apps.studio.models import StepRun

    brief = ContentBrief.objects.create(
        topic="How long to keep SDSs", pkeyword="SDS retention", region="UK", created_by=admin_user
    )
    run = services.create_run(brief, {})
    step = run.steps.get(key="cleanup")
    services.add_version(step, ARTICLE)
    step.status = StepRun.Status.APPROVED
    step.save()
    return run


def test_a_studio_article_gets_a_tailored_plan(admin_client, article_run, planner):
    from apps.studio.models import ImagePlan

    form = admin_client.get(reverse("studio:images"))
    assert f"run:{article_run.pk}" in form.text and "hierarchy of controls (All)" in form.text
    response = admin_client.post(
        reverse("studio:images"), {"action": "plan", "article": f"run:{article_run.pk}"}
    )
    plan = ImagePlan.objects.get()
    assert response["Location"] == reverse("studio:image_plan", args=[plan.pk])
    assert plan.region == "UK" and plan.status == "queued"
    imagegen.execute_plan(plan.pk)
    plan.refresh_from_db()
    assert plan.status == "ready", plan.error
    # The model saw the writer's cues; the hero keeps the article's real H1, not the model's.
    assert "under “What the Rule Says”: photo, a worker filing SDS binders" in planner[0]
    assert [(i["kind"], i["section"]) for i in plan.ideas] == [
        ("hero", "Hero"),
        ("inline", "What the Rule Says"),
    ]
    assert plan.ideas[0]["headline"] == "SDS Retention: How Long to Keep Them"
    assert "flowchart" in plan.notes
    page = admin_client.get(reverse("studio:image_plan", args=[plan.pk]))
    assert "Suggested images" in page.text and "Not photos" in page.text


def test_ticked_ideas_become_images_of_the_article(admin_user, admin_client, article_run, planner, fakes):
    from apps.studio.models import ImagePlan

    plan = ImagePlan.objects.create(run=article_run, region="UK", created_by=admin_user)
    imagegen.execute_plan(plan.pk)
    plan.refresh_from_db()
    response = admin_client.post(
        reverse("studio:image_plan", args=[plan.pk]),
        {
            "action": "make",
            "pick-0": "1",
            "headline-0": "SDS Retention: How Long to Keep Them",
            "description-0": "A coordinator files SDS binders in a bright records room.",
            "description-1": "Not ticked, so not made.",
        },
    )
    assert response.status_code == 302
    job = ImageJob.objects.get()
    assert (job.plan, job.section, job.kind, job.region) == (plan, "Hero", "hero", "UK")
    assert job.description == "A coordinator files SDS binders in a bright records room."
    imagegen.execute(job.pk)
    assert fakes["brand"][-1] == "**SDS Retention:** | How Long to Keep Them"
    status = admin_client.get(reverse("studio:image_plan_status", args=[plan.pk])).json()
    assert status["active"] is False and status["signature"].startswith("ready:")
    page = admin_client.get(reverse("studio:image_plan", args=[plan.pk]))
    assert "Images for this article" in page.text and "Made" in page.text


@respx.mock
def test_a_published_sdsmanager_article_is_read_from_its_page(admin_user, planner):
    from apps.studio.models import ImagePlan

    url = "https://sdsmanager.com/uk/sds-management-articles/safe-system-of-work/"
    body = " ".join(["A safe system of work sets out how a task is done safely."] * 30)
    html = (
        "<html><body><header><nav>Menu</nav></header><main><h1>Safe System of Work: A Guide</h1>"
        f"<p>{body}</p><h2>What the Rule Says</h2><p>{body}</p></main></body></html>"
    )
    respx.get("https://sdsmanager.com/robots.txt").mock(return_value=httpx.Response(200, text=""))
    respx.get(url).mock(return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"}))
    plan = ImagePlan.objects.create(url=url, region="UK", created_by=admin_user)
    imagegen.execute_plan(plan.pk)
    plan.refresh_from_db()
    assert plan.status == "ready", plan.error
    assert plan.title == "Safe System of Work: A Guide"
    assert plan.ideas[0]["headline"] == "Safe System of Work: A Guide"
    assert "- What the Rule Says" in planner[0]


def test_only_sdsmanager_pages_are_fetched(admin_client):
    from apps.studio.models import ImagePlan

    response = admin_client.post(
        reverse("studio:images"), {"action": "plan", "url": "https://example.com/post"}
    )
    assert "Only published sdsmanager.com articles can be read" in response.text
    assert not ImagePlan.objects.exists()
    response = admin_client.post(reverse("studio:images"), {"action": "plan"})
    assert "Choose an article, give its URL, or paste it" in response.text
