"""M6: ComfyUI provider, vision messages for Ollama, and hero branding with the vendored scripts."""

import io
import json
import shutil

import httpx
import numpy as np
import pytest
import respx
from PIL import Image

from apps.ai.adapters import ollama_native
from apps.ai.images import comfyui
from apps.ai.providers import ProviderSpec
from apps.ai.types import ProviderError
from apps.quality import hero

COMFY = "http://comfy.test:8188"
OLLAMA = "http://ollama.test:11434"

# A FLUX-style API export: BasicGuider -> FluxGuidance -> CLIPTextEncode.
FLUX_WORKFLOW = {
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old prompt", "clip": ["11", 0]}},
    "26": {"class_type": "FluxGuidance", "inputs": {"guidance": 3.5, "conditioning": ["6", 0]}},
    "22": {"class_type": "BasicGuider", "inputs": {"model": ["12", 0], "conditioning": ["26", 0]}},
    "25": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
    "27": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "hero"}},
}
# An SD-style export with a negative prompt: KSampler positive/negative.
SD_WORKFLOW = {
    "3": {
        "class_type": "KSampler",
        "inputs": {"seed": 5, "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]},
    },
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, text"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a photo"}},
}


def test_patch_flux_workflow_follows_guidance_to_the_prompt():
    patched, seed = comfyui.patch_workflow(
        FLUX_WORKFLOW, "warehouse", {"width": 1440, "height": 816, "seed": 9}
    )
    assert patched["6"]["inputs"]["text"] == "warehouse"
    assert patched["27"]["inputs"] | {"batch_size": 1} == {"width": 1440, "height": 816, "batch_size": 1}
    assert patched["25"]["inputs"]["noise_seed"] == seed == 9
    assert FLUX_WORKFLOW["6"]["inputs"]["text"] == "old prompt"  # the stored workflow isn't changed


def test_patch_sd_workflow_uses_the_positive_prompt_not_the_negative():
    patched, seed = comfyui.patch_workflow(SD_WORKFLOW, "lab", {})
    assert patched["6"]["inputs"]["text"] == "lab"
    assert patched["7"]["inputs"]["text"] == "blurry, text"
    assert patched["3"]["inputs"]["seed"] == seed
    assert patched["5"]["inputs"]["width"] == 512  # no size option: the workflow's own size stays


def test_titled_positive_prompt_wins_and_ambiguous_workflows_fail():
    titled = json.loads(json.dumps(SD_WORKFLOW))
    titled["7"]["_meta"] = {"title": "Positive prompt"}
    assert comfyui.find_prompt_node(titled) == "7"
    ambiguous = {key: node for key, node in SD_WORKFLOW.items() if key != "3"}
    with pytest.raises(ProviderError, match="Positive prompt"):
        comfyui.find_prompt_node(ambiguous)


@pytest.fixture
def workflows(settings, tmp_path):
    settings.COMFYUI_WORKFLOWS_DIR = tmp_path
    settings.OLLAMA_BASE_URL = OLLAMA
    (tmp_path / "flux.json").write_text(json.dumps(FLUX_WORKFLOW))
    return tmp_path


SPEC = ProviderSpec(name="comfyui", adapter="comfyui", base_url=COMFY)


@respx.mock
def test_comfyui_queues_polls_downloads_and_frees_the_gpu(workflows):
    respx.get(f"{OLLAMA}/api/ps").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "qwen3.8"}]})
    )
    unload = respx.post(f"{OLLAMA}/api/generate").mock(return_value=httpx.Response(200, json={}))
    queued = respx.post(f"{COMFY}/prompt").mock(return_value=httpx.Response(200, json={"prompt_id": "p1"}))
    respx.get(f"{COMFY}/history/p1").mock(
        side_effect=[
            httpx.Response(200, json={}),
            httpx.Response(
                200,
                json={
                    "p1": {
                        "status": {"status_str": "success", "completed": True},
                        "outputs": {
                            "9": {
                                "images": [{"filename": "hero_0001.png", "subfolder": "", "type": "output"}]
                            }
                        },
                    }
                },
            ),
        ]
    )
    view = respx.get(f"{COMFY}/view").mock(return_value=httpx.Response(200, content=_png(16, 9)))
    free = respx.post(f"{COMFY}/free").mock(return_value=httpx.Response(200))

    result = comfyui.generate(SPEC, "flux.json", "a lab", {"width": 1440, "height": 816, "poll_seconds": 0})

    assert result.mime_type == "image/png"
    assert result.stats["unloaded_ollama_models"] == ["qwen3.8"]
    assert json.loads(unload.calls.last.request.content) == {"model": "qwen3.8", "keep_alive": 0}
    sent = json.loads(queued.calls.last.request.content)["prompt"]
    assert sent["6"]["inputs"]["text"] == "a lab"
    assert view.calls.last.request.url.params["filename"] == "hero_0001.png"
    assert free.called


