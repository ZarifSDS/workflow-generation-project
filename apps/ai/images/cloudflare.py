"""Cloudflare Workers AI image generation.

FLUX.1 schnell takes a JSON body; FLUX.2 models take multipart/form-data. Both return
{"result": {"image": "<base64>"}}.
"""

import base64
import time

import httpx

from ..types import ImageResult, ProviderError

MULTIPART_MODELS = ("flux-2-",)
# Fields each model accepts; Cloudflare rejects unknown fields with HTTP 400.
JSON_MODEL_FIELDS = {"flux-1-schnell": ("steps", "seed")}
DEFAULT_FIELDS = ("width", "height", "steps", "seed")


def _uses_multipart(model):
    return any(marker in model for marker in MULTIPART_MODELS)


def _allowed_fields(model):
    for name, fields in JSON_MODEL_FIELDS.items():
        if model.endswith(name):
            return fields
    return DEFAULT_FIELDS


def _mime_type(data):
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def generate(spec, model, prompt, options):
    url = f"/accounts/{spec.account_id}/ai/run/{model}"
    fields = {"prompt": prompt}
    for key in _allowed_fields(model):
        if key in options:
            fields[key] = options[key]
    headers = {**spec.headers, "Authorization": f"Bearer {spec.api_key}"}

    started = time.monotonic()
    try:
        with httpx.Client(
            base_url=spec.base_url, headers=headers, timeout=options.get("timeout", 180)
        ) as client:
            if _uses_multipart(model):
                form = {key: (None, str(value)) for key, value in fields.items()}
                response = client.post(url, files=form)
            else:
                response = client.post(url, json=fields)
    except httpx.TimeoutException as error:
        raise ProviderError("network", f"Cloudflare timed out: {error}") from error
    except httpx.TransportError as error:
        raise ProviderError("network", f"Cannot reach Cloudflare: {error}") from error

    if response.status_code == 429:
        raise ProviderError("rate_limited", "Cloudflare daily neuron allowance or rate limit hit", 429)
    if response.status_code >= 500:
        raise ProviderError(
            "server", f"Cloudflare {response.status_code}: {response.text[:300]}", response.status_code
        )
    if response.status_code >= 400:
        kind = "auth" if response.status_code in (401, 403) else "bad_request"
        raise ProviderError(
            kind, f"Cloudflare {response.status_code}: {response.text[:300]}", response.status_code
        )

    try:
        image_b64 = response.json()["result"]["image"]
        data = base64.b64decode(image_b64)
    except (ValueError, KeyError, TypeError) as error:
        raise ProviderError("unknown", f"Unexpected Cloudflare response: {response.text[:300]}") from error

    return ImageResult(
        provider=spec.name,
        model=model,
        data=data,
        mime_type=_mime_type(data),
        total_time=time.monotonic() - started,
    )
