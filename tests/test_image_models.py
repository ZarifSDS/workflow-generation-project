"""More image models (2026-10-15): OpenRouter's Image API and Gemini's image models as adapters, image models
listed from the keys with their reference-image limits and prices, the owner's recommended order at the top
of every image list, separate defaults for lead and in-article images, and a model choice plus brand assets
in the Image generator."""

import base64
import io
import json
from decimal import Decimal

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.ai import catalog, pricing, redact, remote_models, secrets, service
from apps.ai.images import gemini, openrouter, shape
from apps.ai.models import AddedModel, ModelInfo, ProviderConfig, TaskDefault, UsageRecord
from apps.ai.providers import get_provider
from apps.ai.types import GenerationResult, ImageResult, ProviderError
from apps.studio import executors, imagegen
from apps.studio.forms import ImageJobForm
from apps.studio.models import ImageJob
from apps.studio.pipeline import profile_for

pytestmark = pytest.mark.django_db

BASE = "https://openrouter.ai/api/v1"
KEY = "sk-or-v1-FAKEtestonlyKEY0123456789abcdef"
FLARE = "openai/gpt-image-2.5-flare"
BANANA = "google/gemini-nano-banana-2.1"
SEEDREAM = "bytedance-seed/seedream-5-0-flash"
RATIOS = ["1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16", "21:9", "auto"]
IMAGE_MODELS = {
    "data": [
        {
            "id": FLARE,
            "name": "OpenAI: GPT Image 2.5 Flare",
            "supported_parameters": {
                "aspect_ratio": {"type": "enum", "values": RATIOS},
                "quality": {"type": "enum", "values": ["auto", "low", "medium", "high"]},
                "input_references": {"type": "range", "min": 0, "max": 16},
            },
        },
        {
            "id": BANANA,
            "name": "Google: Nano Banana 2.1",
            "supported_parameters": {
                "resolution": {"type": "enum", "values": ["1K", "2K", "4K"]},
                "aspect_ratio": {"type": "enum", "values": ["1:1", "16:9", "4:3"]},
                "input_references": {"type": "range", "min": 0, "max": 14},
            },
        },
        {
            "id": SEEDREAM,
            "name": "ByteDance Seed: Seedream 5.0 Flash",
            "supported_parameters": {"aspect_ratio": {"type": "enum", "values": ["1:1", "16:9"]}},
        },
        {"id": "openrouter/auto", "name": "Auto Router", "supported_parameters": {}},
    ]
}
TEXT_MODELS = {
    "data": [
        {
            "id": "anthropic/claude-sonnet-5.5",
            "name": "Anthropic: Claude Sonnet 5.5",
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        },
        {  # draws images and answers with text too: an image model, never a writer
            "id": "google/gemini-3.1-flash-image",
            "name": "Google: Nano Banana 2",
            "pricing": {"prompt": "0.0000005", "completion": "0.000003"},
            "architecture": {"input_modalities": ["image", "text"], "output_modalities": ["image", "text"]},
        },
    ]
}


def _endpoints(unit, cost):
    return {"endpoints": [{"pricing": [{"billable": "output_image", "unit": unit, "cost_usd": cost}]}]}


def _png(width=64, height=36):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 200, 200)).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def secrets_key(monkeypatch, settings, tmp_path):
    monkeypatch.setenv(secrets.ENV_NAME, Fernet.generate_key().decode())
    settings.MEDIA_ROOT = tmp_path
    redact.clear_stored_cache()
    cache.clear()
    yield
    redact.clear_stored_cache()
    cache.clear()


def _mock_openrouter(mock):
    mock.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=TEXT_MODELS))
    mock.get(f"{BASE}/images/models").mock(return_value=httpx.Response(200, json=IMAGE_MODELS))
    mock.get(f"{BASE}/images/models/{FLARE}/endpoints").mock(
        return_value=httpx.Response(200, json=_endpoints("token", 3e-05))
    )
    mock.get(f"{BASE}/images/models/{SEEDREAM}/endpoints").mock(
        return_value=httpx.Response(200, json=_endpoints("image", 0.018))
    )
    mock.get(f"{BASE}/images/models/{BANANA}/endpoints").mock(
        return_value=httpx.Response(200, json=_endpoints("megapixel", 0.014))
    )


