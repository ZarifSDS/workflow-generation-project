"""Models the studio can offer in its dropdowns, with availability verified 2026-10-13.

`status` is one of: free, limited, paid, unavailable. Only free and limited models are selectable;
paid and unavailable ones are listed with their reason so nobody picks them by mistake.
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

    @property
    def key(self):
        return f"{self.provider}::{self.model}"

    @property
    def selectable(self):
        return self.status in {"free", "limited"}


PROVIDER_LABELS = {
    "ollama": "Ollama (your PC)",
    "ollama_cloud": "Ollama Cloud",
    "gemini": "Gemini",
    "groq": "Groq",
    "cloudflare": "Cloudflare",
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
    # Cloudflare images (free daily allowance)
    CatalogModel(
        "cloudflare",
        "@cf/black-forest-labs/flux-2-klein-4b",
        "FLUX.2 klein 4B",
        "image",
        typical_seconds=10,
        options={"width": 1024, "height": 576},
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


def find(provider, model):
    return next((m for m in CATALOG if m.provider == provider and m.model == model), None)


def by_key(key):
    provider, _, model = key.partition("::")
    return find(provider, model)


def grouped(kind):
    """[(group label, [CatalogModel, ...]), ...] for a dropdown; unavailable models last."""
    groups = {}
    for item in CATALOG:
        if item.kind != kind:
            continue
        group = "Not available" if not item.selectable else PROVIDER_LABELS.get(item.provider, item.provider)
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
