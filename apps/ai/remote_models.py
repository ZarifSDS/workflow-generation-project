"""The models a provider offers, read from its own API, for the Add a model form (Settings › AI providers).

- OpenAI-compatible providers (OpenRouter, Groq, Gemini, Ollama Cloud and any added provider):
  `GET {base_url}/models`. OpenRouter adds a name, the context length, per-token prices and the input
  modalities; other providers send at least the id.
- Local Ollama: `GET {base_url}/api/tags` (installed models, all free).

The key goes only to the provider's own address (the one it was entered for). Lists are cached for ten
minutes per provider and address, so the form stays quick while you add several models.
"""

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

    @property
    def status(self):
        """The studio's status for it: free, paid, or "" (unknown)."""
        return "" if self.free is None else ("free" if self.free else "paid")

    @property
    def option_label(self):
        parts = [self.name or self.id]
        if self.name and self.name != self.id:
            parts.append(f"({self.id})")
        details = []
        if self.context:
            details.append(
                f"{self.context // 1000}k context" if self.context >= 1000 else f"{self.context} context"
            )
        if self.price:
            details.append(self.price)
        if self.vision:
            details.append("vision: reads images")
        return " ".join(parts) + (f" · {' · '.join(details)}" if details else "")


def _per_million(value):
    try:
        return float(value) * 1_000_000
    except (TypeError, ValueError):
        return None


def _money(value):
    return f"${value:.2f}" if value >= 0.01 else f"${value:.4f}".rstrip("0").rstrip(".")


def _openai_entry(item):
    model_id = str(item.get("id") or "").strip()
    if model_id.startswith("models/"):  # Gemini's OpenAI-compatible list
        model_id = model_id.removeprefix("models/")
    pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
    prompt, completion = _per_million(pricing.get("prompt")), _per_million(pricing.get("completion"))
    free, price = None, ""
    if prompt is not None and completion is not None:
        free = prompt == 0 and completion == 0
        price = "free" if free else f"{_money(prompt)} in / {_money(completion)} out per M tokens"
    elif model_id.endswith(":free"):
        free = True
    modalities = (item.get("architecture") or {}).get("input_modalities") or []
    context = item.get("context_length") or item.get("context_window")
    return RemoteModel(
        id=model_id,
        name=str(item.get("name") or "").strip(),
        free=free,
        context=context if isinstance(context, int) else None,
        price=price,
        vision="image" in modalities,
    )


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
        models = [
            RemoteModel(id=str(item.get("name") or item.get("model") or ""), free=True)
            for item in items or []
            if isinstance(item, dict)
        ]
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
