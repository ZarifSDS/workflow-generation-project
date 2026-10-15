"""Entry points for the rest of the app: generate text or an image with retries."""

import logging
import time

from django.conf import settings

from . import usage
from .adapters import ollama_native, openai_compat
from .images import cloudflare, comfyui, gemini, openrouter
from .providers import get_provider
from .types import ProviderError

logger = logging.getLogger(__name__)

TEXT_ADAPTERS = {"openai_compat": openai_compat.chat, "ollama_native": ollama_native.chat}
IMAGE_ADAPTERS = {
    "cloudflare_images": cloudflare.generate,
    "comfyui": comfyui.generate,
    "gemini_images": gemini.generate,
    "openrouter_images": openrouter.generate,
}


def image_adapter(spec):
    """The image API behind a provider: its own adapter (Cloudflare, ComfyUI), or the image side of a text
    provider (OpenRouter's Image API, Gemini's generateContent); "" when it makes no images."""
    if spec.adapter in IMAGE_ADAPTERS:
        return spec.adapter
    if spec.image_adapter:
        return spec.image_adapter
    if spec.adapter == "openai_compat" and "openrouter.ai" in spec.base_url:
        return "openrouter_images"
    return ""


def _with_retries(call, describe, retries, backoff):
    attempt = 0
    while True:
        attempt += 1
        try:
            result = call()
            result.attempts = attempt
            return result
        except ProviderError as error:
            if not error.retryable or attempt > retries:
                raise
            wait = backoff * (3 ** (attempt - 1))
            logger.warning("%s failed (%s), retry %s/%s in %ss", describe, error.kind, attempt, retries, wait)
            time.sleep(wait)


def generate(provider, model, messages, options=None, retries=None, backoff=None):
    """Chat completion. `messages` is a list of {"role", "content"} dicts."""
    options = options or {}
    spec = get_provider(provider)
    try:
        adapter = TEXT_ADAPTERS[spec.adapter]
    except KeyError:
        raise ProviderError("bad_request", f"Provider '{provider}' does not generate text") from None
    result = _with_retries(
        lambda: adapter(spec, model, messages, options),
        f"{provider}/{model}",
        settings.AI_RETRIES if retries is None else retries,
        settings.AI_RETRY_BACKOFF if backoff is None else backoff,
    )
    usage.record(result)  # tokens and cost in the ledger; never raises
    return result


def generate_image(provider, model, prompt, options=None, retries=None, backoff=None):
    options = options or {}
    spec = get_provider(provider)
    try:
        adapter = IMAGE_ADAPTERS[image_adapter(spec)]
    except KeyError:
        raise ProviderError("bad_request", f"Provider '{provider}' does not generate images") from None
    result = _with_retries(
        lambda: adapter(spec, model, prompt, options),
        f"{provider}/{model}",
        settings.AI_RETRIES if retries is None else retries,
        settings.AI_RETRY_BACKOFF if backoff is None else backoff,
    )
    usage.record(result)  # one image and its cost (OpenRouter bills it exactly) in the ledger
    return result


def generate_for_profile(profile, messages, options=None):
    """Use a configured profile (quality/fast/edit), falling back to its backup provider."""
    config = settings.AI_PROFILES.get(profile)
    if not config:
        raise ProviderError(
            "not_configured", f"Profile '{profile}' is not configured (see docs/model-eval.md)"
        )
    merged = {**config.get("options", {}), **(options or {})}
    try:
        return generate(config["provider"], config["model"], messages, merged)
    except ProviderError as error:
        fallback = config.get("fallback")
        if not fallback:
            raise
        logger.warning("Profile %s: %s failed (%s), using fallback", profile, config["model"], error.kind)
        return generate(
            fallback["provider"],
            fallback["model"],
            messages,
            {**fallback.get("options", {}), **(options or {})},
        )