@pytest.fixture
def openrouter_key(admin_client):
    """OpenRouter added with a key (pay per token); adding it lists its text and image models."""
    with respx.mock(assert_all_called=False) as mock:
        _mock_openrouter(mock)
        admin_client.post(
            reverse("studio:provider_add"),
            {"label": "OpenRouter", "name": "openrouter", "base_url": BASE, "api_key": KEY},
        )
    assert ProviderConfig.objects.filter(name="openrouter").exists()
    catalog.clear_cache()
    pricing.clear_cache()


# ---- Shapes ----


def test_sizes_map_to_the_nearest_ratio_and_the_smallest_tier_that_is_big_enough():
    assert shape.nearest_ratio(1440, 816, RATIOS) == "16:9"
    assert shape.nearest_ratio(1200, 630, ["1:1", "16:9", "4:3", "auto"]) == "16:9"
    assert shape.nearest_ratio(1000, 1000, ["auto"]) is None
    assert shape.resolution_for(1440, ["1K", "2K", "4K"]) == "2K"  # a 1K hero would be upscaled
    assert shape.resolution_for(900, ["512", "1K", "2K"]) == "1K"
    assert shape.resolution_for(5000, ["1K", "2K"]) == "2K"
    assert shape.resolution_for(1440, []) is None


def test_the_openrouter_body_keeps_to_what_the_model_takes():
    caps = {item["id"]: item["supported_parameters"] for item in IMAGE_MODELS["data"]}
    body = openrouter.body(BANANA, "A shelf.", {}, caps[BANANA])
    # No size given: the hero's 1440x816 is asked for, as 16:9 at 2K.
    assert body == {"model": BANANA, "prompt": "A shelf.", "aspect_ratio": "16:9", "resolution": "2K"}
    flare = openrouter.body(FLARE, "A shelf.", {"width": 1200, "height": 900, "seed": 3}, caps[FLARE])
    assert flare["aspect_ratio"] == "4:3" and "resolution" not in flare and "seed" not in flare
    refs = openrouter.body(FLARE, "p", {"reference_images": [_png()] * 20}, caps[FLARE])["input_references"]
    assert len(refs) == 16 and refs[0]["image_url"]["url"].startswith("data:image/png;base64,")
    with pytest.raises(ProviderError, match="doesn't take reference images"):
        openrouter.body(SEEDREAM, "p", {"reference_images": [_png()]}, caps[SEEDREAM])


# ---- Adapters ----


def test_an_openrouter_image_is_generated_and_its_billed_cost_recorded(openrouter_key):
    image = _png()
    with respx.mock(assert_all_called=False) as mock:
        _mock_openrouter(mock)
        route = mock.post(f"{BASE}/images").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [{"b64_json": base64.b64encode(image).decode(), "media_type": "image/png"}],
                    "usage": {"cost": 0.04},
                },
            )
        )
        result = service.generate_image("openrouter", FLARE, "A shelf.", {"reference_images": [_png()] * 3})
    sent = json.loads(route.calls.last.request.content)
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {KEY}"
    assert sent["model"] == FLARE and sent["aspect_ratio"] == "16:9" and len(sent["input_references"]) == 3
    assert (result.data, result.mime_type, result.stats["references"]) == (image, "image/png", 3)
    row = UsageRecord.objects.get()
    assert (row.provider, row.model, row.cost, row.cost_kind) == (
        "openrouter",
        FLARE,
        Decimal("0.04"),
        "billed",
    )


def test_a_failed_openrouter_image_is_not_retried_for_a_missing_credit(openrouter_key):
    with respx.mock(assert_all_called=False) as mock:
        _mock_openrouter(mock)
        mock.post(f"{BASE}/images").mock(return_value=httpx.Response(402, json={"error": "credit"}))
        with pytest.raises(ProviderError) as caught:
            service.generate_image("openrouter", SEEDREAM, "A shelf.", retries=2, backoff=0)
    assert caught.value.kind == "not_free" and not caught.value.retryable