@respx.mock
def test_comfyui_execution_error_is_a_server_error_and_still_frees(workflows):
    respx.post(f"{COMFY}/prompt").mock(return_value=httpx.Response(200, json={"prompt_id": "p2"}))
    respx.get(f"{COMFY}/history/p2").mock(
        return_value=httpx.Response(
            200,
            json={
                "p2": {
                    "status": {
                        "status_str": "error",
                        "messages": [["execution_error", {"exception_message": "CUDA out of memory"}]],
                    },
                    "outputs": {},
                }
            },
        )
    )
    free = respx.post(f"{COMFY}/free").mock(return_value=httpx.Response(200))
    with pytest.raises(ProviderError, match="CUDA out of memory") as error:
        comfyui.generate(SPEC, "flux.json", "x", {"unload_ollama": False, "poll_seconds": 0})
    assert error.value.kind == "server"
    assert free.called


@respx.mock
def test_comfyui_not_running_is_a_network_error(workflows):
    respx.post(f"{COMFY}/prompt").mock(side_effect=httpx.ConnectError("refused"))
    respx.post(f"{COMFY}/free").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ProviderError, match="Is it running") as error:
        comfyui.generate(SPEC, "flux.json", "x", {"unload_ollama": False})
    assert error.value.kind == "network"


def test_missing_or_ui_format_workflow_is_explained(workflows):
    with pytest.raises(ProviderError, match="not found") as error:
        comfyui.load_workflow("nope.json")
    assert error.value.kind == "not_configured"
    with pytest.raises(ProviderError, match="not found"):
        comfyui.load_workflow("../flux.json")
    (workflows / "ui.json").write_text(json.dumps({"nodes": [], "links": []}))
    with pytest.raises(ProviderError, match="API format"):
        comfyui.load_workflow("ui.json")


def test_ollama_gets_images_as_base64_list():
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}},
        ],
    }
    assert ollama_native._native_message(message) == {
        "role": "user",
        "content": "Describe",
        "images": ["QUJD"],
    }
    assert ollama_native._native_message({"role": "user", "content": "hi"}) == {
        "role": "user",
        "content": "hi",
    }


@pytest.mark.parametrize(
    ("title", "region", "expected"),
    [
        ("SDS Retention: How Long to Keep Them", "US", "**SDS Retention:** | How Long to Keep Them"),
        ("SDS Retention: How Long to Keep Them", "EU", "SDS Retention: | **How Long to Keep Them**"),
        ("How long to keep SDS records", "UK", "How long to keep **SDS records**"),
        ("**Own:** | markup", "US", "**Own:** | markup"),
        ("No keyword here", "US", "No keyword here"),
    ],
)
def test_headline_markup(title, region, expected):
    assert hero.headline_markup(title, region, "SDS records") == expected


# ---- Branding with the real vendored scripts (placeholder brand assets) ----


@pytest.fixture
def vendor(tmp_path, monkeypatch):
    """A copy of the vendored scripts with placeholder assets, so tests never need the real logo."""
    folder = tmp_path / "sds_hero_stock"
    shutil.copytree(
        hero.VENDOR_DIR, folder, ignore=shutil.ignore_patterns("*.png", "*.svg", "__pycache__", "*.pyc")
    )
    assets = folder / "assets"
    Image.new("RGBA", (216, 72), (98, 109, 249, 255)).save(assets / "sds-manager-logo.png")
    Image.new("RGBA", (720, 405), (252, 252, 252, 200)).save(assets / "overlay_A.png")
    ys = np.linspace(255, 167, 405)[:, None, None]
    Image.fromarray(np.broadcast_to(ys, (405, 720, 3)).astype(np.uint8)).save(assets / "veil_color.png")
    monkeypatch.setattr(hero, "VENDOR_DIR", folder)
    hero._compose_module.cache_clear()
    yield folder
    hero._compose_module.cache_clear()


def _png(width, height, subject=None):
    """A calm, bright synthetic photo; `subject` (left, right fractions) adds a textured dark figure."""
    rng = np.random.default_rng(1)
    pixels = np.full((height, width, 3), 228.0) + rng.normal(0, 1.5, (height, width, 3))
    if subject:
        x0, x1 = int(subject[0] * width), int(subject[1] * width)
        y0 = int(0.15 * height)
        pixels[y0:, x0:x1] = 90 + rng.normal(0, 25, (height - y0, x1 - x0, 3))
    buffer = io.BytesIO()
    Image.fromarray(pixels.clip(0, 255).astype(np.uint8)).save(buffer, "PNG")
    return buffer.getvalue()


VISION = {
    "subject": [0.66, 0.15, 0.9, 1.0],
    "person_at_left_edge": True,
    "facing": "left",
    "readable_text": [],
    "safety_issues": [],
    "scene": "warehouse aisle",
}


def test_brand_produces_master_and_webp(vendor):
    result = hero.brand(_png(1440, 810, (0.66, 0.9)), "**SDS Retention:** | How Long to Keep Them", VISION)
    assert result.branded, result.flags
    assert Image.open(io.BytesIO(result.png)).size == (1440, 810)
    assert Image.open(io.BytesIO(result.webp)).size == (720, 405)
    assert result.metrics["headline_fit"]["lines"] <= 4
    assert set(result.metrics["contrast"]) == {"grey", "periwinkle"}
    assert 0.6 < result.metrics["subject_left"] < 0.66  # 62%, or a little right where the crop meets the edge
    assert result.metrics["check"]["ok"] is True
    assert result.metrics["reframe"]["flipped"] is False


