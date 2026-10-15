"""The models a provider offers, read from its own API, for the Add a model form (Settings › AI providers).

- OpenAI-compatible providers (OpenRouter, Groq, Gemini, Ollama Cloud and any added provider):
  `GET {base_url}/models`. OpenRouter adds a name, the context length, per-token prices and the input
  modalities; other providers send at least the id.
- Local Ollama: `GET {base_url}/api/tags` (installed models, all free).

The key goes only to the provider's own address (the one it was entered for). Lists are cached for ten
minutes per provider and address, so the form stays quick while you add several models.
"""

import re
from dataclasses import asdict, dataclass

import httpx
from django.core.cache import cache

from .types import ProviderError

LISTABLE_ADAPTERS = {"openai_compat", "ollama_native"}
CACHE_SECONDS = 600
TIMEOUT = httpx.Timeout(20, connect=10)


class RemoteModelsError(Exception):
    """The list couldn't be read; the message says why, for the form."""


@dataclass(frozen=True)
class RemoteModel:
    id: str
    name: str = ""
    free: bool | None = None  # None: the provider doesn't say
    context: int | None = None
    price: str = ""  # "$0.15 in / $0.60 out per million tokens"
    vision: bool = False
    chat: bool = True  # False: embeddings, speech, image or moderation models (never a step's writer)
    # The same prices as numbers (USD per million tokens) and the output limit, for apps.ai.pricing.
    input_per_m: float | None = None
    output_per_m: float | None = None
    cached_input_per_m: float | None = None
    max_output: int | None = None
    # Image models (list_image_models): reference images taken, and the price per image or per million
    # output-image tokens.
    image: bool = False
    max_references: int = 0
    per_image: float | None = None
    image_out_per_m: float | None = None

    @property
    def status(self):
        """The studio's status for it: free, paid, or "" (unknown)."""
        return "" if self.free is None else ("free" if self.free else "paid")

    @property
    def details(self):
        parts = []
        if self.context:
            parts.append(
                f"{self.context // 1000}k context" if self.context >= 1000 else f"{self.context} context"
            )
        if self.price:
            parts.append(self.price)
        if self.image and self.max_references:
            parts.append(f"takes up to {self.max_references} reference images")
        if self.vision:
            parts.append("vision: reads images")
        return " · ".join(parts)

    @property
    def option_label(self):
        parts = [self.name or self.id]
        if self.name and self.name != self.id:
            parts.append(f"({self.id})")
        return " ".join(parts) + (f" · {self.details}" if self.details else "")


def _per_million(value):
    """A price as USD per million tokens. OpenRouter sends USD per token (strings such as "0.0000001");
    some OpenAI-compatible hosts send per-million numbers. No real price is $1,000 per million or more,
    so a value under 0.001 is per token and anything larger is already per million."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None  # OpenRouter's "-1" means variable pricing (a router model): unknown
    return number * 1_000_000 if number < 0.001 else number


def _prices(item):
    """(input, output, cached input) per million from the shapes OpenAI-compatible lists use:
    OpenRouter's pricing.prompt/completion/input_cache_read, or pricing.input/output."""
    pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
    prompt = _per_million(pricing.get("prompt", pricing.get("input")))
    completion = _per_million(pricing.get("completion", pricing.get("output")))
    cached = _per_million(pricing.get("input_cache_read", pricing.get("cached_input")))
    return prompt, completion, cached


def _money(value):
    return f"${value:.2f}" if value >= 0.01 else f"${value:.4f}".rstrip("0").rstrip(".")


