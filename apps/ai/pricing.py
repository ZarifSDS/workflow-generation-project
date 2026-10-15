"""Prices per input and output token and context windows for every model (docs/pricing-and-ux-plan.md).

The model sync (apps.ai.remote_models.sync) calls `update` with what the provider listed. Each value comes
from the first source that has it, and its source is kept beside it:

1. a value entered by hand (Manage models): never overwritten;
2. the provider's own list (OpenRouter's prices; Groq's and OpenRouter's context windows; local Ollama's
   context from /api/show);
3. the reference price list: LiteLLM's model_prices_and_context_window.json (MIT), read at most once a
   week during a sync and kept in the database (PriceReference);
4. nothing: the value stays blank and the studio says "unknown". Nothing is guessed.

How a key is billed (ProviderConfig.billing) decides whether a price becomes a cost: a free-tier or
subscription key shows the list price for reference and costs $0 a call.
"""

import logging
import re
import time
from datetime import timedelta
from decimal import Decimal

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

REFERENCE_EVERY = timedelta(days=7)
TIMEOUT = httpx.Timeout(60, connect=10)
MANUAL = "manual"  # ModelInfo.Source.MANUAL: a value entered by hand is never overwritten
CACHE_KEY = "ai:model-info"
BILLING_CACHE_KEY = "ai:billings"
CACHE_SECONDS = 60

# How a provider's key is usually billed, when the admin hasn't said (ProviderConfig.billing).
LOCAL = "local"  # your own machine: always free
USUAL_BILLING = {
    "ollama": LOCAL,
    "comfyui": LOCAL,
    "ollama_cloud": "subscription",
    "gemini": "free_tier",
    "groq": "free_tier",
    "cloudflare": "free_tier",
}
BILLING_LABELS = {
    LOCAL: "Runs on your machine (free)",
    "per_token": "Pay per token",
    "free_tier": "Free tier",
    "subscription": "Subscription (flat fee)",
}
# The reference list's provider names for ours (its keys look like "groq/openai/gpt-oss-120b").
REFERENCE_PROVIDERS = {
    "openrouter": ("openrouter",),
    "groq": ("groq",),
    "gemini": ("gemini",),
    "ollama_cloud": ("ollama", "ollama_chat"),
    "ollama": ("ollama", "ollama_chat"),
}


# ---- Billing ----


def billing(provider):
    """per_token, free_tier, subscription or local: the admin's choice, else the usual one."""
    return billings().get(provider, "per_token")


def billings():
    """{provider: billing} for every provider with a row or a usual billing (cached with the prices)."""
    if (memo := _memoised(BILLING_CACHE_KEY)) is not None:
        return memo
    cached = cache.get(BILLING_CACHE_KEY)
    if cached is not None:
        return _remember(BILLING_CACHE_KEY, cached)
    from .models import ProviderConfig

    found = dict(USUAL_BILLING)
    try:
        for name, chosen in ProviderConfig.objects.values_list("name", "billing"):
            if chosen and found.get(name) != LOCAL:
                found[name] = chosen
    except DatabaseError:
        return found
    cache.set(BILLING_CACHE_KEY, found, CACHE_SECONDS)
    return _remember(BILLING_CACHE_KEY, found)


# ---- The reference list ----


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def parse_reference(data):
    """LiteLLM's JSON reduced to chat models: {key: {provider, in, out, cached, context, max_output}},
    prices per token as the file has them."""
    entries = {}
    for key, item in (data or {}).items():
        if key == "sample_spec" or not isinstance(item, dict):
            continue
        if item.get("mode") not in (None, "chat", "responses", "completion"):
            continue
        entry = {
            "provider": str(item.get("litellm_provider") or ""),
            "in": _number(item.get("input_cost_per_token")),
            "out": _number(item.get("output_cost_per_token")),
            "cached": _number(item.get("cache_read_input_token_cost")),
            "context": item.get("max_input_tokens") or item.get("max_tokens"),
            "max_output": item.get("max_output_tokens"),
        }
        for size in ("context", "max_output"):
            if not isinstance(entry[size], int):
                entry[size] = None
        if entry["in"] is None and entry["context"] is None:
            continue
        entries[key] = entry
    return entries


def refresh_reference(force=False):
    """Read the reference list again when it is older than a week (or `force`); never raises."""
    from .models import PriceReference

    url = settings.AI_PRICE_REFERENCE_URL
    row = PriceReference.objects.first() or PriceReference(url=url or "")
    if not url:
        return row  # switched off (tests)
    if not force and row.fetched_at and timezone.now() - row.fetched_at < REFERENCE_EVERY and row.entries:
        return row
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": settings.AI_USER_AGENT},
            timeout=TIMEOUT,
            follow_redirects=False,
        )
        response.raise_for_status()
        entries = parse_reference(response.json())
        if not entries:
            raise ValueError("the list held no chat models")
        row.entries, row.error = entries, ""
    except (httpx.HTTPError, ValueError) as error:
        row.error = f"couldn't read the reference list ({error.__class__.__name__}: {error})"[:300]
        logger.warning("Price reference: %s", row.error)
    row.url, row.fetched_at = url, timezone.now()
    row.save()
    return row


