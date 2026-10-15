"""Provider registry: settings.AI_PROVIDERS plus what an admin stored or added (ADR 0003, ADR 0008).

A key stored through the admin (encrypted, apps.ai.secrets) takes precedence over the provider's
environment variable; without one, the environment variable is used as before. Keys are decrypted only
when a call needs them.
"""

import os
from dataclasses import dataclass, replace

from django.conf import settings

from . import secrets
from .types import ProviderError


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    adapter: str  # "openai_compat" | "ollama_native" | "cloudflare_images" | "comfyui"
    base_url: str
    image_adapter: str = ""  # a text provider's image API (apps.ai.service.image_adapter), e.g. Gemini's
    api_key_env: str | None = None
    account_env: str | None = None  # Cloudflare account id, Google Programmable Search engine id
    account_label: str = "Account ID"
    label: str = ""
    stored_key: str = ""  # encrypted
    stored_account: str = ""  # encrypted
    key_required: bool = False  # added providers always need a key
    added: bool = False

    def _stored(self, token):
        try:
            return secrets.decrypt(token)
        except secrets.SecretsUnavailable as error:
            raise ProviderError("not_configured", str(error)) from None

    @property
    def api_key(self):
        if self.stored_key:
            return self._stored(self.stored_key)
        return os.environ.get(self.api_key_env, "") if self.api_key_env else ""

    @property
    def account_id(self):
        if self.stored_account:
            return self._stored(self.stored_account)
        return os.environ.get(self.account_env, "") if self.account_env else ""

    @property
    def needs_key(self):
        return bool(self.api_key_env or self.key_required)

    @property
    def key_source(self):
        """ "studio", "env" or "" (no key): where the key in use comes from."""
        if self.stored_key:
            return "studio"
        if self.api_key_env and os.environ.get(self.api_key_env):
            return "env"
        return ""

    @property
    def is_configured(self):
        if self.needs_key and not self.key_source:
            return False
        return not (self.account_env and not (self.stored_account or os.environ.get(self.account_env)))

    @property
    def headers(self):
        return {"User-Agent": settings.AI_USER_AGENT}


def stored_configs():
    """ProviderConfig rows, or none when the database isn't reachable."""
    from django.db import DatabaseError

    from .models import ProviderConfig

    try:
        return list(ProviderConfig.objects.all())
    except DatabaseError:
        return []


def get_providers():
    specs = {name: ProviderSpec(name=name, **config) for name, config in settings.AI_PROVIDERS.items()}
    for row in stored_configs():
        if row.name in specs:
            specs[row.name] = replace(
                specs[row.name],
                label=row.label,
                stored_key=row.api_key_encrypted,
                stored_account=row.account_id_encrypted,
            )
        elif row.base_url:
            specs[row.name] = ProviderSpec(
                name=row.name,
                adapter="openai_compat",
                base_url=row.base_url,
                label=row.label,
                stored_key=row.api_key_encrypted,
                key_required=True,
                added=True,
            )
    return specs


def get_provider(name):
    try:
        spec = get_providers()[name]
    except KeyError:
        raise ProviderError("not_configured", f"Unknown provider '{name}'") from None
    if not spec.is_configured:
        if not spec.key_source and (spec.added or spec.api_key_env):
            where = f"{spec.api_key_env} in .env or " if spec.api_key_env else ""
            raise ProviderError(
                "not_configured", f"Provider '{name}' needs {where}a key in Settings › AI providers"
            )
        raise ProviderError("not_configured", f"Provider '{name}' needs {spec.account_env} in .env")
    return spec