def test_gemini_images_use_generate_content_and_a_free_key_fails_at_once(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFAKEtestonly0123456789")
    spec = get_provider("gemini")
    assert service.image_adapter(spec) == "gemini_images"
    url = f"{gemini.BASE_URL}/models/gemini-nano-banana-2.1:generateContent"
    image = _png()
    with respx.mock() as mock:
        route = mock.post(url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "image/png",
                                            "data": base64.b64encode(image).decode(),
                                        }
                                    }
                                ]
                            }
                        }
                    ],
                    "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 1290},
                },
            )
        )
        result = gemini.generate(spec, "gemini-nano-banana-2.1", "A shelf.", {"reference_images": [_png()]})
        sent = json.loads(route.calls.last.request.content)
        assert route.calls.last.request.headers["x-goog-api-key"] == "AIzaFAKEtestonly0123456789"
        assert sent["generationConfig"] == {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": "16:9", "imageSize": "2K"},
        }
        assert sent["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "image/png"
        assert result.data == image and result.stats["output_tokens"] == 1290

        mock.post(url).mock(
            return_value=httpx.Response(
                429, text='{"error": {"message": "Quota exceeded ... limit: 0, model: x"}}'
            )
        )
        with pytest.raises(ProviderError) as caught:
            gemini.generate(spec, "gemini-nano-banana-2.1", "A shelf.", {})
    assert caught.value.kind == "not_free" and "OpenRouter" in str(caught.value)


# ---- Lists, prices and order ----


def test_a_key_lists_its_image_models_with_their_limits_and_prices(openrouter_key):
    rows = {row.model: row for row in AddedModel.objects.filter(provider="openrouter")}
    assert rows["anthropic/claude-sonnet-5.5"].kind == "text"
    assert "google/gemini-3.1-flash-image" not in rows  # not a writer, and not in the Image API list here
    assert {m for m, row in rows.items() if row.kind == "image"} == {FLARE, BANANA, SEEDREAM}  # no router
    assert (rows[FLARE].max_references, rows[SEEDREAM].max_references) == (16, 0)
    assert "takes up to 16 reference images" in rows[FLARE].details
    assert ModelInfo.objects.get(model=SEEDREAM).per_image == Decimal("0.018")
    assert ModelInfo.objects.get(model=FLARE).image_out_per_m == Decimal("30")
    # Priced per megapixel (FLUX.2): the price of a hero-size photo.
    assert ModelInfo.objects.get(model=BANANA).per_image == Decimal("0.016451")
    assert pricing.facts("openrouter", SEEDREAM) == "$0.02 per image"
    assert pricing.facts("openrouter", FLARE) == "$30 per M image tokens"
    # A per-image price is the cost when the provider bills none.
    assert pricing.cost("openrouter", SEEDREAM, None, None, images=1) == (Decimal("0.018000"), "estimated")
    assert all(item.kind == "text" for _, items in catalog.grouped("text") for item in items)


def test_a_model_once_listed_as_a_writer_becomes_an_image_model(openrouter_key):
    AddedModel.objects.filter(provider="openrouter", model=FLARE).update(kind="text", max_references=0)
    with respx.mock(assert_all_called=False) as mock:
        _mock_openrouter(mock)
        remote_models.sync(get_provider("openrouter"))
    row = AddedModel.objects.get(provider="openrouter", model=FLARE)
    assert (row.kind, row.max_references) == ("image", 16)


def test_image_lists_start_with_the_owners_order_and_show_each_model_once(openrouter_key):
    groups = catalog.grouped("image")
    name, top = groups[0]
    assert name == "Recommended"
    keys = [item.key for item in top]
    assert (
        keys.index(f"openrouter::{BANANA}")
        < keys.index(f"openrouter::{SEEDREAM}")
        < keys.index(f"openrouter::{FLARE}")
        < keys.index("cloudflare::@cf/black-forest-labs/flux-2-klein-4b")
    )
    labels = {item.key: item.label for item in top}
    assert labels[f"openrouter::{BANANA}"].endswith("· OpenRouter · best for text in images")
    assert "best for combining 3+ brand assets" in labels[f"openrouter::{FLARE}"]
    # FLUX.2 klein 9B has a non-commercial licence: listed, never offered.
    assert not catalog.find("cloudflare", "@cf/black-forest-labs/flux-2-klein-9b").selectable
    every = [item.key for _, items in groups for item in items]
    assert len(every) == len(set(every))


def test_gemini_image_models_are_listed_but_not_offered_on_a_free_tier_key():
    AddedModel.objects.create(
        provider="gemini",
        model="gemini-nano-banana-2.1",
        label="Nano Banana 2.1",
        kind="image",
        status="paid",
    )
    catalog.clear_cache()
    item = catalog.find("gemini", "gemini-nano-banana-2.1")
    assert not item.selectable and "OpenRouter" in item.reason
    ProviderConfig.objects.create(name="gemini", billing="per_token")
    catalog.clear_cache()
    pricing.clear_cache()
    assert catalog.find("gemini", "gemini-nano-banana-2.1").selectable


# ---- Defaults and the Image generator ----


def test_lead_and_in_article_images_follow_the_hero_until_they_have_their_own(openrouter_key):
    assert profile_for("lead_image")["model"] == profile_for("hero_image")["model"]
    TaskDefault.objects.create(task="hero_image", model_key=f"openrouter::{BANANA}")
    TaskDefault.objects.create(task="inline_image", model_key=f"openrouter::{FLARE}")
    from apps.ai import defaults

    defaults.clear_cache()
    assert profile_for("lead_image")["model"] == BANANA
    assert profile_for("inline_image")["model"] == FLARE


def test_the_default_models_page_offers_the_image_tasks(admin_client, openrouter_key):
    page = admin_client.get(reverse("studio:task_defaults")).content.decode()
    assert "Lead image" in page and "In-article image" in page and "Same as Hero image" in page


def _form(**data):
    values = {"kind": "lead", "region": "US", "corner": "auto", "description": "A worker with a binder"}
    files = {"references_upload": [SimpleUploadedFile(f"a{i}.png", _png(), "image/png") for i in range(3)]}
    return ImageJobForm({**values, **data}, files)


def test_brand_assets_need_a_model_that_takes_them(openrouter_key):
    refused = _form()  # the default (Cloudflare FLUX.2 klein) takes no reference images
    assert not refused.is_valid() and "can't take brand assets" in refused.errors["model_key"][0]
    chosen = _form(model_key=f"openrouter::{FLARE}")
    assert chosen.is_valid(), chosen.errors
    assert len(chosen.cleaned_data["references_upload"]) == 3


@pytest.fixture
def fakes(monkeypatch):
    calls = {}
    vision = {
        "subject": [0.6, 0.1, 0.9, 1.0],
        "readable_text": [],
        "safety_issues": [],
        "alt_text": "A binder.",
    }

    def generate(provider, model, messages, options):
        text = json.dumps(vision) if isinstance(messages[-1]["content"], list) else "A worker with a binder."
        return GenerationResult(provider=provider, model=model, text=text, output_tokens=10, total_time=0.1)

    def generate_image(provider, model, prompt, options):
        calls.setdefault("models", []).append(f"{provider}::{model}")
        calls["options"], calls["prompt"] = options, prompt
        if calls.get("fail_first") and len(calls["models"]) == 1:
            raise ProviderError("server", "down")
        return ImageResult(provider=provider, model=model, data=_png(1440, 816), mime_type="image/png")

    monkeypatch.setattr(executors, "generate", generate)
    monkeypatch.setattr(imagegen, "generate_image", generate_image)
    return calls


def test_a_job_uses_its_chosen_model_with_the_brand_assets(admin_client, openrouter_key, fakes):
    files = [SimpleUploadedFile(f"logo{i}.png", _png(), "image/png") for i in range(3)]
    response = admin_client.post(
        reverse("studio:images"),
        {
            "kind": "lead",
            "region": "US",
            "corner": "auto",
            "description": "A worker with a binder",
            "model_key": f"openrouter::{FLARE}",
            "references_upload": files,
        },
    )
    job = ImageJob.objects.get()
    assert response.status_code == 302 and job.references.count() == 3
    imagegen.execute(job.pk)
    job.refresh_from_db()
    assert job.status == ImageJob.Status.DONE, job.error
    assert fakes["models"] == [f"openrouter::{FLARE}"]
    assert len(fakes["options"]["reference_images"]) == 3
    # The brand assets are kept as they are; the usual no-logos clause would forbid them.
    assert fakes["prompt"].endswith(imagegen.WITH_REFERENCES) and executors.NO_TEXT not in fakes["prompt"]
    again = imagegen.again(job, job.created_by)
    assert again.model_key == job.model_key and again.references.count() == 3


def test_a_fallback_without_reference_images_still_makes_the_photo(admin_user, openrouter_key, fakes):
    fakes["fail_first"] = True
    job = ImageJob.objects.create(
        kind="lead", description="A binder", created_by=admin_user, model_key=f"openrouter::{FLARE}"
    )
    job.references.set([imagegen._save_image("logo", _png(), "logo.png")])
    imagegen.execute(job.pk)
    job.refresh_from_db()
    assert job.status == ImageJob.Status.DONE, job.error
    assert fakes["models"][1] == "cloudflare::@cf/black-forest-labs/flux-2-klein-4b"
    assert "reference_images" not in fakes["options"]
