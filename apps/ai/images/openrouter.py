"""OpenRouter's Image API: `POST {base_url}/images` (https://openrouter.ai/docs/features/multimodal/image-generation).

One shape for every image model OpenRouter serves (Nano Banana, GPT Image, Seedream, FLUX, ...):
{"model", "prompt", "aspect_ratio", "resolution", "input_references": [{"type": "image_url", "image_url":
{"url": <data URL>}}]} answered with {"data": [{"b64_json", "media_type"}], "usage": {"cost", ...}}. Each
model accepts its own subset of aspect ratios, resolutions and reference counts, read from
`GET {base_url}/images/models` (apps.ai.remote_models.image_capabilities); a value a model doesn't take
is left out rather than sent, so the request never fails on it. Checked live on 2026-10-15.
"""

import base64
import time

import httpx

from ..types import ImageResult, ProviderError
from .shape import DEFAULT_SIZE, mime_type, nearest_ratio, resolution_for


def _reference(data):
    url = f"data:{mime_type(data)};base64,{base64.b64encode(data).decode()}"
    return {"type": "image_url", "image_url": {"url": url}}


def body(model, prompt, options, capabilities):
    """The request body for `model`, keeping to what it accepts (`capabilities`: its supported_parameters).
    Without a size the studio's hero size is asked for: every photo it makes is landscape."""
    options = {**DEFAULT_SIZE, **options} if not options.get("width") else options
    payload = {"model": model, "prompt": prompt}
    ratios = (capabilities.get("aspect_ratio") or {}).get("values") or []
    if options.get("aspect_ratio") in ratios:
        payload["aspect_ratio"] = options["aspect_ratio"]
    elif ratios and options.get("width") and options.get("height"):
        payload["aspect_ratio"] = nearest_ratio(options["width"], options["height"], ratios)
    tiers = (capabilities.get("resolution") or {}).get("values") or []
    if tiers and options.get("width"):
        payload["resolution"] = resolution_for(max(options["width"], options.get("height") or 0), tiers)
    if "seed" in options and "seed" in capabilities:
        payload["seed"] = options["seed"]
    if options.get("quality") in ((capabilities.get("quality") or {}).get("values") or []):
        payload["quality"] = options["quality"]
    references = options.get("reference_images") or []
    if references:
        most = (capabilities.get("input_references") or {}).get("max") or 0
        if not most:
            raise ProviderError("bad_request", f"{model} doesn't take reference images")
        payload["input_references"] = [_reference(data) for data in references[:most]]
    return payload


def generate(spec, model, prompt, options):
    from ..remote_models import image_capabilities

    payload = body(model, prompt, options, image_capabilities(spec).get(model, {}))
    headers = {**spec.headers, "Authorization": f"Bearer {spec.api_key}"}
    started = time.monotonic()
    try:
        response = httpx.post(
            spec.base_url.rstrip("/") + "/images",
            json=payload,
            headers=headers,
            timeout=options.get("timeout", 240),
        )
    except httpx.TimeoutException as error:
        raise ProviderError("network", f"OpenRouter timed out: {error}") from error
    except httpx.TransportError as error:
        raise ProviderError("network", f"Cannot reach OpenRouter: {error}") from error

    status = response.status_code
    if status == 429:
        raise ProviderError("rate_limited", "OpenRouter rate limit hit", 429)
    if status == 402:
        raise ProviderError("not_free", "OpenRouter: not enough credit for this image", 402)
    if status >= 500:  # 502: the generation did not complete (not billed)
        raise ProviderError("server", f"OpenRouter {status}: {response.text[:300]}", status)
    if status >= 400:
        kind = "auth" if status in (401, 403) else "bad_request"
        raise ProviderError(kind, f"OpenRouter {status}: {response.text[:300]}", status)

    try:
        answer = response.json()
        item = answer["data"][0]
        data = base64.b64decode(item["b64_json"])
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise ProviderError("unknown", f"Unexpected OpenRouter response: {response.text[:300]}") from error
    usage = answer.get("usage") or {}
    stats = {"request": {k: v for k, v in payload.items() if k not in ("prompt", "input_references")}}
    if usage.get("cost") is not None:
        stats["billed_cost"] = usage["cost"]
    if references := payload.get("input_references"):
        stats["references"] = len(references)
    return ImageResult(
        provider=spec.name,
        model=model,
        data=data,
        mime_type=item.get("media_type") or mime_type(data),
        total_time=time.monotonic() - started,
        stats=stats,
    )