def _reference_entries():
    from .models import PriceReference

    try:
        row = PriceReference.objects.first()
    except DatabaseError:
        return {}
    return row.entries if row else {}


def _variants(model):
    """The model id and the forms the reference list may use for it."""
    model = model.removeprefix("models/")
    forms = [model]
    for pattern in (r":free$", r"-latest$", r":latest$", r"-\d{8}$", r"-\d{4}-\d{2}-\d{2}$", r"@\w+$"):
        stripped = re.sub(pattern, "", model)
        if stripped not in forms:
            forms.append(stripped)
    return forms


def bare_index(entries):
    """{model id without its host prefix: [reference keys]}."""
    index = {}
    for key in entries:
        index.setdefault(key.split("/", 1)[-1], []).append(key)
        if "/" in key:
            index.setdefault(key, []).append(key)
    return index


def match_reference(provider, model, entries=None, bare=None):
    """(entry, note) for a model in the reference list, or (None, ""). Matched by the provider's own
    prefix first; a bare id that only another host lists gives its context window, never its price
    (another host's price isn't this provider's)."""
    entries = _reference_entries() if entries is None else entries
    bare = bare_index(entries) if bare is None else bare
    prefixes = REFERENCE_PROVIDERS.get(provider, ())
    for form in _variants(model):
        for prefix in prefixes:
            entry = entries.get(f"{prefix}/{form}")
            if entry:
                return entry, f"reference list: {prefix}/{form}"
        entry = entries.get(form)
        if entry and entry["provider"] in prefixes:
            return entry, f"reference list: {form}"
    for form in _variants(model):
        others = sorted(set(bare.get(form, [])))
        if len(others) == 1:
            entry = dict(entries[others[0]], **{"in": None, "out": None, "cached": None})
            return entry, f"context from the reference list: {others[0]} (another host)"
    return None, ""


# ---- Updating ModelInfo ----


def _dec(value):
    return None if value is None else Decimal(str(round(float(value), 6)))


def update(provider, listed=(), model_ids=()):
    """Fill ModelInfo for a provider's models: `listed` are RemoteModel entries from its own list,
    `model_ids` are further models (built in, added by hand) resolved from the reference list only.
    Returns the number of rows written. Never raises: a problem here never breaks a sync."""
    from .models import ModelInfo

    try:
        entries = _reference_entries()
        bare = bare_index(entries)
        own = {m.id: m for m in listed}
        ids = list(dict.fromkeys([*own, *model_ids]))
        rows = {row.model: row for row in ModelInfo.objects.filter(provider=provider, model__in=ids)}
        now, written = timezone.now(), 0
        with transaction.atomic():
            for model_id in ids:
                row = rows.get(model_id) or ModelInfo(provider=provider, model=model_id)
                _resolve(row, own.get(model_id), *match_reference(provider, model_id, entries, bare), now)
                row.save()
                written += 1
        clear_cache()
        return written
    except Exception:  # noqa: BLE001 - prices are an extra: never fail the sync that called this
        logger.exception("Updating model prices for %s failed", provider)
        return 0


def _resolve(row, remote, entry, note, now):
    """A hand-entered value is kept; so is a provider-listed one when this pass has no listing."""
    local = USUAL_BILLING.get(row.provider) == LOCAL
    keep_price = row.price_source == MANUAL or (remote is None and row.price_source == "provider")
    keep_context = row.context_source == MANUAL or (remote is None and row.context_source == "provider")
    if not keep_price:
        if local:
            row.input_per_m = row.output_per_m = Decimal("0")
            row.cached_input_per_m, row.price_source = None, "provider"
        elif remote and remote.input_per_m is not None and remote.output_per_m is not None:
            row.input_per_m, row.output_per_m = _dec(remote.input_per_m), _dec(remote.output_per_m)
            row.cached_input_per_m, row.price_source = _dec(remote.cached_input_per_m), "provider"
        elif entry and entry.get("in") is not None and entry.get("out") is not None:
            row.input_per_m = _dec(entry["in"] * 1_000_000)
            row.output_per_m = _dec(entry["out"] * 1_000_000)
            cached = entry.get("cached")
            row.cached_input_per_m = _dec(cached * 1_000_000) if cached is not None else None
            row.price_source = "reference"
    if not keep_context:
        if remote and remote.context:
            row.context_window, row.context_source = remote.context, "provider"
            row.max_output = remote.max_output or row.max_output
        elif entry and entry.get("context"):
            row.context_window, row.context_source = entry["context"], "reference"
            row.max_output = entry.get("max_output") or row.max_output
    if entry and (row.price_source == "reference" or row.context_source == "reference"):
        row.note = note[:200]
    row.checked_at = now


