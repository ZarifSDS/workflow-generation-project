"""The open hero items from the SOP audit (docs/sop-audit.md, phase 8): a guest post's lead image goes to the
host unbranded at the host's size, and its last step exports instead of publishing; the skill's WebP and
layered SVG are kept; vision findings carry a severity, and text under the veil doesn't hold the hero."""

import io
import json

import pytest
from django.urls import reverse
from PIL import Image

from apps.ai.types import GenerationResult, ImageResult
from apps.content import exports
from apps.content.models import ArticlePage
from apps.quality import hero
from apps.studio import executors, services
from apps.studio.models import ContentBrief, StepRun
from apps.studio.tasks import execute_step

pytestmark = pytest.mark.django_db

VISION = {
    "subject": [0.66, 0.15, 0.9, 1.0],
    "person_at_left_edge": True,
    "facing": "left",
    "readable_text": [],
    "safety_issues": [{"issue": "safety glasses pushed up on the forehead", "severity": "low"}],
    "scene": "chemical store",
    "alt_text": "A worker in nitrile gloves checks a drum label in a chemical store.",
}
ARTICLE = (
    "# SDS Retention: How Long to Keep Them\n\nKeep every SDS.\n\n## What the rule says\n\nThirty years.\n"
)


def _png(width=1440, height=810):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (220, 220, 220)).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def fakes(monkeypatch):
    calls = {"brand": 0, "vision": dict(VISION)}

    def generate(provider, model, messages, options):
        if isinstance(messages[-1]["content"], list):
            text = json.dumps(calls["vision"])
        elif "image prompt" in messages[-1]["content"].lower():
            text = "A chemical store, soft daylight, a worker checking a drum, no text."
        else:
            text = ARTICLE
        return GenerationResult(provider=provider, model=model, text=text, output_tokens=50, total_time=0.1)

    def generate_image(provider, model, prompt, options):
        return ImageResult(provider=provider, model=model, data=_png(), mime_type="image/png")

    def brand(photo, markup, vision):
        calls["brand"] += 1
        return hero.HeroResult(
            png=_png(), webp=b"RIFF-skill-webp", svg=b"<svg id='layered'/>", metrics={"headline": markup}
        )

    monkeypatch.setattr(executors, "generate", generate)
    monkeypatch.setattr(executors, "generate_image", generate_image)
    monkeypatch.setattr(hero, "brand", brand)
    return calls


def _brief(admin_user, **fields):
    values = {
        "topic": "How long to keep SDSs",
        "pkeyword": "SDS retention requirements",
        "region": "US",
        "content_type": "seo_blog",
        "created_by": admin_user,
        **fields,
    }
    return ContentBrief.objects.create(**values)


def _guest(admin_user, **fields):
    return _brief(
        admin_user,
        content_type="outbound",
        site="Example Safety Blog",
        site_domain="https://example-safety.medium.com/",
        anchors=[{"text": "SDS management software", "url": "https://sdsmanager.com/sds-management"}],
        **fields,
    )


def _run_step(run, key, note=""):
    step = run.steps.get(key=key)
    step.status, step.regenerate_note = StepRun.Status.QUEUED, note
    step.save()
    execute_step(step.pk)
    step.refresh_from_db()
    return step


def _approve(run, key, content):
    step = run.steps.get(key=key)
    services.add_version(step, content)
    step.status = StepRun.Status.APPROVED
    step.save()


# ---- Guest posts: the lead image and the export ----


def test_a_guest_post_lead_image_is_unbranded_and_sized_for_the_host(admin_user, fakes):
    run = services.create_run(_guest(admin_user), {})
    step = _run_step(run, "hero_image")
    assert step.status == StepRun.Status.READY, step.error
    version = step.latest_version
    metrics = version.metrics["hero"]
    assert fakes["brand"] == 0  # never branded
    assert metrics["for_host"] is True and metrics["branded"] is False
    assert metrics["host_size"] == [1500, 750]  # Medium's spec
    assert (version.image.width, version.image.height) == (1500, 750)
    assert version.image.file.name.split("/")[-1].startswith("sds-retention-requirements")
    assert version.image.description == VISION["alt_text"]
    assert "Safety (minor, not held): safety glasses pushed up" in version.note
    assert "Lead image for the host site: 1500x750, unbranded" in version.note
    # A low-severity detail doesn't hold the image; it is finished, so nothing else does either.
    assert not executors.hero_needs_a_look(metrics["flags"], True)


