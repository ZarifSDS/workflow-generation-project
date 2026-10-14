"""Models the studio can offer in its dropdowns, with availability verified 2026-10-13.

`status` is one of: free, limited, paid, unavailable. Only free and limited models are selectable;
paid and unavailable ones are listed with their reason so nobody picks them by mistake. Models an admin
adds under Settings › AI providers (AddedModel, ADR 0008) are merged in and are selectable even when
paid: adding one is the opt-in. They replace a built-in entry with the same provider and model.
`typical_seconds` is a rough per-step duration shown in the UI, measured in the M2 evaluation.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogModel:
    provider: str
    model: str
    label: str
    kind: str  # "text" | "image"
    status: str = "free"
    reason: str = ""
    typical_seconds: int | None = None
    options: dict | None = None
    added: bool = False  # added by an admin

    @property
    def key(self):
        return f"{self.provider}::{self.model}"

    @property
    def selectable(self):
        return self.status in {"free", "limited"} or (self.added and self.status == "paid")


PROVIDER_LABELS = {
    "ollama": "Ollama (your PC)",
    "ollama_cloud": "Ollama Cloud",
    "gemini": "Gemini",
    "groq": "Groq",
    "cloudflare": "Cloudflare",
    "comfyui": "ComfyUI (your PC)",
    "serper": "Serper (Google results)",
    "brave_search": "Brave Search",
    "google_cse": "Google Programmable Search",
}

CATALOG = [
    # Local Ollama (free, private; speed depends on the host)
    CatalogModel(
        "ollama",
        "huihui_ai/Qwen3.8-abliterated:latest",
        "Qwen3.8 27B",
        "text",
        typical_seconds=1130,
        options={"num_ctx": 32768, "think": True},
    ),
    CatalogModel(
        "ollama",
        "hf.co/mradermacher/Huihui-Ornith-1.5-35B-A3B-abliterated-i1-GGUF:latest",
        "Ornith 35B-A3B",
        "text",
        typical_seconds=300,
        options={"num_ctx": 32768},
    ),
    CatalogModel(
        "ollama",
        "hf.co/mradermacher/Huihui-Ornith-1.5-9B-abliterated-GGUF:latest",
        "Ornith 9B",
        "text",
        options={"num_ctx": 32768},
    ),
    CatalogModel(
        "ollama",
        "hf.co/huihui-ai/Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-GGUF:latest",
        "Qwythos 9B (1M context)",
        "text",
        options={"num_ctx": 32768},
    ),
    CatalogModel(
        "ollama",
        "glm-4.7-flash:latest",
        "GLM 4.7 Flash",
        "text",
        typical_seconds=150,
        options={"num_ctx": 32768, "think": False},
    ),
    # Ollama Cloud free plan
    CatalogModel("ollama_cloud", "nemotron-3-ultra", "Nemotron 3 Ultra", "text", typical_seconds=60),
    CatalogModel("ollama_cloud", "gpt-oss:120b", "gpt-oss 120B", "text", typical_seconds=10),
    CatalogModel("ollama_cloud", "gemma4:31b", "Gemma 4 31B", "text", typical_seconds=5),
    CatalogModel("ollama_cloud", "kimi-k3", "Kimi K3", "text", status="paid", reason="Paid plan only"),
    CatalogModel(
        "ollama_cloud",
        "deepseek-v4-pro:0813",
        "DeepSeek V4 Pro",
        "text",
        status="paid",
        reason="Paid plan only",
    ),
    # Gemini free tier
    CatalogModel("gemini", "gemini-3.8-flash", "Gemini 3.8 Flash", "text", typical_seconds=30),
    CatalogModel("gemini", "gemini-3.7-flash", "Gemini 3.7 Flash", "text", typical_seconds=30),
    CatalogModel("gemini", "gemini-pro-latest", "Gemini Pro", "text", status="paid", reason="No free quota"),
    # Groq free tier
    CatalogModel("groq", "openai/gpt-oss-120b", "gpt-oss 120B (Groq)", "text", typical_seconds=5),
    CatalogModel(
        "groq",
        "qwen/qwen3.8-27b",
        "Qwen3.8 27B (Groq)",
        "text",
        status="limited",
        reason="Free tier allows 1,000 output tokens a minute; may fail on long drafts",
        typical_seconds=5,
    ),
    # ComfyUI on your PC: the model is a workflow file exported in API format (docs/setup.md)
    CatalogModel(
        "comfyui",
        "flux2-klein-4b.json",
        "FLUX.2 klein 4B (ComfyUI)",
        "image",
        status="limited",
        reason="Needs ComfyUI running on your PC with this workflow exported (docs/setup.md)",
        options={"width": 1440, "height": 816},
    ),
    # Cloudflare images (free daily allowance)
    CatalogModel(
        "cloudflare",
        "@cf/black-forest-labs/flux-2-klein-4b",
        "FLUX.2 klein 4B",
        "image",
        typical_seconds=12,
        options={"width": 1440, "height": 816},
    ),
    CatalogModel(
        "cloudflare",
        "@cf/black-forest-labs/flux-1-schnell",
        "FLUX.1 schnell",
        "image",
        typical_seconds=8,
        options={"steps": 8},
    ),
    CatalogModel(
        "cloudflare",
        "@cf/black-forest-labs/flux-2-dev",
        "FLUX.2 dev",
        "image",
        status="unavailable",
        reason="Non-commercial licence",
    ),
]


ADDED_CACHE_KEY = "ai:added-models"
ADDED_CACHE_SECONDS = 30


def _added():
    """(models, labels) an admin added; cached briefly, cleared when they change (apps.ai.signals)."""
    from django.core.cache import cache
    from django.db import DatabaseError

    from .models import AddedModel, ProviderConfig

    cached = cache.get(ADDED_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        labels = {row.name: row.label for row in ProviderConfig.objects.all() if row.label}
        models = [
            CatalogModel(
                row.provider,
                row.model,
                row.label,
                "text",
                status=row.status,
                reason="Paid: billed to your key" if row.status == "paid" else "",
                typical_seconds=row.typical_seconds,
                added=True,
            )
            for row in AddedModel.objects.all()
        ]
    except DatabaseError:
        return [], {}
    cache.set(ADDED_CACHE_KEY, (models, labels), ADDED_CACHE_SECONDS)
    return models, labels


def clear_cache():
    from django.core.cache import cache

    cache.delete(ADDED_CACHE_KEY)


def all_models():
    added, _ = _added()
    replaced = {m.key for m in added}
    return [m for m in CATALOG if m.key not in replaced] + added


def usual_status(provider):
    """The status most of a provider's built-in models have (free-tier providers such as Groq report no
    prices), for a newly added model whose price the provider doesn't list; "paid" when none is built in."""
    from collections import Counter

    statuses = Counter(m.status for m in CATALOG if m.provider == provider and m.status != "unavailable")
    return statuses.most_common(1)[0][0] if statuses else "paid"


def provider_labels():
    _, labels = _added()
    return {**labels, **PROVIDER_LABELS}


def provider_label(provider):
    return provider_labels().get(provider, provider)


def find(provider, model):
    return next((m for m in all_models() if m.provider == provider and m.model == model), None)


def by_key(key):
    provider, _, model = key.partition("::")
    return find(provider, model)


def grouped(kind):
    """[(group label, [CatalogModel, ...]), ...] for a dropdown; unavailable models last."""
    groups = {}
    labels = provider_labels()
    for item in all_models():
        if item.kind != kind:
            continue
        group = "Not available" if not item.selectable else labels.get(item.provider, item.provider)
        groups.setdefault(group, []).append(item)
    ordered = [(name, items) for name, items in groups.items() if name != "Not available"]
    if "Not available" in groups:
        ordered.append(("Not available", groups["Not available"]))
    return ordered


def describe_duration(seconds):
    if not seconds:
        return ""
    if seconds < 90:
        return f"~{seconds} s"
    return f"~{round(seconds / 60)} min"