def _openai_entry(item):
    model_id = str(item.get("id") or "").strip()
    if model_id.startswith("models/"):  # Gemini's OpenAI-compatible list
        model_id = model_id.removeprefix("models/")
    prompt, completion, cached = _prices(item)
    free, price = None, ""
    if prompt is not None and completion is not None:
        free = prompt == 0 and completion == 0
        price = "free" if free else f"{_money(prompt)} in / {_money(completion)} out per M tokens"
    elif model_id.endswith(":free"):
        free = True
    architecture = item.get("architecture") or {}
    modalities = architecture.get("input_modalities") or []
    outputs = architecture.get("output_modalities")
    context = item.get("context_length") or item.get("context_window")
    top = item.get("top_provider") if isinstance(item.get("top_provider"), dict) else {}
    max_output = top.get("max_completion_tokens") or item.get("max_completion_tokens")
    name = str(item.get("name") or "").strip()
    return RemoteModel(
        id=model_id,
        name=name,
        free=free,
        context=context if isinstance(context, int) else None,
        price=price,
        vision="image" in modalities,
        # A model that draws images (Nano Banana answers with text too) is an image model, never a writer.
        chat=is_chat(model_id, name) and (not outputs or ("text" in outputs and "image" not in outputs)),
        input_per_m=prompt if completion is not None else None,
        output_per_m=completion if prompt is not None else None,
        cached_input_per_m=cached,
        max_output=max_output if isinstance(max_output, int) else None,
    )


# Ids of models that don't write text: embeddings, speech in or out, image and video makers, moderation.
NOT_CHAT = re.compile(
    r"embed|whisper|tts|transcri|speech|audio|orpheus|playai|imagen|veo|lyria|aqa|"
    r"guard|moderation|image-generation|dall-e|rerank|-image(?:$|[-:])|nano-banana",
    re.IGNORECASE,
)


def is_chat(model_id, name=""):
    return not NOT_CHAT.search(f"{model_id} {name}")