def test_a_size_note_recrops_the_same_photo(admin_user, fakes):
    run = services.create_run(_guest(admin_user), {})
    step = _run_step(run, "hero_image")
    photo_id = step.latest_version.metrics["hero"]["photo_image_id"]
    step = _run_step(run, "hero_image", note="Size: 1600x900")
    metrics = step.latest_version.metrics["hero"]
    assert metrics["host_size"] == [1600, 900] and metrics["photo_image_id"] == photo_id


def test_the_guest_post_prompts_ask_for_an_unbranded_editorial_photo(admin_user, fakes, monkeypatch):
    seen = []
    original = executors.generate

    def spy(provider, model, messages, options):
        seen.append(messages)
        return original(provider, model, messages, options)

    monkeypatch.setattr(executors, "generate", spy)
    _run_step(services.create_run(_guest(admin_user), {}), "hero_image")
    prompt = seen[0][0]["content"] + seen[0][1]["content"]
    assert "no veil, logo or headline is added" in prompt and "right third" not in prompt
    vision_prompt = seen[1][-1]["content"][0]["text"]
    assert "white veil" not in vision_prompt and '"severity"' in vision_prompt


def test_a_guest_post_exports_instead_of_publishing(admin_user, fakes):
    run = services.create_run(_guest(admin_user), {})
    _approve(run, "cleanup", ARTICLE)  # the brief's anchor is missing from this text
    hero_step = _run_step(run, "hero_image")
    hero_step.status = StepRun.Status.APPROVED
    hero_step.save()
    step = _run_step(run, "publish")
    assert step.status == StepRun.Status.READY, step.error
    assert step.label == "Export"
    assert not ArticlePage.objects.filter(run=run).exists()
    version = step.latest_version
    assert "Nothing was published on sdsmanager.com" in version.content
    assert "Lead image alt text: A worker in nitrile gloves" in version.content
    assert "isn't in the article" in version.note
    webp = Image.open(io.BytesIO(exports.hero_webp(run)))
    assert webp.format == "WEBP" and webp.size == (1500, 750)
    html = exports.html_export(run)
    assert 'alt="A worker in nitrile gloves' in html and 'width="1500" height="750"' in html
    assert "hero_alt: A worker in nitrile gloves" in exports.markdown_export(run)


# ---- Blog heroes: the skill's own WebP and layered SVG ----


def test_the_skill_webp_and_layered_svg_are_kept_and_exported(admin_user, fakes, admin_client):
    run = services.create_run(_brief(admin_user), {})
    _approve(run, "cleanup", ARTICLE)
    step = _run_step(run, "hero_image")
    files = step.latest_version.metrics["hero"]["files"]
    assert files["webp"].endswith(".webp") and files["svg"].endswith(".svg")
    step.status = StepRun.Status.APPROVED
    step.save()
    assert exports.hero_webp(run) == b"RIFF-skill-webp"
    assert exports.hero_svg(run) == b"<svg id='layered'/>"
    response = admin_client.get(reverse("studio:run_export", args=[run.pk, "svg"]))
    assert response.status_code == 200 and response["Content-Type"] == "image/svg+xml"
    assert step.label == "Hero image"
    assert run.steps.get(key="publish").label == "Publish"


def test_a_hero_without_stored_files_still_exports_a_webp(admin_user, fakes):
    run = services.create_run(_brief(admin_user), {})
    _approve(run, "cleanup", ARTICLE)
    step = _run_step(run, "hero_image")
    version = step.latest_version
    version.metrics["hero"]["files"] = {}  # a hero made before the files were kept
    version.save()
    step.status = StepRun.Status.APPROVED
    step.save()
    assert Image.open(io.BytesIO(exports.hero_webp(run))).size == (720, 405)
    with pytest.raises(exports.ArticleError, match="no layered SVG"):
        exports.hero_svg(run)


# ---- Vision findings: severity and the veil ----