def update_all():
    """Resolve every text model in the lists (built in, listed, by hand) against the reference list,
    keeping provider-listed values; used after a sync and by Refresh. Returns rows written."""
    from . import catalog

    by_provider = {}
    for item in catalog.all_models():
        if item.kind == "text":
            by_provider.setdefault(item.provider, []).append(item.model)
    return sum(update(provider, model_ids=ids) for provider, ids in by_provider.items())


# ---- Reading ----


MEMO_SECONDS = 5  # a page renders hundreds of options: read the shared cache once, not once an option
_memo = {}


def _memoised(key):
    hit = _memo.get(key)
    return hit[1] if hit and hit[0] > time.monotonic() else None


def _remember(key, value):
    seconds = getattr(settings, "AI_PRICE_MEMO_SECONDS", MEMO_SECONDS)  # 0 in tests: no state between them
    if seconds:
        _memo[key] = (time.monotonic() + seconds, value)
    return value


def clear_cache():
    _memo.clear()
    cache.delete_many([CACHE_KEY, BILLING_CACHE_KEY])


def info_map():
    """{"provider::model": {in, out, cached, context, max_output, price_source, context_source, note}}."""
    if (memo := _memoised(CACHE_KEY)) is not None:
        return memo
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return _remember(CACHE_KEY, cached)
    from .models import ModelInfo

    try:
        found = {
            f"{row.provider}::{row.model}": {
                "in": row.input_per_m,
                "out": row.output_per_m,
                "cached": row.cached_input_per_m,
                "context": row.context_window,
                "max_output": row.max_output,
                "price_source": row.price_source,
                "context_source": row.context_source,
                "note": row.note,
            }
            for row in ModelInfo.objects.all()
        }
    except DatabaseError:
        return {}
    cache.set(CACHE_KEY, found, CACHE_SECONDS)
    return _remember(CACHE_KEY, found)


def info(provider, model):
    return info_map().get(f"{provider}::{model}")


def money(value):
    """$0.10, $0.0375, $12: enough digits to tell cheap models apart."""
    if value is None:
        return ""
    value = float(value)
    if value == 0:
        return "$0"
    if value >= 1:
        return f"${value:,.2f}".replace(".00", "")
    if value >= 0.01:
        return f"${value:.2f}"
    return "$" + f"{value:.6f}".rstrip("0").rstrip(".")


def context_label(tokens):
    if not tokens:
        return ""
    if tokens >= 1_000_000 and tokens % 1_000_000 == 0:
        return f"{tokens // 1_000_000}M context"
    return f"{round(tokens / 1000):,}k context"


def facts(provider, model, billing_mode=None):
    """The short line a dropdown option carries: "$0.10 / $0.50 per M · 1,050k context", with the
    billing said plainly ("free tier", "on your plan", "free: your machine")."""
    found = info(provider, model) or {}
    mode = billing_mode or billing(provider)
    parts = []
    if mode == LOCAL:
        parts.append("free: your machine")
    elif found.get("in") is not None and found.get("out") is not None:
        price = f"{money(found['in'])} / {money(found['out'])} per M"
        if found["in"] == 0 and found["out"] == 0:
            price = "free"
        if mode == "free_tier" and price != "free":
            price = f"free tier (list {price})"
        elif mode == "subscription" and price != "free":
            price = f"on your plan (list {price})"
        parts.append(price)
    elif mode == "free_tier":
        parts.append("free tier")
    elif mode == "subscription":
        parts.append("on your plan")
    else:
        parts.append("price unknown")
    if found.get("context"):
        parts.append(context_label(found["context"]))
    return " · ".join(parts)


def cost(provider, model, input_tokens, output_tokens, billed=None, billing_mode=None):
    """(Decimal or None, kind) for one call. `billed` is what the provider reported (OpenRouter's
    usage.cost); otherwise tokens x price for a pay-per-token key."""
    mode = billing_mode or billing(provider)
    if mode in (LOCAL, "free_tier", "subscription"):
        return Decimal("0"), "free"
    if billed is not None:
        return _dec(billed), "billed"
    found = info(provider, model) or {}
    if found.get("in") is None or found.get("out") is None or input_tokens is None:
        return None, "unknown"
    total = (Decimal(input_tokens) * found["in"] + Decimal(output_tokens or 0) * found["out"]) / 1_000_000
    return total.quantize(Decimal("0.000001")), "estimated"