def test_brand_flags_a_headline_that_is_too_long(vendor):
    long_headline = "**Safety Data Sheet Retention Requirements:** | " + "every single rule explained " * 6
    result = hero.brand(_png(1440, 810, (0.66, 0.9)), long_headline, VISION)
    assert not result.branded
    assert "Shorten it to about" in result.headline_problem


def test_brand_without_vision_assumes_the_prompted_layout(vendor):
    result = hero.brand(_png(1440, 810, (0.62, 0.9)), "**SDS:** | Basics", None)
    assert result.branded
    assert result.metrics["subject_left"] == hero.TARGET_SUBJECT_LEFT
    assert any("didn't return a subject box" in flag for flag in result.flags)


def test_subject_too_far_left_needs_regeneration(vendor):
    vision = {**VISION, "subject": [0.2, 0.15, 0.45, 1.0]}
    result = hero.brand(_png(1440, 810, (0.2, 0.45)), "**SDS:** | Basics", vision)
    assert not result.branded
    assert result.subject_too_far_left
    assert any("Regenerate with the subject further right" in flag for flag in result.flags)


def test_missing_assets_skip_branding(tmp_path, monkeypatch):
    monkeypatch.setattr(hero, "VENDOR_DIR", tmp_path)
    result = hero.brand(b"", "**SDS:** | Basics", VISION)
    assert not result.branded
    assert "brand assets aren't installed" in result.flags[0]


def test_file_stem_matches_the_skill(vendor):
    assert hero.file_stem("**What Is JSA (Job Safety):** | A Guide") == "What-Is-JSA-Job-Safety-A-Guide"


def test_right_facing_subject_on_the_right_is_not_flipped(vendor):
    vision = {**VISION, "facing": "right"}
    result = hero.brand(_png(1440, 810, (0.66, 0.9)), "**SDS:** | Basics", vision)
    assert result.branded
    assert result.metrics["reframe"]["flipped"] is False
    assert any("faces right" in flag for flag in result.flags)


def test_narrow_fill_strip_is_mirrored_under_the_opaque_veil(vendor):
    vision = {**VISION, "subject": [0.55, 0.15, 0.8, 1.0]}
    result = hero.brand(_png(1440, 810, (0.55, 0.8)), "**SDS:** | Basics", vision)
    assert result.branded, result.flags
    assert result.metrics["reframe"]["fill"] == "mirror"
    assert result.metrics["reframe"]["fill_share"] <= hero.MIRROR_MAX_FILL
    assert 0.6 < result.metrics["subject_left"] < 0.64
    assert any("mirrored fill" in flag for flag in result.flags)
    assert not any("branded as it is" in flag for flag in result.flags)


# ---- Phase 8 (docs/sop-audit.md): the hero step ----


def _blank_png(width, height):
    import io as _io

    from PIL import Image as _Image

    out = _io.BytesIO()
    _Image.new("RGB", (width, height), (200, 200, 200)).save(out, format="PNG")
    return out.getvalue()


def _size(data):
    import io as _io

    from PIL import Image as _Image

    with _Image.open(_io.BytesIO(data)) as image:
        return image.size


def test_photos_are_cropped_to_exactly_16_9_before_the_vision_check():
    from apps.quality import hero

    assert _size(hero.to_16_9(_blank_png(1440, 816))) == (1440, 810)  # what the image model returns
    assert _size(hero.to_16_9(_blank_png(1024, 1024))) == (1024, 576)  # the square fallback model
    exact = _blank_png(1440, 810)
    assert hero.to_16_9(exact) is exact


def test_the_vision_check_ignores_placeholders_and_flags_what_it_left_out():
    from apps.studio import executors

    vision = executors._parse_vision(
        '{"subject": [0.6, 0.1, 0.9, 1.0], "readable_text": ["None", "no readable text"], '
        '"safety_issues": ["no gloves while handling drums", "No issues found"]}'
    )
    assert vision["readable_text"] == [] and vision["safety_issues"] == ["no gloves while handling drums"]
    assert vision["unchecked"] == []
    partial = executors._parse_vision('{"subject": [0.6, 0.1, 0.9, 1.0], "text": []}')
    assert set(partial["unchecked"]) == {"readable_text", "safety_issues"}
    assert executors.hero_needs_a_look(["Unchecked: the vision check didn't report on readable text"], True)


def test_the_headline_splits_only_at_a_colon_followed_by_a_space():
    from apps.quality import hero

    assert hero.headline_markup("ISO 45001:2018 Explained", "US", "") == "ISO 45001:2018 Explained"
    assert hero.headline_markup("SDS Retention: How Long to Keep Them", "US", "") == (
        "**SDS Retention:** | How Long to Keep Them"
    )
