"""Gemini image models (Nano Banana) called with the Gemini key: `POST /v1beta/models/{model}:generateContent`
with `generationConfig.responseModalities: ["IMAGE"]` and `imageConfig` (aspectRatio, imageSize); reference
images go in as `inline_data` parts beside the prompt (up to 14). The image comes back as a part's
`inlineData` (mimeType, base64 data).

Checked live on 2026-10-15 up to the quota: a free-tier key has no image quota at all (HTTP 429, "limit:
0"), which is reported as not_free so nobody waits on retries; the answer's shape is the one Google
documents for generateContent. The same models are served through OpenRouter (apps.ai.images.openrouter).
"""

import base64
import time

import httpx

from ..types import ImageResult, ProviderError
from .shape import DEFAULT_SIZE, mime_type, nearest_ratio, resolution_for

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
SIZES = ["1K", "2K", "4K"]
MOST_REFERENCES = 14


def body(prompt, options):
    options = {**DEFAULT_SIZE, **options} if not options.get("width") else options
    parts = [{"text": prompt}]
    for data in (options.get("reference_images") or [])[:MOST_REFERENCES]:
        parts.append({"inline_data": {"mime_type": mime_type(data), "data": base64.b64encode(data).decode()}})
    config = {
        "aspectRatio": options.get("aspect_ratio")
        or nearest_ratio(options["width"], options["height"], RATIOS)
    }
    if "lite" not in options.get("_model", ""):  # Flash Lite Image makes 1K only
        config["imageSize"] = resolution_for(max(options["width"], options["height"]), SIZES)
    return {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": config},
    }


def generate(spec, model, prompt, options):
    payload = body(prompt, {**options, "_model": model})
    headers = {**spec.headers, "x-goog-api-key": spec.api_key}
    started = time.monotonic()
    try:
        response = httpx.post(
            f"{BASE_URL}/models/{model}:generateContent",
            json=payload,
            headers=headers,
            timeout=options.get("timeout", 240),
        )
    except httpx.TimeoutException as error:
        raise ProviderError("network", f"Gemini timed out: {error}") from error
    except httpx.TransportError as error:
        raise ProviderError("network", f"Cannot reach Gemini: {error}") from error

    status = response.status_code
    if status == 429:
        if "limit: 0" in response.text:
            raise ProviderError(
                "not_free",
                "This Gemini key has no image quota (free tier). Use the OpenRouter entry for this model, "
                "or set the Gemini key to Pay per token under AI providers.",
                429,
            )
        raise ProviderError("rate_limited", "Gemini rate limit hit", 429)
    if status >= 500:
        raise ProviderError("server", f"Gemini {status}: {response.text[:300]}", status)
    if status >= 400:
        kind = "auth" if status in (401, 403) else "bad_request"
        raise ProviderError(kind, f"Gemini {status}: {response.text[:300]}", status)

    try:
        answer = response.json()
        parts = answer["candidates"][0]["content"]["parts"]
        inline = next(
            p.get("inlineData") or p.get("inline_data")
            for p in parts
            if p.get("inlineData") or p.get("inline_data")
        )
        data = base64.b64decode(inline["data"])
    except (ValueError, KeyError, IndexError, TypeError, StopIteration) as error:
        raise ProviderError("unknown", f"Gemini returned no image: {response.text[:300]}") from error
    usage = answer.get("usageMetadata") or {}
    return ImageResult(
        provider=spec.name,
        model=model,
        data=data,
        mime_type=inline.get("mimeType") or inline.get("mime_type") or mime_type(data),
        total_time=time.monotonic() - started,
        stats={
            "request": payload["generationConfig"]["imageConfig"],
            "input_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount"),
        },
    )