def _fetch(spec):
    headers = dict(spec.headers)
    try:
        key = spec.api_key if spec.adapter == "openai_compat" else ""
    except ProviderError as error:  # the stored key can't be decrypted
        raise RemoteModelsError(str(error)) from error
    if key:
        headers["Authorization"] = f"Bearer {key}"
    path = "/api/tags" if spec.adapter == "ollama_native" else "/models"
    url = spec.base_url.rstrip("/") + path
    try:
        response = httpx.get(url, headers=headers, timeout=TIMEOUT, follow_redirects=False)
    except httpx.HTTPError as error:
        raise RemoteModelsError(f"couldn't reach {spec.base_url} ({error.__class__.__name__})") from error
    if response.status_code in (401, 403):
        raise RemoteModelsError("the provider refused the key (check it under AI providers)")
    if response.status_code != 200:
        raise RemoteModelsError(f"the provider answered HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as error:
        raise RemoteModelsError("the provider's answer wasn't a model list") from error
    if spec.adapter == "ollama_native":
        items = data.get("models") if isinstance(data, dict) else None
        models = []
        for item in items or []:
            if isinstance(item, dict):
                model_id = str(item.get("name") or item.get("model") or "")
                models.append(RemoteModel(id=model_id, free=True, chat=is_chat(model_id)))
    else:
        items = data.get("data") if isinstance(data, dict) else data
        models = [_openai_entry(item) for item in items or [] if isinstance(item, dict)]
    models = [model for model in models if model.id and not any(c.isspace() for c in model.id)]
    if not models:
        raise RemoteModelsError("the provider listed no models")
    return sorted({model.id: model for model in models}.values(), key=lambda m: (m.name or m.id).lower())


def list_models(spec, refresh=False):
    """[RemoteModel] for a provider spec; raises RemoteModelsError."""
    if spec.adapter not in LISTABLE_ADAPTERS:
        raise RemoteModelsError("this provider doesn't list its models")
    if spec.needs_key and not spec.key_source:
        raise RemoteModelsError("add the provider's key first")
    key = f"ai:remote-models:{spec.name}:{spec.base_url}"
    if not refresh and (cached := cache.get(key)) is not None:
        return [RemoteModel(**item) for item in cached]
    models = _fetch(spec)
    cache.set(key, [asdict(model) for model in models], CACHE_SECONDS)
    return models


# ---- Image models (apps.ai.images): OpenRouter's Image API and Gemini's own list ----

GEMINI_NATIVE = "https://generativelanguage.googleapis.com/v1beta"
CAPABILITIES_SECONDS = 24 * 3600
HERO_MEGAPIXELS = 1440 * 816 / 1_000_000  # apps.ai.images.shape.DEFAULT_SIZE; lead images are smaller
IMAGE_ID = re.compile(r"-image(?:$|-)|nano-banana")


def image_side(spec):
    """ "openrouter" or "gemini" when the provider's key also makes images through a known API, else ""."""
    from .service import image_adapter

    return {"openrouter_images": "openrouter", "gemini_images": "gemini"}.get(image_adapter(spec), "")


def _get_json(url, headers, params=None):
    try:
        response = httpx.get(url, headers=headers, params=params, timeout=TIMEOUT, follow_redirects=False)
    except httpx.HTTPError as error:
        raise RemoteModelsError(f"couldn't reach {url.split('/')[2]} ({error.__class__.__name__})") from error
    if response.status_code in (401, 403):
        raise RemoteModelsError("the provider refused the key (check it under AI providers)")
    if response.status_code != 200:
        raise RemoteModelsError(f"the provider answered HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as error:
        raise RemoteModelsError("the provider's answer wasn't a model list") from error


def _key(spec):
    try:
        return spec.api_key
    except ProviderError as error:  # the stored key can't be decrypted
        raise RemoteModelsError(str(error)) from error


def _openrouter_images(spec, prices=True, models_wanted=True):
    headers = {**spec.headers, "Authorization": f"Bearer {_key(spec)}"}
    base = spec.base_url.rstrip("/")
    data = _get_json(base + "/images/models", headers)
    items = data.get("data") if isinstance(data, dict) else data
    items = [item for item in items or [] if isinstance(item, dict)]
    capabilities = {str(item.get("id")): item.get("supported_parameters") or {} for item in items}
    cache.set(f"ai:image-capabilities:{spec.name}", capabilities, CAPABILITIES_SECONDS)
    if not prices and not models_wanted:
        return capabilities
    models = []
    for item in items:
        model_id = str(item.get("id") or "").strip()
        if not model_id or model_id.startswith("openrouter/"):  # routers, not models
            continue
        params = item.get("supported_parameters") or {}
        per_image, per_m = _openrouter_image_price(base, model_id, headers) if prices else (None, None)
        price = ""
        if per_image is not None:
            price = f"{_money(per_image)} per image"
        elif per_m is not None:
            price = f"{_money(per_m)} per M image tokens"
        known = [value for value in (per_image, per_m) if value is not None]
        models.append(
            RemoteModel(
                id=model_id,
                name=str(item.get("name") or "").strip(),
                free=(max(known) == 0) if known else None,
                price=price,
                chat=False,
                image=True,
                max_references=int((params.get("input_references") or {}).get("max") or 0),
                per_image=per_image,
                image_out_per_m=per_m,
            )
        )
    return models


def _openrouter_image_price(base, model_id, headers):
    """(USD per image, USD per million output-image tokens) from the model's first endpoint; either may be
    None. Never raises: a price is an extra."""
    try:
        response = httpx.get(f"{base}/images/models/{model_id}/endpoints", headers=headers, timeout=TIMEOUT)
        endpoints = (response.json().get("endpoints") or []) if response.status_code == 200 else []
    except (httpx.HTTPError, ValueError, AttributeError):
        return None, None
    for entry in (endpoints[0].get("pricing") or []) if endpoints else []:
        if entry.get("billable") != "output_image":
            continue
        try:
            amount = float(entry.get("cost_usd"))
        except (TypeError, ValueError):
            continue
        if entry.get("unit") == "image":
            return amount, None
        if entry.get("unit") == "megapixel":  # FLUX.2: the price of a hero-size photo (an upper bound)
            return amount * HERO_MEGAPIXELS, None
        if entry.get("unit") == "token":
            return None, amount * 1_000_000
    return None, None


def _gemini_images(spec):
    headers = {**spec.headers, "x-goog-api-key": _key(spec)}
    data = _get_json(f"{GEMINI_NATIVE}/models", headers, {"pageSize": 1000})
    models = []
    for item in data.get("models") or []:
        model_id = str(item.get("name") or "").removeprefix("models/")
        if "generateContent" not in (item.get("supportedGenerationMethods") or []):
            continue
        if not IMAGE_ID.search(model_id) or "imagen" in model_id:
            continue
        models.append(
            RemoteModel(
                id=model_id,
                name=str(item.get("displayName") or "").strip(),
                chat=False,
                image=True,
                max_references=3 if "2.5" in model_id else 14,
            )
        )
    return models


def list_image_models(spec, refresh=False, prices=True):
    """[RemoteModel] image models the provider's key can use; [] for a provider without an image side."""
    side = image_side(spec)
    if not side:
        return []
    if spec.needs_key and not spec.key_source:
        raise RemoteModelsError("add the provider's key first")
    key = f"ai:remote-image-models:{spec.name}:{spec.base_url}"
    if not refresh and (cached := cache.get(key)) is not None:
        return [RemoteModel(**item) for item in cached]
    models = _openrouter_images(spec, prices) if side == "openrouter" else _gemini_images(spec)
    models = sorted(models, key=lambda m: (m.name or m.id).lower())
    cache.set(key, [asdict(model) for model in models], CACHE_SECONDS)
    return models


def image_capabilities(spec):
    """{model id: supported_parameters} from OpenRouter's Image API, read at most once a day."""
    found = cache.get(f"ai:image-capabilities:{spec.name}")
    if found is None:
        try:
            found = _openrouter_images(spec, prices=False, models_wanted=False)
        except RemoteModelsError:
            return {}
    return found


# ---- Keeping the model lists in step with the providers (AddedModel rows with source "listed") ----

SYNC_EVERY_HOURS = 24


def listable(spec):
    """A provider whose models can be listed now: a text API that lists models, with its key if needed."""
    return spec.adapter in LISTABLE_ADAPTERS and spec.is_configured


def sync(spec):
    """Read the provider's chat models into AddedModel as "listed" rows: new ones are added, gone ones are
    removed, hidden ones stay hidden, and rows added by hand or edited labels and statuses are left alone.
    Models the built-in catalog already offers are skipped (its curated entry wins). Returns the number of
    listed models; records the result in ModelSync; raises RemoteModelsError after recording it."""
    from django.db import transaction
    from django.utils import timezone

    from . import catalog
    from .models import ModelSync

    record, _ = ModelSync.objects.get_or_create(provider=spec.name)
    try:
        models = [model for model in list_models(spec, refresh=True) if model.chat]
    except RemoteModelsError as error:
        record.error, record.synced_at = str(error)[:300], timezone.now()
        record.save()
        raise
    try:
        images = list_image_models(spec, refresh=True)
    except Exception:  # noqa: BLE001 - the image list is an extra: the text list is still synced
        import logging

        logging.getLogger(__name__).warning("Image models of %s couldn't be listed", spec.name, exc_info=True)
        images = None  # the image rows stay as they were
    built_in = {item.model for item in catalog.CATALOG if item.provider == spec.name}
    usual = catalog.usual_status(spec.name)
    now = timezone.now()
    wanted = {model.id: model for model in models if model.id not in built_in}
    with transaction.atomic():
        listed = _apply(spec, "text", wanted, usual, now)
        if images is not None:
            listed += _apply(spec, "image", {m.id: m for m in images if m.id not in built_in}, "paid", now)
        record.synced_at, record.listed, record.error = now, listed, ""
        record.save()
    catalog.clear_cache()
    _update_prices(spec, models)
    if images:
        _update_image_prices(spec, images)
    return listed


def _apply(spec, kind, wanted, usual, now):
    """Bring the provider's listed rows of one kind in line with `wanted`; returns how many it lists. A
    listed row of the other kind for a wanted id (a Nano Banana once listed as a writer) changes kind."""
    from .models import AddedModel

    rows = {row.model: row for row in AddedModel.objects.filter(provider=spec.name)}
    new = [
        AddedModel(
            provider=spec.name,
            model=model.id,
            label=(model.name or model.id)[:80],
            kind=kind,
            max_references=model.max_references,
            status=model.status or usual,
            source=AddedModel.Source.LISTED,
            details=model.details[:200],
            refreshed_at=now,
        )
        for model_id, model in wanted.items()
        if model_id not in rows
    ]
    AddedModel.objects.bulk_create(new)
    for model_id, row in rows.items():
        if row.source != AddedModel.Source.LISTED:
            continue
        if model_id in wanted:
            model = wanted[model_id]
            row.details, row.refreshed_at = model.details[:200], now
            row.kind, row.max_references = kind, model.max_references
            row.save(update_fields=["details", "refreshed_at", "kind", "max_references"])
        elif row.kind == kind:
            row.delete()
    return len(wanted)


def _update_image_prices(spec, images):
    """Per-image (or per image-token) prices from the provider's list into ModelInfo; never raises. A value
    entered by hand is kept."""
    from decimal import Decimal

    from django.utils import timezone

    from . import pricing
    from .models import ModelInfo

    def dec(value):
        return None if value is None else Decimal(str(round(value, 6)))

    try:
        now = timezone.now()
        for model in images:
            if model.per_image is None and model.image_out_per_m is None:
                continue
            row, _ = ModelInfo.objects.get_or_create(provider=spec.name, model=model.id)
            if row.price_source == pricing.MANUAL:
                continue
            row.per_image, row.image_out_per_m = dec(model.per_image), dec(model.image_out_per_m)
            row.price_source, row.checked_at = "provider", now
            row.save()
        pricing.clear_cache()
    except Exception:  # noqa: BLE001 - prices are an extra: the model list itself is already saved
        import logging

        logging.getLogger(__name__).exception("Image prices for %s couldn't be updated", spec.name)


def _update_prices(spec, models):
    """Prices and context windows for every model of the provider (apps.ai.pricing); never raises."""
    from . import catalog, pricing
    from .models import AddedModel

    try:
        pricing.refresh_reference()
        if spec.adapter == "ollama_native":
            models = [_with_ollama_context(spec, model) for model in models]
        others = [m.model for m in catalog.CATALOG if m.provider == spec.name and m.kind == "text"]
        others += list(
            AddedModel.objects.filter(provider=spec.name, source=AddedModel.Source.MANUAL).values_list(
                "model", flat=True
            )
        )
        pricing.update(spec.name, listed=models, model_ids=others)
    except Exception:  # noqa: BLE001 - prices are an extra: the model list itself is already saved
        import logging

        logging.getLogger(__name__).exception("Prices for %s couldn't be updated", spec.name)


def _with_ollama_context(spec, model):
    """Local Ollama reports a model's context length through /api/show (model_info "*.context_length")."""
    from dataclasses import replace

    try:
        response = httpx.post(
            spec.base_url.rstrip("/") + "/api/show",
            json={"model": model.id},
            headers=dict(spec.headers),
            timeout=TIMEOUT,
        )
        info = response.json().get("model_info") or {} if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return model
    lengths = [v for k, v in info.items() if k.endswith(".context_length") and isinstance(v, int)]
    return replace(model, context=lengths[0]) if lengths else model


def stale(names=None):
    """Names of listable providers not synced in the last SYNC_EVERY_HOURS (or never)."""
    from datetime import timedelta

    from django.utils import timezone

    from .models import ModelSync
    from .providers import get_providers

    cutoff = timezone.now() - timedelta(hours=SYNC_EVERY_HOURS)
    synced = {row.provider: row.synced_at for row in ModelSync.objects.all()}
    return [
        name
        for name, spec in get_providers().items()
        if listable(spec)
        and (names is None or name in names)
        and not (synced.get(name) and synced[name] > cutoff)
    ]


def sync_all(names=None):
    """{provider: listed count or error message} for every listable provider (or the named ones)."""
    from .providers import get_providers

    results = {}
    for name, spec in get_providers().items():
        if not listable(spec) or (names is not None and name not in names):
            continue
        try:
            results[name] = sync(spec)
        except RemoteModelsError as error:
            results[name] = str(error)
    if names is None:
        from . import pricing

        pricing.update_all()  # models of providers that list nothing get reference prices too
    return results