def test_vision_items_carry_a_box_and_a_severity():
    vision = executors._parse_vision(
        json.dumps(
            {
                "subject": [0.6, 0.1, 0.9, 1.0],
                "readable_text": [{"text": "poster", "box": [0.02, 0.1, 0.2, 0.3]}, "label, right edge"],
                "safety_issues": [
                    {"issue": "no gloves while decanting", "severity": "high"},
                    {"issue": "a mop in the background", "severity": "low"},
                    "hand in a cut path",
                    {"issue": "None", "severity": "low"},
                ],
                "alt_text": "  A worker   decants solvent. ",
            }
        )
    )
    assert vision["readable_text"] == [
        {"text": "poster", "box": [0.02, 0.1, 0.2, 0.3]},
        {"text": "label, right edge", "box": None},
    ]
    assert [item["severity"] for item in vision["safety_issues"]] == ["high", "low", "high"]
    assert vision["alt_text"] == "A worker decants solvent."


def test_text_under_the_veil_is_reported_without_holding():
    vision = executors._parse_vision(
        json.dumps(
            {
                "subject": [0.66, 0.15, 0.9, 1.0],
                "readable_text": [
                    {"text": "poster on the far left", "box": [0.02, 0.1, 0.25, 0.3]},
                    {"text": "sign beside the worker", "box": [0.4, 0.1, 0.5, 0.3]},
                ],
                "safety_issues": [],
            }
        )
    )
    reframed = {"reframe": {"subject_left": 0.62, "subject_right": 0.86, "flipped": False}}
    result = hero.HeroResult(png=b"x", metrics=reframed)
    flags = executors._vision_flags(vision, "", result)
    assert "Text under the veil (covered by the branding, not held): poster on the far left" in flags
    assert "Readable text or logo in the photo: sign beside the worker" in flags
    assert executors.hero_needs_a_look(flags, True)  # the sign still holds
    # Unbranded (e.g. a guest post), the same poster is visible and holds.
    assert "Readable text or logo in the photo: poster on the far left" in executors._vision_flags(
        vision, "", hero.HeroResult(png=b"x", metrics=reframed, for_host=True)
    )


def test_the_veil_map_follows_the_reframe():
    vision = {"subject": [0.66, 0.15, 0.9, 1.0]}
    moved = {"reframe": {"subject_left": 0.62, "subject_right": 0.86, "flipped": False}}
    assert hero.final_x(0.66, vision, moved) == pytest.approx(0.62)
    assert hero.covered_by_veil([0.02, 0.1, 0.25, 0.3], vision, moved)
    assert not hero.covered_by_veil([0.4, 0.1, 0.5, 0.3], vision, moved)
    # Flipped: text on the far right of the source ends up on the far left.
    flipped = {"reframe": {"subject_left": 0.62, "subject_right": 0.86, "flipped": True}}
    assert hero.covered_by_veil([0.8, 0.1, 0.95, 0.3], {"subject": [0.1, 0.15, 0.34, 1.0]}, flipped)
    # Branded as it was (generative fill skipped): positions don't move.
    kept = {"reframe": {"subject_left": 0.62, "subject_right": 0.86, "skipped": "generative fill needed"}}
    assert hero.final_x(0.25, vision, kept) == 0.25
    assert not hero.covered_by_veil(None, vision, moved)


# ---- Host sizes and the crop ----


def test_host_sizes_follow_the_platform_then_the_default():
    assert hero.host_size("https://medium.com/@someone") == (1500, 750)
    assert hero.host_size("https://safety.substack.com/") == (1200, 630)
    assert hero.host_size("https://www.linkedin.com/pulse/x") == (1280, 720)
    assert hero.host_size("https://blog.example.com/") == hero.DEFAULT_HOST_SIZE
    assert hero.host_size("https://blog.example.com/", "Size: 1600 x 900") == (1600, 900)


def test_the_host_crop_keeps_the_subject():
    source = Image.new("RGB", (1440, 810), (230, 230, 230))
    source.paste((20, 20, 20), (1100, 100, 1300, 810))  # a dark subject on the right
    buffer = io.BytesIO()
    source.save(buffer, "PNG")
    result = hero.for_host(buffer.getvalue(), (1200, 630), {"subject": [1100 / 1440, 0.12, 1300 / 1440, 1.0]})
    image = Image.open(io.BytesIO(result.png))
    assert image.size == (1200, 630) and result.ready and not result.branded
    assert not result.flags
    dark = [x for x in range(0, 1200, 10) if image.getpixel((x, 400))[0] < 60]
    assert dark and 0 < min(dark) and max(dark) < 1199  # the subject is inside the frame
    small = hero.for_host(_png(640, 360), (1200, 630))
    assert any("upscaled" in flag for flag in small.flags)
