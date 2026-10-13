"""Provider registry, built from settings.AI_PROVIDERS. API keys are read from the environment only."""

import os
from dataclasses import dataclass

from django.conf import settings

from .types import ProviderError


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    adapter: str  # "openai_compat" | "ollama_native" | "cloudflare_images" | "comfyui"
    base_url: str
    api_key_env: str | None = None
    account_env: str | None = None  # Cloudflare account id

    @property
    def api_key(self):
        return os.environ.get(self.api_key_env, "") if self.api_key_env else ""

    @property
    def account_id(self):
        return os.environ.get(self.account_env, "") if self.account_env else ""

    @property
    def is_configured(self):
        if self.api_key_env and not self.api_key:
            return False
        return not (self.account_env and not self.account_id)

    @property
    def headers(self):
        return {"User-Agent": settings.AI_USER_AGENT}


def get_providers():
    return {name: ProviderSpec(name=name, **config) for name, config in settings.AI_PROVIDERS.items()}


def get_provider(name):
    try:
        spec = get_providers()[name]
    except KeyError:
        raise ProviderError("not_configured", f"Unknown provider '{name}'") from None
    if not spec.is_configured:
        missing = spec.api_key_env if not spec.api_key else spec.account_env
        raise ProviderError("not_configured", f"Provider '{name}' needs {missing} in .env")
    return spec
